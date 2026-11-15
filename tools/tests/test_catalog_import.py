from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from shoptools import catalog_import as ci
from shoptools import odoodb
from shoptools.data import shop_catalog, slice_builder

MANY2ONE = {"categ_id", "partner_id", "product_tmpl_id", "parent_id", "product_variant_id", "lot_stock_id"}
STOCK_LOCATION = 5


class FakeOdoo:
    """The JSON-2 calls the importer makes, on in-memory records (enough of Odoo's behaviour to test it).

    and location, reused if it exists), then `action_apply_inventory` sets the quantity, one move per
    quant.
    quant.
    """

    def __init__(self, fail_on_product_create: int | None = None) -> None:
        self.records: dict[str, dict[int, dict[str, Any]]] = {}
        self.next_id = 1
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.product_creates = 0
        self.fail_on_product_create = fail_on_product_create
        self.moves = 0  # stock moves applied
        self.stock_conflict = False  # action_apply_inventory answers with a conflict wizard
        self.table("stock.warehouse")[999] = {"id": 999, "lot_stock_id": STOCK_LOCATION}

    def __call__(self, model: str, method: str, body: dict[str, Any]) -> Any:
        self.calls.append((model, method, copy.deepcopy(body)))
        if method == "context_get":
            return {"lang": "en_US"}
        if method == "search_read":
            return self.search_read(model, body["domain"], body["fields"])
        if method == "create" and model == "stock.quant":
            assert body.get("context", {}).get("inventory_mode") is True, (
                "quants are counted in inventory mode"
            )
            return [self.count_quant(vals) for vals in body["vals_list"]]
        if method == "create":
            if model == "product.template":
                self.product_creates += 1
                if self.product_creates == self.fail_on_product_create:
                    raise odoodb.SetupError("JSON-2 call product.template.create refused: HTTP 500 boom")
            return [self.create(model, vals) for vals in body["vals_list"]]
        if method == "write":
            for record_id in body["ids"]:
                self.write(model, record_id, body["vals"])
            return True
        if method == "action_apply_inventory":
            return self.apply_inventory(body["ids"])
        raise AssertionError(f"unexpected call {model}.{method}")

    # -- storage --

    def table(self, model: str) -> dict[int, dict[str, Any]]:
        return self.records.setdefault(model, {})

    def create(self, model: str, vals: dict[str, Any]) -> int:
        record_id = self.next_id
        self.next_id += 1
        self.table(model)[record_id] = {"id": record_id}
        if model == "product.template":
            self.table(model)[record_id]["product_variant_id"] = record_id + 100_000
        self.write(model, record_id, vals)
        return record_id

    def write(self, model: str, record_id: int, vals: dict[str, Any]) -> None:
        record = self.table(model)[record_id]
        for name, value in vals.items():
            if name == "seller_ids":
                for command in value:
                    if command[0] == 5:
                        lines = self.table("product.supplierinfo")
                        for line_id in [
                            i for i, line in lines.items() if line["product_tmpl_id"] == record_id
                        ]:
                            del lines[line_id]
                    elif command[0] == 0:
                        self.create("product.supplierinfo", {**command[2], "product_tmpl_id": record_id})
            elif name in {"public_categ_ids", "taxes_id"}:
                assert value[0][0] == 6, value
                record[name] = list(value[0][2])
            else:
                record[name] = value

    def count_quant(self, vals: dict[str, Any]) -> int:
        quants = self.table("stock.quant")
        for quant in quants.values():
            if (quant["product_id"], quant["location_id"]) == (vals["product_id"], vals["location_id"]):
                quant["inventory_quantity"] = vals["inventory_quantity"]
                return quant["id"]
        return self.create("stock.quant", {**vals, "quantity": 0.0})

    def apply_inventory(self, ids: list[int]) -> Any:
        if self.stock_conflict:
            return {"type": "ir.actions.act_window", "res_model": "stock.inventory.conflict"}
        for quant_id in ids:
            quant = self.table("stock.quant")[quant_id]
            quant["quantity"] = quant["inventory_quantity"]
            self.moves += 1
        return None

    def qty_available(self, template: dict[str, Any]) -> float:
        variant = template["product_variant_id"]
        return sum(q["quantity"] for q in self.table("stock.quant").values() if q["product_id"] == variant)

    def search_read(self, model: str, domain: list[list[Any]], fields: list[str]) -> list[dict[str, Any]]:
        def value_of(record: dict[str, Any], name: str) -> Any:
            if name == "parent_id.name":  # the one dotted path the importer uses
                parent = self.table(model).get(record.get("parent_id") or 0)
                return parent["name"] if parent else False
            return record.get(name, False)

        def matches(record: dict[str, Any]) -> bool:
            for name, operator, value in domain:
                stored = value_of(record, name)
                if operator == "=" and stored != value:
                    return False
                if operator == "in" and stored not in value:
                    return False
                if operator == "like" and value not in (stored or ""):
                    return False
            return True

        rows = []
        for record in self.table(model).values():
            if matches(record):
                row = {"id": record["id"]}
                for name in fields:
                    value = self.qty_available(record) if name == "qty_available" else record.get(name, False)
                    row[name] = [value, f"name {value}"] if name in MANY2ONE and value else value
                rows.append(row)
        return rows

    # -- inspection --

    def count(self, method: str, model: str | None = None) -> int:
        return sum(1 for m, meth, _ in self.calls if meth == method and (model is None or m == model))

    def products(self) -> dict[str, dict[str, Any]]:
        return {record["default_code"]: record for record in self.table("product.template").values()}

    def stock(self) -> dict[str, float]:
        return {code: self.qty_available(record) for code, record in self.products().items()}


