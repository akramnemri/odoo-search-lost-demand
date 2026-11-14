"""`uv run shop import catalog [--limit N] [--dry-run]`: the shop catalog into Odoo (Task 2.4a, ADR-019).

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
  `_get_website_sale_search_fields`) --, list price, **no customer tax** (supervisor, 2026-11-14: the
  shop shows the synthetic prices as they are), and exactly one vendor price line `product.supplierinfo`
  (vendor, price, minimum quantity, lead time).

Idempotent and resumable: every run first looks up what exists (by `ref`, name or `default_code`, archived
records included), creates only what is missing and writes only fields that differ. A second run creates
and writes nothing; a run stopped in the middle resumes where it stopped. Stock is Task 2.4b.

Output: `data/processed/odoo_id_map.parquet` (ESCI product id, template id, variant id), for Locust and
evaluation.
"""

from __future__ import annotations

import html
import json
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shoptools import odoodb
from shoptools.data import download, shop_catalog, slice_builder
from shoptools.envfile import parse_env

ID_MAP_FILE = "odoo_id_map.parquet"
BATCH_SIZE = 200
CALL_TIMEOUT_SECONDS = 300  # creating 200 products in one call can take a while on a laptop
INTERNAL_ROOT = "Shop catalog"
VENDOR_REF = "synthetic-vendor-{:02d}"
READ_ALL = {"active_test": False}  # archived records count as existing: never create a duplicate

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


def _create(call: Call, model: str, vals_list: list[dict[str, Any]]) -> list[int]:
    if not vals_list:
        return []
    ids = call(model, "create", {"vals_list": vals_list})
    if not isinstance(ids, list) or len(ids) != len(vals_list):
        raise CatalogImportError(f"unexpected answer from {model}.create: {ids!r:.200}")
    return ids


