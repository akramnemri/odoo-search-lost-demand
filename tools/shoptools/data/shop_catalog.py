"""The shop catalog: synthetic enrichment, hidden sets and out-of-stock set on top of the slice (Task 2.3b).

`slice_builder.run_build_slice` calls `build_shop_catalog` after the 2.3a steps. The 2.3a outputs do not change:
every 2.3b draw uses its own stream (`prices`, `stock`, `vendor-terms`, `hidden-test`, `hidden-dev`, `out-of-stock`).
Rules: `enrichment.py` (synthetic fields) and `hidden_sets.py` (protocol v1.1 §4, option B2).

Outputs (tables, written by slice_builder): `products.parquet` (what the Odoo importer reads, Task 2.4),
`vendors.parquet`, `hidden-test.parquet`, `hidden-dev.parquet`, `out-of-stock.parquet`; and an aggregates-only report,
results/summary/enrichment-report.md (`render_enrichment_report`).
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING, Any

from shoptools.data import enrichment
from shoptools.data.normalize import normalize_query
from shoptools.data.hidden_sets import (
    HiddenSet,
    draw_hidden_set,
    draw_out_of_stock,
    exact_targets,
    query_strata,
)

if TYPE_CHECKING:
    import pyarrow as pa

PRODUCTS_FILE = "products.parquet"
VENDORS_FILE = "vendors.parquet"
HIDDEN_TEST_FILE = "hidden-test.parquet"
HIDDEN_DEV_FILE = "hidden-dev.parquet"
OUT_OF_STOCK_FILE = "out-of-stock.parquet"
OUTPUT_FILES = (PRODUCTS_FILE, VENDORS_FILE, HIDDEN_TEST_FILE, HIDDEN_DEV_FILE, OUT_OF_STOCK_FILE)
SEED_STREAMS = ("prices", "stock", "vendor-terms", "hidden-test", "hidden-dev", "out-of-stock")
SYNTHETIC_FIELDS = (
    "category",
    "list_price_cents",
    "stock_qty",
    "vendor_id",
    "vendor_price_cents",
    "vendor_min_qty",
    "vendor_lead_days",
)


@dataclass(frozen=True)
class ShopSettings:
    categories_file: str  # relative to the repository root
    price_min_dollars: int
    price_max_dollars: int
    stock_range: tuple[int, int]
    vendors: int
    vendor_price_share: tuple[float, float]
    vendor_min_qty: tuple[int, int]
    vendor_lead_days: tuple[int, int]
    description_max_chars: int
    hidden_query_share: float
    out_of_stock_share: float


def parse_shop_settings(parsed: dict[str, Any]) -> ShopSettings:
    """The [enrichment], [hidden] and [out_of_stock] tables of slice.toml. Raises KeyError/TypeError/ValueError."""
    shop = parsed["enrichment"]

    def bounds(table: dict[str, Any], cast: type) -> tuple[Any, Any]:
        low, high = cast(table["min"]), cast(table["max"])
        if not 0 < low <= high:
            raise ValueError(f"need 0 < min <= max, found {table}")
        return low, high

    settings = ShopSettings(
        categories_file=str(shop["categories_file"]),
        price_min_dollars=int(shop["price"]["min_dollars"]),
        price_max_dollars=int(shop["price"]["max_dollars"]),
        stock_range=bounds(shop["stock"], int),
        vendors=int(shop["vendors"]),
        vendor_price_share=bounds(shop["vendor_price_share"], float),
        vendor_min_qty=bounds(shop["vendor_min_qty"], int),
        vendor_lead_days=bounds(shop["vendor_lead_days"], int),
        description_max_chars=int(shop["description_max_chars"]),
        hidden_query_share=float(parsed["hidden"]["query_share"]),
        out_of_stock_share=float(parsed["out_of_stock"]["share"]),
    )
    if not 0 < settings.price_min_dollars <= settings.price_max_dollars:
        raise ValueError("enrichment.price needs 0 < min_dollars <= max_dollars")
    if settings.vendor_price_share[1] >= 1:
        raise ValueError("enrichment.vendor_price_share.max must be below 1 (vendors sell below the list price)")
    if settings.vendors < 1 or settings.description_max_chars < 100:
        raise ValueError("enrichment.vendors must be >= 1 and description_max_chars >= 100")
    for name, share in (("hidden.query_share", settings.hidden_query_share), ("out_of_stock.share", settings.out_of_stock_share)):
        if not 0 < share < 1:
            raise ValueError(f"{name} must be between 0 and 1")
    return settings


@dataclass(frozen=True)
class ShopCatalog:
    tables: dict[str, pa.Table]
    statistics: dict[str, Any]


def build_shop_catalog(
    catalog: pa.Table,
    judgments: Sequence[tuple[str, int, str, str]],  # (query set, query id, product id, label)
    dev_queries: Sequence[int],
    test_queries: Sequence[int],
    settings: ShopSettings,
    rules: enrichment.CategoryRules,
    rng_for: Callable[[str], random.Random],
) -> ShopCatalog:
    rows = catalog.to_pylist()  # ~20k rows, sorted by product id: draws are consumed in that order
    category_of = {
        row["product_id"]: enrichment.assign_category(row["product_title"], row["product_bullet_point"], rules)
        for row in rows
    }

    targets = exact_targets((query_id, product_id, label) for _, query_id, product_id, label in judgments)
    strata = query_strata(targets, category_of, rules.names)
    hidden_test = draw_hidden_set(
        "hidden-test", test_queries, targets, strata, settings.hidden_query_share, rng_for("hidden-test"), rules.names
    )
    hidden_dev = draw_hidden_set(
        "hidden-dev",
        dev_queries,
        targets,
        strata,
        settings.hidden_query_share,
        rng_for("hidden-dev"),
        rules.names,
        forbidden_products=hidden_test.products,
    )
    hidden_products = hidden_test.products | hidden_dev.products
    out_of_stock, oos_candidates = draw_out_of_stock(
        targets,
        set(hidden_test.queries) | set(hidden_dev.queries),
        hidden_products,
        len(rows),
        settings.out_of_stock_share,
        rng_for("out-of-stock"),
    )

    products = _enrich(rows, category_of, set(out_of_stock), settings, rules, rng_for)
    tables = _tables(products, settings, hidden_test, hidden_dev, strata, out_of_stock, category_of)
    statistics = _statistics(
        products, rules, settings, hidden_test, hidden_dev, targets, out_of_stock, oos_candidates, category_of
    )
    return ShopCatalog(tables, statistics)


def _enrich(
    rows: list[dict[str, Any]],
    category_of: dict[str, str],
    out_of_stock: set[str],
    settings: ShopSettings,
    rules: enrichment.CategoryRules,
    rng_for: Callable[[str], random.Random],
) -> list[dict[str, Any]]:
    prices, stock, terms = rng_for("prices"), rng_for("stock"), rng_for("vendor-terms")
    products = []
    for row in rows:
        product_id = row["product_id"]
        category = rules.by_name(category_of[product_id])
        price = enrichment.draw_price_cents(category, prices, settings.price_min_dollars, settings.price_max_dollars)
        quantity = enrichment.draw_stock(stock, *settings.stock_range)  # drawn for every product: see module doc
        vendor_price, min_qty, lead_days = enrichment.draw_vendor_terms(
            price, terms, settings.vendor_price_share, settings.vendor_min_qty, settings.vendor_lead_days
        )
        products.append(
            {
                "product_id": product_id,
                "name": row["product_title"],
                "description": enrichment.plain_description(
                    row["product_description"], row["product_bullet_point"], settings.description_max_chars
                ),
                "brand": row["product_brand"],
                "color": row["product_color"],
                "category": category.name,
                "list_price_cents": price,
                "stock_qty": 0 if product_id in out_of_stock else quantity,
                "vendor_id": enrichment.vendor_for(row["product_brand"], product_id, settings.vendors),
                "vendor_price_cents": vendor_price,
                "vendor_min_qty": min_qty,
                "vendor_lead_days": lead_days,
            }
        )
    return products


def _tables(
    products: list[dict[str, Any]],
    settings: ShopSettings,
    hidden_test: HiddenSet,
    hidden_dev: HiddenSet,
    strata: dict[int, str],
    out_of_stock: list[str],
    category_of: dict[str, str],
) -> dict[str, pa.Table]:
    import pyarrow as pa

    text, integer = pa.string(), pa.int64()
    product_schema = pa.schema(
        [
            ("product_id", text),
            ("name", text),
            ("description", text),
            ("brand", text),
            ("color", text),
            ("category", text),
            ("list_price_cents", integer),
            ("stock_qty", integer),
            ("vendor_id", integer),
            ("vendor_price_cents", integer),
            ("vendor_min_qty", integer),
            ("vendor_lead_days", integer),
        ]
    )
    hidden_schema = pa.schema([("query_id", integer), ("product_id", text), ("query_category", text)])

    def hidden_table(hidden: HiddenSet) -> pa.Table:
        return pa.table(
            {
                "query_id": [query_id for query_id, _ in hidden.pairs],
                "product_id": [product_id for _, product_id in hidden.pairs],
                "query_category": [strata[query_id] for query_id, _ in hidden.pairs],
            },
            schema=hidden_schema,
        )

    vendors = range(1, settings.vendors + 1)
    return {
        PRODUCTS_FILE: pa.Table.from_pylist(products, schema=product_schema),
        VENDORS_FILE: pa.table(
            {"vendor_id": list(vendors), "name": [enrichment.vendor_name(number) for number in vendors]},
            schema=pa.schema([("vendor_id", integer), ("name", text)]),
        ),
        HIDDEN_TEST_FILE: hidden_table(hidden_test),
        HIDDEN_DEV_FILE: hidden_table(hidden_dev),
        OUT_OF_STOCK_FILE: pa.table(
            {"product_id": out_of_stock, "category": [category_of[product_id] for product_id in out_of_stock]},
            schema=pa.schema([("product_id", text), ("category", text)]),
        ),
    }


# --- statistics and report -----------------------------------------------------------------------------------


def _spread(values: list[int]) -> dict[str, int]:
    """Nearest-rank p10 / median / p90, min and max (integers: no float formatting differences)."""
    if not values:
        return {"min": 0, "p10": 0, "median": 0, "p90": 0, "max": 0}
    ordered = sorted(values)

    def rank(share: float) -> int:
        return ordered[min(len(ordered) - 1, max(0, round(share * len(ordered)) - 1))]

    return {"min": ordered[0], "p10": rank(0.1), "median": rank(0.5), "p90": rank(0.9), "max": ordered[-1]}


def _hidden_statistics(hidden: HiddenSet, targets: dict[int, set[str]], catalog_size: int) -> dict[str, Any]:
    chosen = set(hidden.queries)
    elsewhere = {
        product_id for query_id, products in targets.items() if query_id not in chosen for product_id in products
    }
    return {
        "queries": len(hidden.queries),
        "candidate_queries": hidden.candidates,
        "excluded_overlap": hidden.excluded_overlap,
        "products": len(hidden.products),
        "catalog_share_permille": round(1000 * len(hidden.products) / catalog_size) if catalog_size else 0,
        "queries_fully_hidden": sum(1 for query_id in hidden.queries if targets[query_id] <= hidden.products),
        "products_also_exact_for_other_queries": len(hidden.products & elsewhere),
        "exact_per_query": _spread([len(targets[query_id]) for query_id in hidden.queries]),
        "per_stratum": {name: {"candidates": c, "hidden": h} for name, (c, h) in hidden.per_stratum.items()},
    }


def _statistics(
    products: list[dict[str, Any]],
    rules: enrichment.CategoryRules,
    settings: ShopSettings,
    hidden_test: HiddenSet,
    hidden_dev: HiddenSet,
    targets: dict[int, set[str]],
    out_of_stock: list[str],
    oos_candidates: int,
    category_of: dict[str, str],
) -> dict[str, Any]:
    by_category: dict[str, list[dict[str, Any]]] = {name: [] for name in rules.names}
    for product in products:
        by_category[product["category"]].append(product)
    hidden_test_categories = Counter(category_of[product_id] for product_id in hidden_test.products)
    hidden_dev_categories = Counter(category_of[product_id] for product_id in hidden_dev.products)
    oos_categories = Counter(category_of[product_id] for product_id in out_of_stock)
    vendor_counts = Counter(product["vendor_id"] for product in products)
    brands = {normalize_query(product["brand"] or "") for product in products} - {""}
    in_stock = [product["stock_qty"] for product in products if product["stock_qty"] > 0]
    return {
        "products": len(products),
        "categories": {
            name: {
                "products": len(items),
                "price_cents": _spread([item["list_price_cents"] for item in items]),
                "stock_median": _spread([item["stock_qty"] for item in items])["median"],
                "hidden_test": hidden_test_categories.get(name, 0),
                "hidden_dev": hidden_dev_categories.get(name, 0),
                "out_of_stock": oos_categories.get(name, 0),
            }
            for name, items in by_category.items()
        },
        "not_other": len(products) - len(by_category[rules.other.name]),
        "price_cents": _spread([product["list_price_cents"] for product in products]),
        "stock_in_stock": _spread(in_stock),
        "vendors": {
            "count": settings.vendors,
            "products_per_vendor": _spread([vendor_counts.get(n, 0) for n in range(1, settings.vendors + 1)]),
            "distinct_brands": len(brands),
            "products_without_brand": sum(1 for product in products if not (product["brand"] or "").strip()),
        },
        "vendor_margin_permille": _spread(
            [round(1000 * p["vendor_price_cents"] / p["list_price_cents"]) for p in products]
        ),
        "descriptions": {
            "empty": sum(1 for product in products if not product["description"]),
            "at_cap": sum(
                1 for product in products if len(product["description"]) > settings.description_max_chars - 50
            ),
        },
        "hidden_test": _hidden_statistics(hidden_test, targets, len(products)),
        "hidden_dev": _hidden_statistics(hidden_dev, targets, len(products)),
        "hidden_overlap_products": len(hidden_test.products & hidden_dev.products),
        "out_of_stock": {
            "products": len(out_of_stock),
            "candidates": oos_candidates,
            "wanted": round(
                settings.out_of_stock_share * (len(products) - len(hidden_test.products | hidden_dev.products))
            ),
        },
    }


def _dollars(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def render_enrichment_report(manifest: dict[str, Any]) -> str:
    stats = manifest["counts"]["shop_catalog"]
    settings = manifest["config"]
    total = stats["products"]
    lines = [
        "# Shop catalog: synthetic enrichment, hidden sets, out-of-stock set",
        "",
        "Generated by `uv run shop data build-slice` (Task 2.3b). Aggregates only: no product or query text.",
        "",
        "> **Synthetic data.** Categories, prices, stock, vendors and vendor terms are invented by seeded rules",
        "> (`tools/shoptools/data/enrichment.py`, `categories.toml`); they are not Amazon data. The relevance",
        "> labels are ESCI's and are not changed.",
        "",
        f"- base seed `{settings['slice']['seed']}`; streams {', '.join(f'`{s}`' for s in SEED_STREAMS)}",
        f"- category rules `{manifest['categories_file']}`, SHA-256 of the parsed values "
        f"`{manifest['categories_sha256'][:16]}…`; written from dev products only",
        f"- hidden sets: protocol v1.1 §4, option B2 (all Exact products of {settings['hidden']['query_share']:.0%} "
        "of each set's queries)",
        "",
        "## Categories",
        "",
        f"**{stats['not_other']:,} of {total:,} products ({stats['not_other'] / total:.1%}) have a category other "
        "than Other.**",
        "",
        "| category | products | share | price p10 / median / p90 | stock median | hidden-test | hidden-dev "
        "| out-of-stock |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for name, row in stats["categories"].items():
        price = row["price_cents"]
        lines.append(
            f"| {name} | {row['products']:,} | {row['products'] / total:.1%} | "
            f"{_dollars(price['p10'])} / {_dollars(price['median'])} / {_dollars(price['p90'])} | "
            f"{row['stock_median']} | {row['hidden_test']} | {row['hidden_dev']} | {row['out_of_stock']} |"
        )
    price, stock = stats["price_cents"], stats["stock_in_stock"]
    vendors, margin = stats["vendors"], stats["vendor_margin_permille"]
    lines += [
        "",
        "## Prices, stock, vendors",
        "",
        f"- list price: min {_dollars(price['min'])}, p10 {_dollars(price['p10'])}, median {_dollars(price['median'])}, "
        f"p90 {_dollars(price['p90'])}, max {_dollars(price['max'])}; every price ends in .99",
        f"- stock of products in stock: min {stock['min']}, median {stock['median']}, max {stock['max']}; "
        f"{stats['out_of_stock']['products']:,} products start at 0 (out-of-stock set)",
        f"- {vendors['count']} synthetic vendors; products per vendor min {vendors['products_per_vendor']['min']}, "
        f"median {vendors['products_per_vendor']['median']}, max {vendors['products_per_vendor']['max']}; "
        f"{vendors['distinct_brands']:,} distinct brands; {vendors['products_without_brand']:,} products without brand",
        f"- vendor price / list price: min {margin['min'] / 10:.1f} %, median {margin['median'] / 10:.1f} %, "
        f"max {margin['max'] / 10:.1f} %",
        f"- descriptions: {stats['descriptions']['empty']:,} empty (no ESCI description nor bullet points), "
        f"{stats['descriptions']['at_cap']:,} at or within 50 characters of the {settings['enrichment']['description_max_chars']:,}-character cap",
        "",
        "## Hidden sets (detection campaigns, protocol §5)",
        "",
        "| set | hidden queries | candidates | excluded (share an E product with hidden-test) | products | "
        "share of catalog | queries with every E product hidden | products also E for a non-hidden query | "
        "E products per hidden query (min / median / max) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in ("hidden_test", "hidden_dev"):
        row = stats[name]
        spread = row["exact_per_query"]
        lines.append(
            f"| {name.replace('_', '-')} | {row['queries']} | {row['candidate_queries']} | {row['excluded_overlap']} | "
            f"{row['products']:,} | {row['catalog_share_permille'] / 10:.1f} % | {row['queries_fully_hidden']} | "
            f"{row['products_also_exact_for_other_queries']} | {spread['min']} / {spread['median']} / {spread['max']} |"
        )
    oos = stats["out_of_stock"]
    lines += [
        "",
        f"- products in both hidden sets: {stats['hidden_overlap_products']} (must be 0)",
        "- strata (category of a query = most frequent category of its E products), hidden / candidates:",
    ]
    for name in ("hidden_test", "hidden_dev"):
        strata = stats[name]["per_stratum"]
        lines.append(
            f"  - {name.replace('_', '-')}: "
            + ", ".join(f"{category} {row['hidden']}/{row['candidates']}" for category, row in strata.items())
        )
    lines += [
        "",
        "## Out-of-stock set",
        "",
        f"- {oos['products']:,} products (wanted {oos['wanted']:,} = {settings['out_of_stock']['share']:.0%} of the "
        f"products in no hidden set), drawn among {oos['candidates']:,} E products of queries that are not hidden",
        "",
        "## Outputs (`data/processed/`, git-ignored)",
        "",
        "| file | rows | SHA-256 |",
        "|---|---:|---|",
    ]
    lines += [
        f"| `{name}` | {manifest['outputs'][name]['rows']:,} | `{manifest['outputs'][name]['sha256'][:16]}…` |"
        for name in OUTPUT_FILES
    ]
    return "\n".join(lines) + "\n"