def product_row(n: int, category: str = "Shoes", vendor: int = 1) -> dict[str, Any]:
    return {
        "product_id": f"B{n:04d}",
        "name": f"Product {n}",
        "description": f"Line one of {n}\nLine <two> & more",
        "brand": "Acme" if n % 2 else "",
        "color": None,
        "category": category,
        "list_price_cents": 2_000 + n * 100 + 99,
        "stock_qty": 0 if n % 4 == 0 else 3 + n,  # every fourth product starts out of stock
        "vendor_id": vendor,
        "vendor_price_cents": 1_300 + n * 60,
        "vendor_min_qty": 1 + n % 5,
        "vendor_lead_days": 2 + n % 7,
    }


PRODUCT_SCHEMA = pa.schema(
    [
        ("product_id", pa.string()),
        ("name", pa.string()),
        ("description", pa.string()),
        ("brand", pa.string()),
        ("color", pa.string()),
        ("category", pa.string()),
        ("list_price_cents", pa.int64()),
        ("stock_qty", pa.int64()),
        ("vendor_id", pa.int64()),
        ("vendor_price_cents", pa.int64()),
        ("vendor_min_qty", pa.int64()),
        ("vendor_lead_days", pa.int64()),
    ]
)


def write_inputs(root: Path, count: int = 5) -> list[dict[str, Any]]:
    rows = [product_row(n, "Shoes" if n % 3 else "Kitchen & Dining", 1 + n % 2) for n in range(count, 0, -1)]
    processed = root / slice_builder.PROCESSED_DIR
    processed.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=PRODUCT_SCHEMA), processed / shop_catalog.PRODUCTS_FILE)
    pq.write_table(
        pa.table({"vendor_id": [1, 2], "name": ["Synthetic Vendor 01", "Synthetic Vendor 02"]}),
        processed / shop_catalog.VENDORS_FILE,
    )
    outputs = {
        name: {"rows": 0, "sha256": hashlib.sha256((processed / name).read_bytes()).hexdigest()}
        for name in (shop_catalog.PRODUCTS_FILE, shop_catalog.VENDORS_FILE)
    }
    (processed / slice_builder.MANIFEST_NAME).write_text(json.dumps({"outputs": outputs}), encoding="utf-8")
    return sorted(rows, key=lambda row: row["product_id"])


