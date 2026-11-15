"""`uv run shop import catalog|verify`: the shop catalog into Odoo, and its check (Tasks 2.4a-b, ADR-019).

Input: `data/processed/products.parquet` and `vendors.parquet` from `uv run shop data build-slice` (Task
2.3b), checked against the SHA-256 recorded in `slice-manifest.json`. Everything goes through Odoo's public
JSON-2 API as the integration user (`ODOO_API_KEY` in `.env`), so Odoo's access rights and rules apply.

What it creates or updates (Odoo 19.0 fields, read in .odoo-src/odoo/addons):
- public categories `product.public.category` (one per shop category, top level) and internal categories
  `product.category` ("Shop catalog" and one child per category);
- one vendor `res.partner` per synthetic vendor, found again by `ref` = "synthetic-vendor-NN";
- one `product.template` per product, found again by `default_code` = ESCI product id: `type='consu'`
  and `is_storable=True` (stock/models/product.py), published, `brand` (module field), `description_sale`
  (plain text) and `description_ecommerce` (HTML) -- Odoo's own shop search reads both (website_sale
  `_get_website_sale_search_fields`) --, list price, cost (`standard_price`) = the synthetic vendor price
  (supervisor, 2026-11-15), **no customer tax** (supervisor, 2026-11-14: the shop shows the synthetic
  prices as they are), exactly one vendor price line `product.supplierinfo`, and stock availability shown
  in the shop with no order when out of stock (`show_availability=True`, `allow_out_of_stock_order=False`,
  website_sale_stock; supervisor, 2026-11-15: Odoo then marks sold-out products and refuses them in carts);
- stock on hand in the warehouse's stock location through a real **inventory adjustment** (Task 2.4b):
  `stock.quant.create` in `inventory_mode` with `inventory_quantity`, then `action_apply_inventory`, which
  creates and completes one stock move per product (stock/models/stock_quant.py, `create` and
  `_apply_inventory`). Only products whose quantity differs are adjusted: applying an unchanged quantity
  would still create an empty move.

Idempotent and resumable: every run first looks up what exists (by `ref`, name or `default_code`, archived
records included), creates only what is missing and writes only what differs. A second run creates, writes
and moves nothing; a run stopped in the middle resumes where it stopped.

Outputs: `data/processed/odoo_id_map.parquet` (ESCI product id, template id, variant id) for Locust and
evaluation; `results/summary/catalog-import.md`, the record of the last real run that changed something.
"""

from __future__ import annotations

import html
import json
import os
import platform
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shoptools import odoodb, snapshot
from shoptools.data import download, enrichment, shop_catalog, slice_builder
from shoptools.envfile import parse_env

ID_MAP_FILE = "odoo_id_map.parquet"
REPORT_FILE = Path("results") / "summary" / "catalog-import.md"
BATCH_SIZE = 200
CALL_TIMEOUT_SECONDS = (
    300  # creating 200 products or 200 stock moves in one call can take a while on a laptop
)
INTERNAL_ROOT = "Shop catalog"
VENDOR_REF = "synthetic-vendor-{:02d}"
READ_ALL = {"active_test": False}  # archived records count as existing: never create a duplicate
INVENTORY_MODE = {"inventory_mode": True}  # stock.quant._is_inventory_mode: quants are counted, then applied
VERIFY_SAMPLE = 10

TEMPLATE = "product.template"
SUPPLIERINFO = "product.supplierinfo"
PUBLIC_CATEGORY = "product.public.category"
CATEGORY = "product.category"
PARTNER = "res.partner"
QUANT = "stock.quant"
WAREHOUSE = "stock.warehouse"

Call = Callable[[str, str, dict[str, Any]], Any]  # (model, method, body) -> decoded JSON-2 result


class CatalogImportError(Exception):
    """The input files, the connection or Odoo refused something; the message says what to do."""


@dataclass
class Counts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    def add(self, other: Counts) -> None:
        self.created += other.created
        self.updated += other.updated
        self.unchanged += other.unchanged


@dataclass
class ImportResult:
    categories: Counts = field(default_factory=Counts)
    vendors: Counts = field(default_factory=Counts)
    products: Counts = field(default_factory=Counts)
    stock: Counts = field(default_factory=Counts)  # updated = adjusted, unchanged = already right
    batch_seconds: list[float] = field(default_factory=list)
    mapped: int = 0