def _write(call: Call, model: str, record_id: int, vals: dict[str, Any]) -> None:
    call(model, "write", {"ids": [record_id], "vals": vals})


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
            call, "product.public.category", [["name", "in", names], ["parent_id", "=", False]], ["name"]
        )
    }
    missing = [name for name in names if name not in public]
    counts.unchanged += len(public)
    counts.created += len(missing)

    roots = _search_read(
        call, "product.category", [["name", "=", INTERNAL_ROOT], ["parent_id", "=", False]], ["name"]
    )
    root_id = roots[0]["id"] if roots else None
    internal: dict[str, int] = {}
    if root_id is not None:
        internal = {
            row["name"]: row["id"]
            for row in _search_read(
                call, "product.category", [["name", "in", names], ["parent_id", "=", root_id]], ["name"]
            )
        }
    missing_internal = [name for name in names if name not in internal]
    counts.created += len(missing_internal) + (0 if root_id is not None else 1)
    counts.unchanged += len(internal) + (1 if root_id is not None else 0)
    if dry_run:
        return public, internal, counts

    public |= dict(
        zip(
            missing,
            _create(call, "product.public.category", [{"name": name} for name in missing]),
            strict=True,
        )
    )
    if root_id is None:
        root_id = _create(call, "product.category", [{"name": INTERNAL_ROOT}])[0]
    internal |= dict(
        zip(
            missing_internal,
            _create(
                call, "product.category", [{"name": name, "parent_id": root_id} for name in missing_internal]
            ),
            strict=True,
        )
    )
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
    existing = {
        row["ref"]: row
        for row in _search_read(
            call, "res.partner", [["ref", "in", [vals["ref"] for vals in wanted.values()]]], ["ref", "name"]
        )
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
                _write(call, "res.partner", row["id"], {"name": vals["name"]})
        else:
            counts.unchanged += 1
    counts.created += len(to_create)
    if not dry_run:
        partner_of |= dict(
            zip(
                to_create, _create(call, "res.partner", [wanted[number] for number in to_create]), strict=True
            )
        )
    return partner_of, counts


# --- products -----------------------------------------------------------------------------------------------


PRODUCT_FIELDS = (
    "default_code",
    "name",
    "brand",
    "description_sale",
    "description_ecommerce",
    "list_price",
    "type",
    "is_storable",
    "is_published",
    "categ_id",
    "public_categ_ids",
    "taxes_id",
)
SELLER_FIELDS = ("product_tmpl_id", "partner_id", "price", "min_qty", "delay")


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
        "type": "consu",
        "is_storable": True,
        "is_published": True,
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
    if name in {"public_categ_ids", "taxes_id"}:
        return sorted(value or [])
    return value


def product_changes(wanted: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Fields to write so the record matches `wanted` (x2many fields as a SET command)."""
    changes: dict[str, Any] = {}
    for name, value in wanted.items():
        stored = _stored(record, name)
        if name in {"public_categ_ids", "taxes_id"}:
            if stored != sorted(value):
                changes[name] = [[6, 0, sorted(value)]]
        elif name == "list_price":
            if stored is None or abs(float(stored) - value) > 0.004:
                changes[name] = value
        elif name == "description_ecommerce":
            if _html_text(stored) != _html_text(value):
                changes[name] = value
        elif (stored or False) != (value or False):
            changes[name] = value
    return changes


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
        for record in _search_read(call, "product.template", [["default_code", "in", codes]], PRODUCT_FIELDS)
    }
    sellers: dict[int, list[dict[str, Any]]] = {}
    if existing:
        for line in _search_read(
            call,
            "product.supplierinfo",
            [["product_tmpl_id", "in", [record["id"] for record in existing.values()]]],
            SELLER_FIELDS,
        ):
            sellers.setdefault(_many2one_id(line["product_tmpl_id"]), []).append(line)

    to_create = []
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
            if not dry_run:
                _write(call, "product.template", record["id"], changes)
        else:
            counts.unchanged += 1
    counts.created += len(to_create)
    if not dry_run:
        _create(call, "product.template", to_create)
    return counts


def read_id_map(call: Call, codes: list[str], batch_size: int) -> list[dict[str, Any]]:
    rows = []
    for start in range(0, len(codes), batch_size * 5):
        chunk = codes[start : start + batch_size * 5]
        for record in _search_read(
            call, "product.template", [["default_code", "in", chunk]], ["default_code", "product_variant_id"]
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


# --- command ------------------------------------------------------------------------------------------------


def _eta(seconds_per_row: float, remaining: int) -> str:
    seconds = round(seconds_per_row * remaining)
    return f"{seconds // 60} min {seconds % 60:02d} s"


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
            existing = sum(
                len(_search_read(call, "product.template", [["default_code", "in", chunk]], ["default_code"]))
                for chunk in _chunks([row["product_id"] for row in products], batch_size * 5)
            )
            result.products = Counts(created=len(products) - existing, unchanged=existing)
        else:
            batches = list(_chunks(products, batch_size))
            done = 0
            for number, batch in enumerate(batches, start=1):
                batch_started = time.monotonic()
                counts = import_batch(call, batch, public, internal, partner_of, dry_run)
                result.batch_seconds.append(time.monotonic() - batch_started)
                result.products.add(counts)
                done += len(batch)
                rate = sum(result.batch_seconds) / done
                write(
                    f"  batch {number}/{len(batches)}: {counts.created} created, {counts.updated} updated, "
                    f"{counts.unchanged} unchanged ({result.batch_seconds[-1]:.1f} s); "
                    f"{done:,}/{len(products):,}, about {_eta(rate, len(products) - done)} left\n"
                )
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
    _summary(result, len(products), total, dry_run, time.monotonic() - started, write)
    return 0


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _summary(
    result: ImportResult, count: int, total: int, dry_run: bool, seconds: float, write: Callable[[str], None]
) -> None:
    products = result.products
    verb = "would be" if dry_run else "were"
    write(
        f"Products: {products.created:,} {verb} created, {products.updated:,} updated, "
        f"{products.unchanged:,} unchanged in {seconds:.0f} s.\n"
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
