"""`uv run shop probe products [--count 30]`: how long a product change takes to become searchable (FR1).

Protocol (docs/ai/04_DATA_SEARCH_EVALUATION.md §11.4, Task 3.2): `--count` changes, one at a time, alternating
a price change (`product.template.write` of `list_price`, +1.00) and a stock change (an inventory adjustment
of -1 unit, as the importer makes them: `stock.quant` in inventory mode, then `action_apply_inventory`), all
through Odoo's JSON-2 API as the integration user. After each change the probe searches the product index
(`GET shop-products/_search`, as `shop_tools`) every 200 ms until the product's document shows the new value.

Delay = from just before the API call is sent to the first search that shows the change, on the host clock:
it includes the API call, the commit, the cron trigger, the bulk request and Elasticsearch's 1 s refresh.
A change not visible after `--timeout` seconds is counted as a timeout, never dropped. Each change is undone
right after it is measured (and the undo awaited, unmeasured), so the catalog ends as it started -- except for
the inventory moves the stock changes leave in Odoo's history (campaigns restore `baseline-catalog` anyway).

Until Task 3.3 the shop page itself does not search Elasticsearch, so this measures change → searchable in
the index. Products are drawn with the seeded stream "probe-products" among published, sellable products
with stock on hand.

Outputs: `results/probe-products-<UTC time>/run.json` and `observations.json` (git-ignored), and the table
`results/summary/freshness-products.md`.
"""

from __future__ import annotations

import json
import math
import os
import platform
import sys
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shoptools import catalog_import, odoodb, snapshot, stack
from shoptools.data.slice_builder import derived_rng
from shoptools.doctor.system import HttpResponse, RealSystem
from shoptools.envfile import parse_env

ALIAS = "shop-products"
SEED = 20261025  # the project seed (protocol v1)
STREAM = "probe-products"
POLL_SECONDS = 0.2
SUMMARY_FILE = Path("results") / "summary" / "freshness-products.md"
TARGET_SECONDS = 60.0  # FR1
TEMPLATE = "product.template"

Call = catalog_import.Call
Get = Callable[[str], HttpResponse | None]


class ProbeError(Exception):
    pass


@dataclass
class Observation:
    template_id: int
    kind: str  # "price" or "stock"
    before: float
    after: float
    api_seconds: float  # the JSON-2 call alone
    delay_seconds: float | None  # None: not visible within the timeout


def nearest_rank(values: list[float], share: float) -> float:
    """Nearest-rank percentile: the smallest value with at least `share` of the values at or below it."""
    ordered = sorted(values)
    if not ordered:
        return math.nan
    return ordered[max(1, math.ceil(share * len(ordered))) - 1]


def es_getter(repo_root: Path) -> Get:
    password = parse_env((repo_root / ".env").read_text(encoding="utf-8")).get("SHOP_TOOLS_ES_PASSWORD", "")
    if not password:
        raise ProbeError(".env has no SHOP_TOOLS_ES_PASSWORD: run `uv run shop env init`")
    system = RealSystem()

    def get(path: str) -> HttpResponse | None:
        return system.http_get(
            f"{stack.ELASTICSEARCH_URL}/{path}", auth=("shop_tools", password), timeout=5.0
        )

    return get


def indexed_values(get: Get, template_id: int) -> dict[str, Any] | None:
    """The searchable document of a product (price, free_qty), or None when the search does not find it."""
    query = urllib.parse.urlencode(
        {"q": f"template_id:{template_id}", "_source_includes": "price,free_qty", "size": 1}
    )
    response = get(f"{ALIAS}/_search?{query}")
    if response is None or response.status != 200:
        return None
    hits = response.json().get("hits", {}).get("hits", [])
    return hits[0]["_source"] if hits else None