# --- inputs -------------------------------------------------------------------------------------------------


def read_inputs(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(products sorted by ESCI id, vendors), after checking both files against the slice manifest."""
    import pyarrow.parquet as pq

    processed = repo_root / slice_builder.PROCESSED_DIR
    manifest_path = processed / slice_builder.MANIFEST_NAME
    if not manifest_path.is_file():
        raise CatalogImportError(f"{manifest_path} is missing: run `uv run shop data build-slice` first")
    outputs = json.loads(manifest_path.read_text(encoding="utf-8"))["outputs"]
    tables = []
    for name in (shop_catalog.PRODUCTS_FILE, shop_catalog.VENDORS_FILE):
        path = processed / name
        if name not in outputs or not path.is_file() or download.sha256_of(path) != outputs[name]["sha256"]:
            raise CatalogImportError(
                f"{path} is missing or not the one in the slice manifest: run `uv run shop data build-slice`"
            )
        tables.append(pq.read_table(path).to_pylist())
    products, vendors = tables
    return sorted(products, key=lambda row: row["product_id"]), vendors


# --- JSON-2 access ------------------------------------------------------------------------------------------


def json2_caller(repo_root: Path) -> Call:
    """A JSON-2 caller for the shop database, with the integration user's API key from `.env`."""
    env_path = repo_root / ".env"
    settings = odoodb.read_settings(env_path)
    api_key = parse_env(env_path.read_text(encoding="utf-8")).get(odoodb.API_KEY_ENV, "")
    if not api_key:
        raise CatalogImportError(
            f".env has no {odoodb.API_KEY_ENV}: create the database with `uv run shop db create`"
        )

    def call(model: str, method: str, body: dict[str, Any]) -> Any:
        return odoodb.json2_call(settings.db_name, api_key, model, method, body, timeout=CALL_TIMEOUT_SECONDS)

    return call


def _search_read(call: Call, model: str, domain: list[Any], fields: Sequence[str]) -> list[dict[str, Any]]:
    result = call(model, "search_read", {"domain": domain, "fields": list(fields), "context": READ_ALL})
    if not isinstance(result, list):
        raise CatalogImportError(f"unexpected answer from {model}.search_read: {result!r:.200}")
    return result


def _create(
    call: Call, model: str, vals_list: list[dict[str, Any]], context: dict[str, Any] | None = None
) -> list[int]:
    if not vals_list:
        return []
    body: dict[str, Any] = {"vals_list": vals_list}
    if context:
        body["context"] = context
    ids = call(model, "create", body)
    if not isinstance(ids, list) or len(ids) != len(vals_list):
        raise CatalogImportError(f"unexpected answer from {model}.create: {ids!r:.200}")
    return ids


def _write(call: Call, model: str, record_ids: int | list[int], vals: dict[str, Any]) -> None:
    ids = record_ids if isinstance(record_ids, list) else [record_ids]
    call(model, "write", {"ids": ids, "vals": vals})


def _many2one_id(value: Any) -> int | None:
    """search_read returns a many2one as [id, display name] or False."""
    return value[0] if isinstance(value, list) and value else None


# --- categories and vendors ---------------------------------------------------------------------------------


def ensure_categories(
    call: Call, names: Iterable[str], dry_run: bool
) -> tuple[dict[str, int], dict[str, int], Counts]:
    """(public category id by name, internal category id by name, counts). Top-level public categories."""
    names = sorted(set(names))
    counts = Counts()

    public = {
        row["name"]: row["id"]
        for row in _search_read(
            call, PUBLIC_CATEGORY, [["name", "in", names], ["parent_id", "=", False]], ["name"]
        )
    }
    missing = [name for name in names if name not in public]
    counts.unchanged += len(public)
    counts.created += len(missing)

    roots = _search_read(call, CATEGORY, [["name", "=", INTERNAL_ROOT], ["parent_id", "=", False]], ["name"])
    root_id = roots[0]["id"] if roots else None
    internal: dict[str, int] = {}
    if root_id is not None:
        internal = {
            row["name"]: row["id"]
            for row in _search_read(
                call, CATEGORY, [["name", "in", names], ["parent_id", "=", root_id]], ["name"]
            )
        }
    missing_internal = [name for name in names if name not in internal]
    counts.created += len(missing_internal) + (0 if root_id is not None else 1)
    counts.unchanged += len(internal) + (1 if root_id is not None else 0)
    if dry_run:
        return public, internal, counts

    new_public = _create(call, PUBLIC_CATEGORY, [{"name": name} for name in missing])
    public |= dict(zip(missing, new_public, strict=True))
    if root_id is None:
        root_id = _create(call, CATEGORY, [{"name": INTERNAL_ROOT}])[0]
    new_internal = _create(
        call, CATEGORY, [{"name": name, "parent_id": root_id} for name in missing_internal]
    )
    internal |= dict(zip(missing_internal, new_internal, strict=True))
    return public, internal, counts


def ensure_vendors(call: Call, vendors: list[dict[str, Any]], dry_run: bool) -> tuple[dict[int, int], Counts]:
    """(partner id by vendor number, counts): companies with a supplier rank, found again by `ref`."""
    counts = Counts()
    wanted = {
        row["vendor_id"]: {
            "name": row["name"],
            "ref": VENDOR_REF.format(row["vendor_id"]),
            "is_company": True,
            "supplier_rank": 1,
        }
        for row in vendors
    }
    refs = [vals["ref"] for vals in wanted.values()]
    existing = {
        row["ref"]: row for row in _search_read(call, PARTNER, [["ref", "in", refs]], ["ref", "name"])
    }
    partner_of: dict[int, int] = {}
    to_create = []
    for number, vals in sorted(wanted.items()):
        row = existing.get(vals["ref"])
        if row is None:
            to_create.append(number)
            continue
        partner_of[number] = row["id"]
        if row["name"] != vals["name"]:
            counts.updated += 1
            if not dry_run:
                _write(call, PARTNER, row["id"], {"name": vals["name"]})
        else:
            counts.unchanged += 1
    counts.created += len(to_create)
    if not dry_run:
        new_ids = _create(call, PARTNER, [wanted[number] for number in to_create])
        partner_of |= dict(zip(to_create, new_ids, strict=True))
    return partner_of, counts


# --- products -----------------------------------------------------------------------------------------------


PRODUCT_FIELDS = (
    "default_code",
    "name",
    "brand",
    "description_sale",
    "description_ecommerce",
    "list_price",
    "standard_price",
    "type",
    "is_storable",
    "is_published",
    "show_availability",
    "allow_out_of_stock_order",
    "categ_id",
    "public_categ_ids",
    "taxes_id",
)
SELLER_FIELDS = ("product_tmpl_id", "partner_id", "price", "min_qty", "delay")
X2MANY_FIELDS = frozenset({"public_categ_ids", "taxes_id"})
PRICE_FIELDS = frozenset({"list_price", "standard_price"})


def html_description(text: str) -> str:
    """Plain text -> escaped HTML paragraphs (the source text never becomes markup).

    Only &, < and > are escaped: Odoo's HTML sanitizer stores quotes as plain characters, so escaping them
    would make every re-run see a difference (measured on the first real import).
    """
    return "".join(f"<p>{html.escape(line, quote=False)}</p>" for line in text.splitlines() if line.strip())


def _html_text(value: Any) -> str:
    """HTML compared after decoding entities: the sanitizer may re-encode characters without changing them."""
    return " ".join(html.unescape(str(value or "")).split())


def product_values(row: dict[str, Any], public_id: int, internal_id: int) -> dict[str, Any]:
    """The template fields the importer owns, as Odoo stores them (prices from integer cents)."""
    return {
        "default_code": row["product_id"],
        "name": row["name"],
        "brand": row["brand"] or False,
        "description_sale": row["description"] or False,
        "description_ecommerce": html_description(row["description"]) or False,
        "list_price": row["list_price_cents"] / 100,
        "standard_price": row["vendor_price_cents"] / 100,
        "type": "consu",
        "is_storable": True,
        "is_published": True,
        "show_availability": True,
        "allow_out_of_stock_order": False,
        "categ_id": internal_id,
        "public_categ_ids": [public_id],
        "taxes_id": [],
    }


def seller_values(row: dict[str, Any], partner_id: int) -> dict[str, Any]:
    return {
        "partner_id": partner_id,
        "price": row["vendor_price_cents"] / 100,
        "min_qty": float(row["vendor_min_qty"]),
        "delay": row["vendor_lead_days"],
    }


def _stored(record: dict[str, Any], name: str) -> Any:
    """A search_read value in the shape `product_values` uses."""
    value = record.get(name)
    if name == "categ_id":
        return _many2one_id(value)
    if name in X2MANY_FIELDS:
        return sorted(value or [])
    return value


def _same(name: str, stored: Any, value: Any) -> bool:
    if name in X2MANY_FIELDS:
        return stored == sorted(value)
    if name in PRICE_FIELDS:
        return stored is not None and stored is not False and abs(float(stored) - value) < 0.005
    if name == "description_ecommerce":
        return _html_text(stored) == _html_text(value)
    return (stored or False) == (value or False)


def product_changes(wanted: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Fields to write so the record matches `wanted` (x2many fields as a SET command)."""
    return {
        name: [[6, 0, sorted(value)]] if name in X2MANY_FIELDS else value
        for name, value in wanted.items()
        if not _same(name, _stored(record, name), value)
    }


def _seller_matches(lines: list[dict[str, Any]], wanted: dict[str, Any]) -> bool:
    if len(lines) != 1:
        return False
    line = lines[0]
    return (
        _many2one_id(line["partner_id"]) == wanted["partner_id"]
        and abs(float(line["price"]) - wanted["price"]) < 0.005
        and float(line["min_qty"]) == wanted["min_qty"]
        and int(line["delay"]) == wanted["delay"]
    )


def _sellers_by_template(call: Call, template_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    sellers: dict[int, list[dict[str, Any]]] = {}
    if template_ids:
        for line in _search_read(
            call, SUPPLIERINFO, [["product_tmpl_id", "in", template_ids]], SELLER_FIELDS
        ):
            sellers.setdefault(_many2one_id(line["product_tmpl_id"]), []).append(line)
    return sellers


def import_batch(
    call: Call,
    rows: list[dict[str, Any]],
    public: dict[str, int],
    internal: dict[str, int],
    partner_of: dict[int, int],
    dry_run: bool,
) -> Counts:
    counts = Counts()
    codes = [row["product_id"] for row in rows]
    existing = {
        record["default_code"]: record
        for record in _search_read(call, TEMPLATE, [["default_code", "in", codes]], PRODUCT_FIELDS)
    }
    sellers = _sellers_by_template(call, [record["id"] for record in existing.values()])

    to_create = []
    # Identical changes (a new field set the same way on every product) go out as one write per batch.
    writes: dict[str, tuple[dict[str, Any], list[int]]] = {}
    for row in rows:
        wanted = product_values(row, public[row["category"]], internal[row["category"]])
        seller = seller_values(row, partner_of[row["vendor_id"]])
        record = existing.get(row["product_id"])
        if record is None:
            wanted["seller_ids"] = [[0, 0, seller]]
            wanted["public_categ_ids"] = [[6, 0, wanted["public_categ_ids"]]]
            wanted["taxes_id"] = [[6, 0, []]]
            to_create.append(wanted)
            continue
        changes = product_changes(wanted, record)
        if not _seller_matches(sellers.get(record["id"], []), seller):
            changes["seller_ids"] = [
                [5, 0, 0],
                [0, 0, seller],
            ]  # replace whatever lines exist by the one wanted
        if changes:
            counts.updated += 1
            key = json.dumps(changes, sort_keys=True)
            writes.setdefault(key, (changes, []))[1].append(record["id"])
        else:
            counts.unchanged += 1
    counts.created += len(to_create)
    if not dry_run:
        for changes, ids in writes.values():
            _write(call, TEMPLATE, ids, changes)
        _create(call, TEMPLATE, to_create)
    return counts


# --- stock --------------------------------------------------------------------------------------------------


def stock_location(call: Call) -> int:
    """The stock location of the shop's warehouse (one warehouse: `shop db create` makes none other)."""
    warehouses = sorted(_search_read(call, WAREHOUSE, [], ["lot_stock_id"]), key=lambda row: row["id"])
    location = _many2one_id(warehouses[0]["lot_stock_id"]) if warehouses else None
    if location is None:
        raise CatalogImportError(
            "no warehouse with a stock location in Odoo: is the Inventory app installed?"
        )
    return location


def sync_stock(call: Call, rows: list[dict[str, Any]], location_id: int, dry_run: bool) -> Counts:
    """Set on-hand quantities by one inventory adjustment, for the products whose quantity differs."""
    counts = Counts()
    wanted = {row["product_id"]: row["stock_qty"] for row in rows}
    templates = _search_read(
        call,
        TEMPLATE,
        [["default_code", "in", list(wanted)]],
        ["default_code", "product_variant_id", "qty_available"],
    )
    adjust = []
    for record in templates:
        target = wanted[record["default_code"]]
        if abs(float(record["qty_available"] or 0) - target) < 1e-6:
            counts.unchanged += 1
        else:
            adjust.append(
                {
                    "product_id": _many2one_id(record["product_variant_id"]),
                    "location_id": location_id,
                    "inventory_quantity": float(target),
                }
            )
    counts.updated += len(adjust)
    if dry_run or not adjust:
        return counts
    quant_ids = _create(call, QUANT, adjust, context=INVENTORY_MODE)
    result = call(QUANT, "action_apply_inventory", {"ids": quant_ids, "context": INVENTORY_MODE})
    if result:  # an action dict instead of None: Odoo asks a person to resolve a counting conflict
        raise CatalogImportError(
            "Odoo reported a stock counting conflict (some quantities moved since they were read); "
            "nothing was applied for this batch"
        )
    return counts


# --- id map -------------------------------------------------------------------------------------------------


def read_id_map(call: Call, codes: list[str], batch_size: int) -> list[dict[str, Any]]:
    rows = []
    for chunk in _chunks(codes, batch_size * 5):
        for record in _search_read(
            call, TEMPLATE, [["default_code", "in", chunk]], ["default_code", "product_variant_id"]
        ):
            rows.append(
                {
                    "product_id": record["default_code"],
                    "template_id": record["id"],
                    "variant_id": _many2one_id(record["product_variant_id"]),
                }
            )
    return sorted(rows, key=lambda row: row["product_id"])


def write_id_map(repo_root: Path, rows: list[dict[str, Any]]) -> Path:
    import pyarrow as pa

    schema = pa.schema([("product_id", pa.string()), ("template_id", pa.int64()), ("variant_id", pa.int64())])
    target = repo_root / slice_builder.PROCESSED_DIR / ID_MAP_FILE
    slice_builder.write_parquet(pa.Table.from_pylist(rows, schema=schema), target)
    return target


# --- import command -----------------------------------------------------------------------------------------


def _eta(seconds_per_row: float, remaining: int) -> str:
    seconds = round(seconds_per_row * remaining)
    return f"{seconds // 60} min {seconds % 60:02d} s"


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _count_existing(call: Call, codes: list[str], batch_size: int) -> int:
    return sum(
        len(_search_read(call, TEMPLATE, [["default_code", "in", chunk]], ["default_code"]))
        for chunk in _chunks(codes, batch_size * 5)
    )


def _import_products(
    call: Call,
    products: list[dict[str, Any]],
    lookups: tuple[dict[str, int], dict[str, int], dict[int, int], int | None],
    dry_run: bool,
    batch_size: int,
    result: ImportResult,
    write: Callable[[str], None],
) -> None:
    public, internal, partner_of, location_id = lookups
    batches = list(_chunks(products, batch_size))
    done = 0
    for number, batch in enumerate(batches, start=1):
        batch_started = time.monotonic()
        counts = import_batch(call, batch, public, internal, partner_of, dry_run)
        stock = sync_stock(call, batch, location_id, dry_run) if location_id is not None else Counts()
        result.batch_seconds.append(time.monotonic() - batch_started)
        result.products.add(counts)
        result.stock.add(stock)
        done += len(batch)
        rate = sum(result.batch_seconds) / done
        write(
            f"  batch {number}/{len(batches)}: {counts.created} created, {counts.updated} updated, "
            f"{counts.unchanged} unchanged, stock {stock.updated} adjusted "
            f"({result.batch_seconds[-1]:.1f} s); "
            f"{done:,}/{len(products):,}, about {_eta(rate, len(products) - done)} left\n"
        )


def run_import(
    repo_root: Path,
    limit: int | None = None,
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE,
    call: Call | None = None,
    write: Callable[[str], None] = sys.stdout.write,
) -> int:
    started = time.monotonic()
    result = ImportResult()
    try:
        products, vendors = read_inputs(repo_root)
        total = len(products)
        if limit is not None:
            products = products[:limit]
        call = call or json2_caller(repo_root)
        call("res.users", "context_get", {})  # fails fast if the stack, the database or the key is wrong
        mode = "Dry run (nothing is written)" if dry_run else "Import"
        write(
            f"{mode}: {len(products):,} of {total:,} products, {len(vendors)} vendors, "
            f"batches of {batch_size}\n"
        )
        public, internal, result.categories = ensure_categories(
            call, [row["category"] for row in products], dry_run
        )
        partner_of, result.vendors = ensure_vendors(call, vendors, dry_run)
        write(
            f"  categories: {result.categories.created} to create, {result.categories.unchanged} present; "
            f"vendors: {result.vendors.created} to create, {result.vendors.updated} to update, "
            f"{result.vendors.unchanged} present\n"
        )
        if dry_run and (result.categories.created or result.vendors.created):
            # Without their ids the product fields cannot be compared; count products only by presence.
            existing = _count_existing(call, [row["product_id"] for row in products], batch_size)
            result.products = Counts(created=len(products) - existing, unchanged=existing)
        else:
            lookups = (public, internal, partner_of, stock_location(call))
            _import_products(call, products, lookups, dry_run, batch_size, result, write)
        if not dry_run:
            id_rows = read_id_map(call, [row["product_id"] for row in products], batch_size)
            result.mapped = len(id_rows)
            if result.mapped != len(products):
                raise CatalogImportError(
                    f"{result.mapped:,} of {len(products):,} products found in Odoo after the import"
                )
            write_id_map(repo_root, id_rows)
    except (CatalogImportError, odoodb.SetupError, OSError) as error:
        print(f"\nshop import catalog: {error}", file=sys.stderr)
        print("Nothing is lost: run the same command again, it continues where it stopped.", file=sys.stderr)
        return 1
    seconds = time.monotonic() - started
    _summary(result, len(products), total, dry_run, seconds, write)
    changed = (
        result.categories.created
        + result.vendors.created
        + result.vendors.updated
        + result.products.created
        + result.products.updated
        + result.stock.updated
    )
    if not dry_run and changed:  # a run that changes nothing keeps the record of the last one that did
        _write_report(repo_root, result, len(products), total, limit, batch_size, seconds)
        write(f"Record of this run: {REPORT_FILE.as_posix()}\n")
    return 0


def _summary(
    result: ImportResult, count: int, total: int, dry_run: bool, seconds: float, write: Callable[[str], None]
) -> None:
    products, stock = result.products, result.stock
    verb = "would be" if dry_run else "were"
    write(
        f"Products: {products.created:,} {verb} created, {products.updated:,} updated, "
        f"{products.unchanged:,} unchanged in {seconds:.0f} s; stock: {stock.updated:,} {verb} adjusted, "
        f"{stock.unchanged:,} already right.\n"
    )
    if result.batch_seconds and count:
        per_product = sum(result.batch_seconds) / count
        write(
            f"  {per_product * 1000:.0f} ms per product; the full catalog ({total:,}) would take about "
            f"{_eta(per_product, total)} at this rate\n"
        )
    if not dry_run:
        id_map = (slice_builder.PROCESSED_DIR / ID_MAP_FILE).as_posix()
        write(f"Id map: {result.mapped:,} products in {id_map}\n")


def _nearest_rank(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(share * len(ordered)) - 1))] if ordered else 0.0