def quiet(text: str) -> None:
    pass


def run(root: Path, odoo: FakeOdoo, **kwargs: Any) -> int:
    return ci.run_import(root, call=odoo, write=quiet, **kwargs)


def test_first_run_creates_everything_with_the_right_fields(tmp_path: Path) -> None:
    rows = write_inputs(tmp_path)
    odoo = FakeOdoo()

    assert run(tmp_path, odoo, batch_size=2) == 0

    public = {r["name"]: r["id"] for r in odoo.table("product.public.category").values()}
    internal = {r["name"]: r for r in odoo.table("product.category").values()}
    vendors = {r["ref"]: r for r in odoo.table("res.partner").values()}
    assert set(public) == {"Shoes", "Kitchen & Dining"}
    assert internal["Shoes"]["parent_id"] == internal[ci.INTERNAL_ROOT]["id"]
    assert set(vendors) == {"synthetic-vendor-01", "synthetic-vendor-02"}
    assert all(vendor["is_company"] and vendor["supplier_rank"] == 1 for vendor in vendors.values())

    products = odoo.products()
    assert sorted(products) == [row["product_id"] for row in rows]
    product = products["B0001"]
    assert product["name"] == "Product 1"
    assert product["brand"] == "Acme"
    assert products["B0002"]["brand"] is False
    assert product["list_price"] == 21.99
    assert (product["type"], product["is_storable"], product["is_published"]) == ("consu", True, True)
    assert product["taxes_id"] == []
    assert product["public_categ_ids"] == [public["Shoes"]]
    assert product["categ_id"] == internal["Shoes"]["id"]
    assert product["description_sale"] == "Line one of 1\nLine <two> & more"
    assert product["description_ecommerce"] == "<p>Line one of 1</p><p>Line &lt;two&gt; &amp; more</p>"
    lines = [
        line
        for line in odoo.table("product.supplierinfo").values()
        if line["product_tmpl_id"] == product["id"]
    ]
    assert len(lines) == 1
    assert lines[0]["partner_id"] == vendors["synthetic-vendor-02"]["id"]
    assert (lines[0]["price"], lines[0]["min_qty"], lines[0]["delay"]) == (13.6, 2.0, 3)

    id_map = pq.read_table(tmp_path / slice_builder.PROCESSED_DIR / ci.ID_MAP_FILE).to_pylist()
    assert [row["product_id"] for row in id_map] == sorted(products)
    assert all(row["variant_id"] == row["template_id"] + 100_000 for row in id_map)