def pick_products(call: Call, count: int, seed: int) -> list[dict[str, Any]]:
    domain = [
        ["sale_ok", "=", True],
        ["is_published", "=", True],
        ["is_storable", "=", True],
        ["qty_available", ">=", 2],
    ]
    ids = sorted(call(TEMPLATE, "search", {"domain": domain}))
    if len(ids) < count:
        raise ProbeError(f"only {len(ids)} published products with stock: need {count}")
    chosen = derived_rng(seed, STREAM).sample(ids, count)
    fields = ["list_price", "qty_available", "product_variant_id"]
    rows = call(TEMPLATE, "read", {"ids": chosen, "fields": fields})
    by_id = {row["id"]: row for row in rows}
    return [by_id[template_id] for template_id in chosen]


def set_price(call: Call, template_id: int, price: float) -> None:
    call(TEMPLATE, "write", {"ids": [template_id], "vals": {"list_price": price}})


def set_stock(call: Call, variant_id: int, location_id: int, quantity: float) -> None:
    quant = {"product_id": variant_id, "location_id": location_id, "inventory_quantity": quantity}
    quant_ids = catalog_import._create(
        call, catalog_import.QUANT, [quant], context=catalog_import.INVENTORY_MODE
    )  # noqa: SLF001
    result = call(
        catalog_import.QUANT,
        "action_apply_inventory",
        {"ids": quant_ids, "context": catalog_import.INVENTORY_MODE},
    )
    if result:
        raise ProbeError(f"Odoo asked to resolve a stock counting conflict for variant {variant_id}")