def _write_report(
    repo_root: Path,
    result: ImportResult,
    count: int,
    total: int,
    limit: int | None,
    batch_size: int,
    seconds: float,
) -> None:
    batches = result.batch_seconds
    per_product = sum(batches) / count * 1000 if count else 0.0
    command = "uv run shop import catalog" + (f" --limit {limit}" if limit else "")
    command += f" --batch-size {batch_size}" if batch_size != BATCH_SIZE else ""
    lines = [
        "# Catalog import: record of a real run",
        "",
        "Written by `uv run shop import catalog` (Tasks 2.4a-b, ADR-019) after a run that changed something.",
        "Timings depend on the machine and on what Odoo had to do: a first import creates products and",
        "stock moves, a re-run only compares. The data is SYNTHETIC except the ESCI texts (docs/ai/04 §4).",
        "",
        f"- date (UTC): {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- command: `{command}`; git `{snapshot.git_sha(repo_root)}`",
        f"- machine: {platform.system()} {platform.machine()}, {os.cpu_count()} logical CPUs; Python "
        f"{platform.python_version()}",
        f"- products: {count:,} of {total:,} in `products.parquet`",
        "",
        "| what | created | updated | unchanged |",
        "|---|---:|---:|---:|",
        f"| categories (public + internal) | {result.categories.created} | {result.categories.updated} | "
        f"{result.categories.unchanged} |",
        f"| vendors | {result.vendors.created} | {result.vendors.updated} | {result.vendors.unchanged} |",
        f"| products | {result.products.created:,} | {result.products.updated:,} | "
        f"{result.products.unchanged:,} |",
        f"| stock (inventory adjustment) | — | {result.stock.updated:,} adjusted | "
        f"{result.stock.unchanged:,} |",
        "",
        f"- total {seconds:.0f} s; {len(batches)} batches of up to {batch_size}; "
        f"{per_product:.1f} ms per product",
        f"- batch time: median {_nearest_rank(batches, 0.5):.1f} s, "
        f"p95 {_nearest_rank(batches, 0.95):.1f} s, "
        f"max {max(batches, default=0.0):.1f} s",
        f"- id map: {result.mapped:,} products in `data/processed/{ID_MAP_FILE}`",
    ]
    target = repo_root / REPORT_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, target)