def test_second_run_creates_and_writes_nothing(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    odoo = FakeOdoo()
    assert run(tmp_path, odoo, batch_size=2) == 0
    odoo.calls.clear()

    assert run(tmp_path, odoo, batch_size=2) == 0
    assert odoo.count("create") == 0
    assert odoo.count("write") == 0


def test_a_changed_product_is_written_back_and_nothing_else(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    odoo = FakeOdoo()
    assert run(tmp_path, odoo) == 0
    product = odoo.products()["B0003"]
    product["list_price"] = 1.0
    product["taxes_id"] = [42]
    lines = odoo.table("product.supplierinfo")
    for line_id in [i for i, line in lines.items() if line["product_tmpl_id"] == product["id"]]:
        lines[line_id]["price"] = 0.5
    odoo.calls.clear()

    assert run(tmp_path, odoo) == 0
    writes = [body for model, method, body in odoo.calls if method == "write"]
    assert len(writes) == 1
    assert writes[0]["ids"] == [product["id"]]
    assert set(writes[0]["vals"]) == {"list_price", "taxes_id", "seller_ids"}
    assert odoo.products()["B0003"]["list_price"] == 23.99
    assert len([line for line in lines.values() if line["product_tmpl_id"] == product["id"]]) == 1


def test_a_failed_batch_resumes_without_duplicates(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    odoo = FakeOdoo(fail_on_product_create=2)

    assert run(tmp_path, odoo, batch_size=2) == 1
    assert len(odoo.products()) == 2  # batch 1 done, batch 2 refused
    assert not (tmp_path / slice_builder.PROCESSED_DIR / ci.ID_MAP_FILE).exists()

    odoo.fail_on_product_create = None
    assert run(tmp_path, odoo, batch_size=2) == 0
    codes = [record["default_code"] for record in odoo.table("product.template").values()]
    assert sorted(codes) == sorted(set(codes))
    assert len(codes) == 5
    assert len(odoo.table("res.partner")) == 2
    assert len(odoo.table("product.public.category")) == 2


def test_limit_imports_the_first_products_by_id(tmp_path: Path) -> None:
    rows = write_inputs(tmp_path)
    odoo = FakeOdoo()

    assert run(tmp_path, odoo, limit=3) == 0
    assert sorted(odoo.products()) == [row["product_id"] for row in rows[:3]]
    id_map = pq.read_table(tmp_path / slice_builder.PROCESSED_DIR / ci.ID_MAP_FILE)
    assert id_map.num_rows == 3


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    odoo = FakeOdoo()
    lines: list[str] = []

    assert ci.run_import(tmp_path, dry_run=True, call=odoo, write=lines.append) == 0
    assert odoo.count("create") == 0
    assert odoo.count("write") == 0
    assert any("5 would be created" in line for line in lines)
    assert not (tmp_path / slice_builder.PROCESSED_DIR / ci.ID_MAP_FILE).exists()

    assert run(tmp_path, odoo) == 0
    lines.clear()
    assert ci.run_import(tmp_path, dry_run=True, call=odoo, write=lines.append) == 0
    assert any("0 would be created, 0 updated, 5 unchanged" in line for line in lines)


def test_lookups_include_archived_records(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    odoo = FakeOdoo()

    assert run(tmp_path, odoo) == 0
    searches = [body for _, method, body in odoo.calls if method == "search_read"]
    assert searches
    assert all(body["context"] == {"active_test": False} for body in searches)


def test_inputs_not_matching_the_manifest_are_refused(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    products = tmp_path / slice_builder.PROCESSED_DIR / shop_catalog.PRODUCTS_FILE
    products.write_bytes(products.read_bytes() + b"x")
    odoo = FakeOdoo()

    assert run(tmp_path, odoo) == 1
    assert odoo.calls == []


def test_a_missing_api_key_is_reported(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            f"{key}={value}"
            for key, value in {
                "ODOO_DB_NAME": "shop",
                "ODOO_ADMIN_LOGIN_PASSWORD": "fake-admin",  # pragma: allowlist secret
                "ODOO_INTEGRATION_LOGIN": "shop_integration",
                odoodb.API_KEY_ENV: "",
            }.items()
        ),
        encoding="utf-8",
    )
    with pytest.raises(ci.CatalogImportError, match="ODOO_API_KEY"):
        ci.json2_caller(tmp_path)
    assert ci.run_import(tmp_path, write=quiet) == 1


def test_html_description_escapes_the_source_text() -> None:
    assert ci.html_description("<script>alert(1)</script>\n\nok") == (
        "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p><p>ok</p>"
    )
    assert ci.html_description("") == ""


def test_product_changes_compares_like_odoo_stores() -> None:
    wanted = ci.product_values(product_row(1), public_id=7, internal_id=9)
    stored = {
        **wanted,
        "categ_id": [9, "Shop catalog / Shoes"],
        "public_categ_ids": [7],
        "taxes_id": [],
        "list_price": 21.990000001,
        "brand": "Acme",
    }
    assert ci.product_changes(wanted, stored) == {}
    stored["public_categ_ids"] = [7, 8]
    stored["brand"] = False
    assert ci.product_changes(wanted, stored) == {"public_categ_ids": [[6, 0, [7]]], "brand": "Acme"}


def test_html_description_keeps_quotes_as_odoo_stores_them() -> None:
    # Odoo's sanitizer stores ' and " as plain characters: escaping them would rewrite the field on every run.
    assert (
        ci.html_description('Children\'s "Art" & <Crafts>') == '<p>Children\'s "Art" &amp; &lt;Crafts&gt;</p>'
    )
    wanted = ci.product_values({**product_row(1), "description": "It's"}, public_id=7, internal_id=9)
    stored = {
        **wanted,
        "categ_id": [9, "x"],
        "public_categ_ids": [7],
        "description_ecommerce": "<p>It&#x27;s</p>",
    }
    assert ci.product_changes(wanted, stored) == {}


# --- Task 2.4b: stock, cost, verify, report -----------------------------------------------------------------


def test_stock_is_set_by_inventory_adjustment_and_out_of_stock_needs_no_move(tmp_path: Path) -> None:
    rows = write_inputs(tmp_path, count=8)
    odoo = FakeOdoo()

    assert run(tmp_path, odoo, batch_size=3) == 0
    assert odoo.stock() == {row["product_id"]: float(row["stock_qty"]) for row in rows}
    in_stock = [row for row in rows if row["stock_qty"] > 0]
    assert odoo.moves == len(in_stock)  # B0004 and B0008 start at 0: no quant, no move
    quants = odoo.table("stock.quant").values()
    assert {quant["location_id"] for quant in quants} == {STOCK_LOCATION}
    assert len(quants) == len(in_stock)


def test_second_run_moves_no_stock(tmp_path: Path) -> None:
    write_inputs(tmp_path, count=8)
    odoo = FakeOdoo()
    assert run(tmp_path, odoo, batch_size=3) == 0
    moves = odoo.moves
    odoo.calls.clear()

    assert run(tmp_path, odoo, batch_size=3) == 0
    assert odoo.moves == moves
    assert odoo.count("create", "stock.quant") == 0
    assert odoo.count("action_apply_inventory") == 0


def test_a_changed_quantity_is_adjusted_back(tmp_path: Path) -> None:
    write_inputs(tmp_path, count=8)
    odoo = FakeOdoo()
    assert run(tmp_path, odoo) == 0
    variant = odoo.products()["B0005"]["product_variant_id"]
    quant = next(q for q in odoo.table("stock.quant").values() if q["product_id"] == variant)
    quant["quantity"] = 1.0  # sold or counted differently in the shop
    moves = odoo.moves

    assert run(tmp_path, odoo) == 0
    assert odoo.stock()["B0005"] == 8.0
    assert odoo.moves == moves + 1


def test_a_stock_conflict_stops_the_run(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    odoo = FakeOdoo()
    odoo.stock_conflict = True

    assert run(tmp_path, odoo) == 1
    assert not (tmp_path / slice_builder.PROCESSED_DIR / ci.ID_MAP_FILE).exists()


def test_cost_is_the_vendor_price(tmp_path: Path) -> None:
    rows = write_inputs(tmp_path)
    odoo = FakeOdoo()

    assert run(tmp_path, odoo) == 0
    products = odoo.products()
    for row in rows:
        assert products[row["product_id"]]["standard_price"] == row["vendor_price_cents"] / 100


def test_dry_run_counts_stock_to_adjust_without_moving_any(tmp_path: Path) -> None:
    write_inputs(tmp_path, count=8)
    odoo = FakeOdoo()
    assert run(tmp_path, odoo) == 0
    next(iter(odoo.table("stock.quant").values()))["quantity"] = 99.0
    moves = odoo.moves
    lines: list[str] = []

    assert ci.run_import(tmp_path, dry_run=True, call=odoo, write=lines.append) == 0
    assert any("stock: 1 would be adjusted, 7 already right" in line for line in lines)
    assert odoo.moves == moves


def test_verify_passes_after_an_import_and_names_what_differs(tmp_path: Path) -> None:
    write_inputs(tmp_path, count=8)
    odoo = FakeOdoo()
    assert run(tmp_path, odoo) == 0
    lines: list[str] = []

    assert ci.run_verify(tmp_path, sample=4, seed=1, call=odoo, write=lines.append) == 0
    assert lines[-1] == "4 of 4 match.\n"

    for product in odoo.products().values():
        product["list_price"] = 0.0
    lines.clear()
    assert ci.run_verify(tmp_path, sample=4, seed=1, call=odoo, write=lines.append) == 1
    assert sum("differs: list_price" in line for line in lines) == 4


def test_verify_reports_missing_products_and_wrong_stock(tmp_path: Path) -> None:
    write_inputs(tmp_path, count=8)
    odoo = FakeOdoo()
    assert run(tmp_path, odoo, limit=4) == 0
    for quant in odoo.table("stock.quant").values():
        quant["quantity"] += 1
    lines: list[str] = []

    assert ci.run_verify(tmp_path, sample=8, seed=1, call=odoo, write=lines.append) == 1
    failed = [line for line in lines if "FAIL" in line]
    assert sum("differs: missing" in line for line in failed) == 4
    assert sum("differs: stock" in line for line in failed) == 3  # B0004 has no quant: still 0


def test_a_real_run_writes_its_record(tmp_path: Path) -> None:
    write_inputs(tmp_path, count=8)
    odoo = FakeOdoo()

    assert run(tmp_path, odoo, limit=6, batch_size=4) == 0
    report = (tmp_path / ci.REPORT_FILE).read_text(encoding="utf-8")
    assert "`uv run shop import catalog --limit 6 --batch-size 4`" in report
    assert "| products | 6 | 0 | 0 |" in report
    assert "| stock (inventory adjustment) | — | 5 adjusted | 1 |" in report
    assert "2 batches of up to 4" in report

    lines: list[str] = []
    assert ci.run_import(tmp_path, dry_run=True, call=odoo, write=lines.append) == 0
    assert (tmp_path / ci.REPORT_FILE).read_text(encoding="utf-8") == report  # a dry run leaves no record


# --- 2.4b follow-up: stock availability in the shop, grouped writes, record only on change -----------------


def test_products_show_availability_and_refuse_orders_when_out_of_stock(tmp_path: Path) -> None:
    write_inputs(tmp_path)
    odoo = FakeOdoo()

    assert run(tmp_path, odoo) == 0
    for product in odoo.products().values():
        assert product["show_availability"] is True
        assert product["allow_out_of_stock_order"] is False


def test_the_same_change_on_many_products_is_one_write_per_batch(tmp_path: Path) -> None:
    write_inputs(tmp_path, count=8)
    odoo = FakeOdoo()
    assert run(tmp_path, odoo, batch_size=4) == 0
    for product in odoo.products().values():  # as before the follow-up: Odoo's defaults
        product["show_availability"] = False
        product["allow_out_of_stock_order"] = True
    odoo.calls.clear()

    assert run(tmp_path, odoo, batch_size=4) == 0
    writes = [body for _, method, body in odoo.calls if method == "write"]
    assert len(writes) == 2  # 2 batches of 4
    assert all(
        body["vals"] == {"show_availability": True, "allow_out_of_stock_order": False} for body in writes
    )
    assert sorted(i for body in writes for i in body["ids"]) == sorted(
        p["id"] for p in odoo.products().values()
    )


def test_a_run_that_changes_nothing_keeps_the_last_record(tmp_path: Path) -> None:
    write_inputs(tmp_path, count=8)
    odoo = FakeOdoo()
    assert run(tmp_path, odoo) == 0
    record = (tmp_path / ci.REPORT_FILE).read_text(encoding="utf-8")
    lines: list[str] = []

    assert ci.run_import(tmp_path, call=odoo, write=lines.append) == 0
    assert (tmp_path / ci.REPORT_FILE).read_text(encoding="utf-8") == record
    assert not any("Record of this run" in line for line in lines)