def wait_until(
    get: Get,
    template_id: int,
    field: str,
    value: float,
    timeout: float,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> float | None:
    """Clock time when the document first shows `field == value`; None after `timeout` seconds."""
    deadline = clock() + timeout
    while True:
        document = indexed_values(get, template_id)
        now = clock()
        if document is not None and abs(float(document.get(field, math.nan)) - value) < 0.005:
            return now
        if now >= deadline:
            return None
        sleep(POLL_SECONDS)


def probe_one(
    call: Call,
    get: Get,
    product: dict[str, Any],
    kind: str,
    location_id: int,
    timeout: float,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> Observation:
    template_id = int(product["id"])
    document = indexed_values(get, template_id)
    if document is None:
        raise ProbeError(f"product {template_id} is not in {ALIAS}: rebuild the index first")
    variant_id = catalog_import._many2one_id(product["product_variant_id"])  # noqa: SLF001
    if kind == "price":
        before = round(float(product["list_price"]), 2)
        after = round(before + 1.0, 2)
        field, expected, restore = "price", after, before

        def change() -> None:
            set_price(call, template_id, after)

        def undo() -> None:
            set_price(call, template_id, before)
    else:
        before = float(product["qty_available"])
        after = before - 1.0
        field = "free_qty"
        restore = float(document["free_qty"])
        expected = restore - 1.0

        def change() -> None:
            set_stock(call, variant_id, location_id, after)

        def undo() -> None:
            set_stock(call, variant_id, location_id, before)

    started = clock()
    change()
    api_seconds = clock() - started
    seen = wait_until(get, template_id, field, expected, timeout, clock, sleep)
    undo()
    wait_until(get, template_id, field, restore, timeout, clock, sleep)  # the next change starts clean
    delay = None if seen is None else seen - started
    return Observation(
        template_id, kind, before, after, round(api_seconds, 3), None if delay is None else round(delay, 3)
    )


def summarize(observations: list[Observation]) -> dict[str, Any]:
    delays = [o.delay_seconds for o in observations if o.delay_seconds is not None]
    stats: dict[str, Any] = {"changes": len(observations), "visible": len(delays)}
    stats["timeouts"] = len(observations) - len(delays)
    for name, share in (("p50", 0.5), ("p95", 0.95)):
        stats[name] = round(nearest_rank(delays, share), 2) if delays else None
    stats["max"] = round(max(delays), 2) if delays else None
    stats["within_target"] = sum(1 for d in delays if d <= TARGET_SECONDS)
    for kind in ("price", "stock"):
        values = [o.delay_seconds for o in observations if o.kind == kind and o.delay_seconds is not None]
        stats[f"{kind}_p50"] = round(nearest_rank(values, 0.5), 2) if values else None
    return stats


def render_summary(meta: dict[str, Any], stats: dict[str, Any]) -> str:
    def cell(value: Any) -> str:
        return "–" if value is None else f"{value:.2f} s"

    git = meta["git"]
    short = git[:7] + ("-dirty" if git.endswith("-dirty") else "")
    return (
        "# Freshness of product changes (FR1)\n\n"
        "Generated by `uv run shop probe products` from run folder "
        f"`results/{meta['run_id']}/` (git {short}). Never edited by hand.\n\n"
        "What is measured: from just before a change is sent to Odoo's JSON-2 API until a search on the "
        "product index (alias `shop-products`) returns the new value; polled every 0.2 s. Until Task 3.3 the "
        "shop page does not search Elasticsearch, so this is change → searchable in the index. "
        "Target (FR1): < 60 s.\n\n"
        "| Changes | Visible | Timeouts | p50 | p95 | max | Within 60 s | p50 price | p50 stock |\n"
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        f"| {stats['changes']} | {stats['visible']} | {stats['timeouts']} | {cell(stats['p50'])} | "
        f"{cell(stats['p95'])} | {cell(stats['max'])} | {stats['within_target']} | "
        f"{cell(stats['price_p50'])} | {cell(stats['stock_p50'])} |\n\n"
        f"Run: {meta['start']}, seed {meta['seed']} (stream `{STREAM}`), timeout {meta['timeout']:.0f} s per "
        f"change, database `{meta['database']}`, index `{meta['index']}`, {meta['machine']}. Percentiles: "
        "nearest rank. Prices and stock are synthetic (labelled synthetic catalog, Task 2.3b); each change "
        "was undone after it was measured.\n"
    )


def _write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, target)


def alias_index(get: Get) -> str:
    response = get(f"_alias/{ALIAS}")
    if response is None or response.status != 200:
        raise ProbeError(
            f"no index behind {ALIAS}: is the stack up and the index built (`uv run shop index rebuild`)?"
        )
    return ", ".join(sorted(response.json()))


def run_probe(
    repo_root: Path,
    count: int,
    timeout: float,
    seed: int = SEED,
    write: Callable[[str], object] = sys.stdout.write,
) -> int:
    started_at = datetime.now(UTC)
    try:
        settings = odoodb.read_settings(repo_root / ".env")
        call = catalog_import.json2_caller(repo_root)
        get = es_getter(repo_root)
        index = alias_index(get)
        location_id = catalog_import.stock_location(call)
        products = pick_products(call, count, seed)
        write(f"Probing {count} product changes (index {index}); each is undone after it is measured.\n")
        observations = []
        for number, product in enumerate(products, start=1):
            kind = "price" if number % 2 else "stock"
            observation = probe_one(call, get, product, kind, location_id, timeout)
            observations.append(observation)
            shown = "timeout" if observation.delay_seconds is None else f"{observation.delay_seconds:.2f} s"
            write(f"  {number:>3} {kind:<5} product {observation.template_id:<6} {shown}\n")
    except (ProbeError, odoodb.SetupError, catalog_import.CatalogImportError) as error:
        write(f"shop probe products: {error}\n")
        return 1
    stats = summarize(observations)
    run_id = f"probe-products-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    meta = {
        "kind": "probe-products",
        "run_id": run_id,
        "command": f"uv run shop probe products --count {count} --timeout {timeout:g} --seed {seed}",
        "git": snapshot.git_sha(repo_root),
        "seed": seed,
        "stream": STREAM,
        "timeout": timeout,
        "poll_seconds": POLL_SECONDS,
        "database": settings.db_name,
        "index": index,
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "start": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stats": stats,
    }
    folder = repo_root / "results" / run_id
    _write_text(folder / "observations.json", json.dumps([asdict(o) for o in observations], indent=2) + "\n")
    _write_text(folder / "run.json", json.dumps(meta, indent=2) + "\n")
    _write_text(repo_root / SUMMARY_FILE, render_summary(meta, stats))
    write(
        f"p50 {stats['p50']} s, p95 {stats['p95']} s, max {stats['max']} s; {stats['timeouts']} timeouts. "
        f"Table: {SUMMARY_FILE.as_posix()}; run folder: results/{run_id}/\n"
    )
    return 0 if stats["timeouts"] == 0 else 1