# --- verify command -----------------------------------------------------------------------------------------


def check_product(
    row: dict[str, Any],
    record: dict[str, Any] | None,
    sellers: list[dict[str, Any]],
    names: dict[str, dict[int, str]],
) -> list[str]:
    """The fields of one imported product that do not match its source row (empty list = all match)."""
    if record is None:
        return ["missing"]
    public = {name: category_id for category_id, name in names["public"].items()}
    internal = {name: category_id for category_id, name in names["internal"].items()}
    wanted = product_values(row, public.get(row["category"], -1), internal.get(row["category"], -1))
    problems = sorted(product_changes(wanted, record))
    partner = {name: partner_id for partner_id, name in names["vendor"].items()}
    vendor_name = enrichment.vendor_name(row["vendor_id"])
    if not _seller_matches(sellers, seller_values(row, partner.get(vendor_name, -1))):
        problems.append("vendor line")
    if abs(float(record.get("qty_available") or 0) - row["stock_qty"]) > 1e-6:
        problems.append("stock")
    return problems


def run_verify(
    repo_root: Path,
    sample: int = VERIFY_SAMPLE,
    seed: int | None = None,
    call: Call | None = None,
    write: Callable[[str], None] = sys.stdout.write,
) -> int:
    """Compare `sample` products, drawn with a seed, with their source rows; exit 1 on any mismatch."""
    try:
        products, _ = read_inputs(repo_root)
        if seed is None:
            seed = slice_builder.load_config(repo_root / slice_builder.CONFIG_FILE).seed
        chosen = slice_builder.derived_rng(seed, "import-check").sample(products, min(sample, len(products)))
        call = call or json2_caller(repo_root)
        codes = [row["product_id"] for row in chosen]
        records = {
            record["default_code"]: record
            for record in _search_read(
                call, TEMPLATE, [["default_code", "in", codes]], [*PRODUCT_FIELDS, "qty_available"]
            )
        }
        sellers = _sellers_by_template(call, [record["id"] for record in records.values()])
        names = {
            "public": {row["id"]: row["name"] for row in _search_read(call, PUBLIC_CATEGORY, [], ["name"])},
            "internal": {
                row["id"]: row["name"]
                for row in _search_read(call, CATEGORY, [["parent_id.name", "=", INTERNAL_ROOT]], ["name"])
            },
            "vendor": {
                row["id"]: row["name"]
                for row in _search_read(call, PARTNER, [["ref", "like", "synthetic-vendor-"]], ["name"])
            },
        }
    except (CatalogImportError, odoodb.SetupError, slice_builder.SliceError, OSError) as error:
        print(f"shop import verify: {error}", file=sys.stderr)
        return 1
    failures = 0
    write(f"Checking {len(chosen)} products (seed {seed}, stream import-check) against their source rows:\n")
    for row in sorted(chosen, key=lambda item: item["product_id"]):
        record = records.get(row["product_id"])
        problems = check_product(row, record, sellers.get(record["id"], []) if record else [], names)
        failures += bool(problems)
        status = "OK  " if not problems else "FAIL"
        detail = "" if not problems else f" — differs: {', '.join(problems)}"
        write(
            f"  {status} {row['product_id']}  ${row['list_price_cents'] / 100:,.2f}  "
            f"stock {row['stock_qty']:>3}  "
            f"{row['category'][:24]}{detail}\n"
        )
    write(f"{len(chosen) - failures} of {len(chosen)} match.\n")
    return 1 if failures else 0
