from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from conftest import REPO_ROOT, edit_distance

from shoptools.data import esci, shop_catalog
from shoptools.data import slice_builder as sb
from shoptools.data.enrichment import load_category_rules
from shoptools.data.normalize import normalize_query
from shoptools.doctor.expected import VERSIONS_FILE

CONFIG = """
[slice]
seed = {seed}
locale = "us"
small_version = 1

[queries]
dev = {{ size = 3, split = "train" }}
test = {{ size = 4, split = "test" }}

[gains]
E = 1.0
S = 0.1
C = 0.01
I = 0.0

[typos]
min_word_letters = 4

[enrichment]
categories_file = "categories.toml"
price = {{ min_dollars = 2, max_dollars = 999 }}
stock = {{ min = 3, max = 150 }}
vendors = 4
vendor_price_share = {{ min = 0.55, max = 0.75 }}
vendor_min_qty = {{ min = 1, max = 10 }}
vendor_lead_days = {{ min = 2, max = 14 }}
description_max_chars = 200

[hidden]
query_share = {hidden_share}

[out_of_stock]
share = 0.1
"""
CATEGORIES = """
[[category]]
name = "Shoes"
price_median = 50.0
price_sigma = 0.5
keywords = ["shoe", "running shoe"]

[[category]]
name = "Devices"
price_median = 20.0
price_sigma = 0.5
keywords = ["gadget"]

[other]
name = "Other"
price_median = 10.0
price_sigma = 0.5
"""
LABEL_CYCLE = "ESCIES"


def config_text(seed: int, hidden_share: float = 0.2) -> str:
    return CONFIG.format(seed=seed, hidden_share=hidden_share)


def product_word(product_id: str) -> str:
    """Titles that the test category rules can place: T* products are shoes, P* and U* gadgets, X* nothing."""
    return {"T": "running shoes", "P": "gadget", "U": "gadget"}.get(product_id[0], "title")


def synthetic_esci() -> tuple[dict[str, list], dict[str, list]]:
    """ESCI-format examples and products.

    - train queries 1..12 ("brand<i> running shoes"); test queries 101..112 repeat the train texts with
      other case and punctuation ("BRAND<i> Running Shoes!"): each dev query has one twin in the test pool;
      test queries 113..115 are unique; query 116 has no word of 4 letters ("tv 4k").
    - each query judges 3 products, one of them shared with the next query.
    - noise the builder must ignore: query 200 in locale "es", query 300 with small_version 0.
    """
    examples: dict[str, list] = {
        name: []
        for name in (
            "query_id",
            "query",
            "product_id",
            "product_locale",
            "esci_label",
            "small_version",
            "split",
        )
    }

    def judge(
        query_id: int, text: str, split: str, products: list[str], locale: str = "us", small: int = 1
    ) -> None:
        for n, product_id in enumerate(products):
            examples["query_id"].append(query_id)
            examples["query"].append(text)
            examples["product_id"].append(product_id)
            examples["product_locale"].append(locale)
            examples["esci_label"].append(LABEL_CYCLE[(query_id + n) % len(LABEL_CYCLE)])
            examples["small_version"].append(small)
            examples["split"].append(split)

    for i in range(1, 13):
        judge(i, f"brand{i} running shoes", "train", [f"P{i:03}", f"P{i:03}b", f"P{i + 1:03}"])
    for i in range(1, 13):
        judge(100 + i, f"BRAND{i} Running Shoes!", "test", [f"T{i:03}", f"T{i:03}b", f"T{i + 1:03}"])
    for i in range(13, 16):
        judge(100 + i, f"unique gadget {i}", "test", [f"U{i:03}", f"U{i:03}b", f"P{i - 12:03}"])
    judge(116, "tv 4k", "test", ["U900", "U901", "U902"])
    judge(200, "zapatos", "train", ["ES1"], locale="es")
    judge(300, "big catalog only", "test", ["BIG1"], small=0)

    pairs = zip(examples["product_id"], examples["product_locale"], strict=True)
    judged = sorted({pid for pid, loc in pairs if loc == "us"})
    extra = ["X001", "X002"]
    product_ids = [*judged, *extra, "P001"]  # P001 again, in locale "es": must not reach the catalog
    locales = ["us"] * (len(judged) + len(extra)) + ["es"]
    products = {
        "product_id": product_ids,
        "product_title": [
            f"{product_word(pid)} {pid} {loc}" for pid, loc in zip(product_ids, locales, strict=True)
        ],
        "product_description": [None if n % 4 == 0 else f"description {n}" for n in range(len(product_ids))],
        "product_bullet_point": ["  " if n % 5 == 0 else f"bullet {n}" for n in range(len(product_ids))],
        "product_brand": [f"brand {n % 7}" for n in range(len(product_ids))],
        "product_color": [None] * len(product_ids),
        "product_locale": locales,
    }
    return examples, products


def write_repo(
    root: Path,
    seed: int = 20261025,
    products_override: dict[str, list] | None = None,
    hidden_share: float = 0.2,
) -> Path:
    examples, products = synthetic_esci()
    raw = root / esci.RAW_DIR
    raw.mkdir(parents=True)
    pq.write_table(pa.table(examples), raw / esci.EXAMPLES)
    pq.write_table(pa.table(products_override or products), raw / esci.PRODUCTS)
    blocks = ['[datasets.esci]\nrepository = "o/r"\ncommit = "c"\nfolder = "f"\nlicense = "Apache-2.0"\n']
    for name in (esci.EXAMPLES, esci.PRODUCTS):
        content = (raw / name).read_bytes()
        blocks.append(
            f'[[datasets.esci.files]]\nname = "{name}"\nlfs = true\nsize_bytes = {len(content)}\n'
            f'sha256 = "{hashlib.sha256(content).hexdigest()}"\n'
        )
    (root / VERSIONS_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / VERSIONS_FILE).write_text("\n".join(blocks), encoding="utf-8")
    config = root / "slice.toml"
    config.write_text(config_text(seed, hidden_share), encoding="utf-8")
    (root / "categories.toml").write_text(CATEGORIES, encoding="utf-8")
    return config


def quiet(text: str) -> None:
    pass


def build(root: Path, seed: int = 20261025) -> dict:
    config = write_repo(root, seed)
    assert sb.run_build_slice(root, config_path=config, write=quiet) == 0
    return json.loads((root / sb.PROCESSED_DIR / sb.MANIFEST_NAME).read_text(encoding="utf-8"))


def read(root: Path, name: str) -> list[dict]:
    return pq.read_table(root / sb.PROCESSED_DIR / name).to_pylist()


def test_same_inputs_and_seed_give_byte_identical_outputs(tmp_path: Path) -> None:
    first = build(tmp_path / "a")
    second = build(tmp_path / "b")
    other_seed = build(tmp_path / "c", seed=7)

    assert first["outputs"] == second["outputs"]
    for name in sb.OUTPUT_FILES:
        assert (tmp_path / "a" / sb.PROCESSED_DIR / name).read_bytes() == (
            tmp_path / "b" / sb.PROCESSED_DIR / name
        ).read_bytes()
    assert (tmp_path / "a" / sb.REPORT_FILE).read_text(encoding="utf-8") == (
        tmp_path / "b" / sb.REPORT_FILE
    ).read_text(encoding="utf-8")
    assert other_seed["outputs"][sb.DEV_FILE] != first["outputs"][sb.DEV_FILE]
    assert other_seed["config_sha256"] != first["config_sha256"]


def test_recorded_hashes_match_the_files(tmp_path: Path) -> None:
    manifest = build(tmp_path)

    for name, output in manifest["outputs"].items():
        path = tmp_path / sb.PROCESSED_DIR / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == output["sha256"]
        assert pq.read_metadata(path).num_rows == output["rows"]
    assert not list((tmp_path / sb.PROCESSED_DIR).glob("*.tmp"))


def test_dev_and_test_are_disjoint_by_id_and_by_normalized_text(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    dev, test = read(tmp_path, sb.DEV_FILE), read(tmp_path, sb.TEST_FILE)

    assert len(dev) == 3
    assert len(test) == 4
    assert {row["query_id"] for row in dev} <= set(range(1, 13))  # train split only, never the noise queries
    assert {row["query_id"] for row in test} <= set(range(101, 117))
    dev_texts = {normalize_query(row["query"]) for row in dev}
    assert not dev_texts & {normalize_query(row["query"]) for row in test}
    assert [row["query_normalized"] for row in dev] == [normalize_query(row["query"]) for row in dev]
    # Each dev query has exactly one test twin ("brand<i> running shoes" vs "BRAND<i> Running Shoes!").
    assert manifest["counts"]["pool"] == {"dev": 12, "test": 16, "removed_duplicates": 3}
    assert [row["query_id"] for row in dev] == sorted(row["query_id"] for row in dev)


def test_qrels_hold_every_judgment_of_the_selected_queries_with_its_gain(tmp_path: Path) -> None:
    build(tmp_path)
    examples, _ = synthetic_esci()
    selected = {row["query_id"]: "dev" for row in read(tmp_path, sb.DEV_FILE)} | {
        row["query_id"]: "test" for row in read(tmp_path, sb.TEST_FILE)
    }
    expected = sorted(
        (query_id, product_id, label)
        for query_id, product_id, label in zip(
            examples["query_id"], examples["product_id"], examples["esci_label"], strict=True
        )
        if query_id in selected
    )
    qrels = read(tmp_path, sb.QRELS_FILE)

    assert [(row["query_id"], row["product_id"], row["esci_label"]) for row in qrels] == expected
    assert all(row["query_set"] == selected[row["query_id"]] for row in qrels)
    gains = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}
    assert all(row["gain"] == gains[row["esci_label"]] for row in qrels)


def test_catalog_is_exactly_the_judged_products_of_the_locale(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    judged = {row["product_id"] for row in read(tmp_path, sb.QRELS_FILE)}
    catalog = read(tmp_path, sb.CATALOG_FILE)

    assert [row["product_id"] for row in catalog] == sorted(judged)
    assert all(row["product_title"].endswith(" us") for row in catalog)  # not the "es" copy of P001
    assert list(catalog[0]) == ["product_id", *sb.PRODUCT_TEXT_COLUMNS]
    assert manifest["counts"]["catalog"]["products"] == len(judged)
    assert manifest["counts"]["catalog"]["empty_fields"]["product_color"] == len(judged)


def test_test_typo_has_one_edit_per_query_or_none(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    test = {row["query_id"]: row["query"] for row in read(tmp_path, sb.TEST_FILE)}
    typos = read(tmp_path, sb.TYPO_FILE)

    assert [row["query_id"] for row in typos] == sorted(test)
    for row in typos:
        assert row["query_original"] == test[row["query_id"]]
        if row["typo_operation"] is None:
            assert row["query"] == row["query_original"]
            assert row["typo_position"] is None
        else:
            assert edit_distance(row["query_original"], row["query"]) == 1
    counts = manifest["counts"]["test_typo"]
    assert counts["unchanged"] == sum(1 for row in typos if row["typo_operation"] is None)
    assert counts["unchanged"] + sum(counts["operations"].values()) == 4


def test_query_without_an_eligible_word_stays_unchanged() -> None:
    config = sb.load_config(Path(__file__).parents[1] / "shoptools" / "data" / "slice.toml")
    queries = [sb.Query(1, "tv 4k", "test"), sb.Query(2, "running shoes", "test")]

    rows = sb.build_test_typos(queries, config)

    assert rows[0].operation is None
    assert rows[0].query == "tv 4k"
    assert rows[1].operation is not None


def test_report_has_aggregates_but_no_query_text(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    report = (tmp_path / sb.REPORT_FILE).read_text(encoding="utf-8")

    assert "removed because their normalized text equals a dev query's: **3**" in report
    assert "running" not in report.lower()
    assert "gadget" not in report
    for name in sb.SLICE_OUTPUT_FILES:
        assert manifest["outputs"][name]["sha256"][:16] in report


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    config = write_repo(tmp_path)
    lines: list[str] = []

    assert sb.run_build_slice(tmp_path, dry_run=True, config_path=config, write=lines.append) == 0
    assert not (tmp_path / sb.PROCESSED_DIR).exists()
    assert not (tmp_path / sb.REPORT_FILE).exists()
    assert any("dev 3 of 12" in line for line in lines)


def test_a_missing_judged_product_fails_and_leaves_no_manifest(tmp_path: Path) -> None:
    _, products = synthetic_esci()
    keep = [n for n, pid in enumerate(products["product_id"]) if not pid.startswith(("P", "T"))]
    trimmed = {name: [values[n] for n in keep] for name, values in products.items()}
    config = write_repo(tmp_path, products_override=trimmed)

    assert sb.run_build_slice(tmp_path, config_path=config, write=quiet) == 1
    assert not (tmp_path / sb.PROCESSED_DIR / sb.MANIFEST_NAME).exists()


def test_a_changed_input_file_is_refused(tmp_path: Path) -> None:
    config = write_repo(tmp_path)
    examples = tmp_path / esci.RAW_DIR / esci.EXAMPLES
    content = bytearray(examples.read_bytes())
    content[10] ^= 0xFF  # same size, different bytes
    examples.write_bytes(bytes(content))

    assert sb.run_build_slice(tmp_path, config_path=config, write=quiet) == 1
    assert not (tmp_path / sb.PROCESSED_DIR).exists()


def test_a_rerun_replaces_the_previous_outputs(tmp_path: Path) -> None:
    first = build(tmp_path)
    config = tmp_path / "slice.toml"

    assert sb.run_build_slice(tmp_path, config_path=config, write=quiet) == 0
    second = json.loads((tmp_path / sb.PROCESSED_DIR / sb.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert first == second


def test_config_rules(tmp_path: Path) -> None:
    path = tmp_path / "slice.toml"
    path.write_text(config_text(1).replace('split = "test"', 'split = "train"'), encoding="utf-8")
    with pytest.raises(sb.SliceError, match="different ESCI splits"):
        sb.load_config(path)
    path.write_text(config_text(1).replace("I = 0.0\n", ""), encoding="utf-8")
    with pytest.raises(sb.SliceError, match="exactly the labels"):
        sb.load_config(path)
    path.write_text("[slice]\nseed = 1\n", encoding="utf-8")
    with pytest.raises(sb.SliceError, match="not valid"):
        sb.load_config(path)


def test_config_hash_ignores_comments_and_spacing(tmp_path: Path) -> None:
    plain, commented = tmp_path / "a.toml", tmp_path / "b.toml"
    plain.write_text(config_text(1), encoding="utf-8")
    commented.write_text(
        "# a comment\n" + config_text(1).replace("seed = 1", "seed   =   1  # base"), "utf-8"
    )

    assert sb.load_config(plain).sha256 == sb.load_config(commented).sha256


def test_derived_streams_are_independent_and_repeatable() -> None:
    first, again = (sb.derived_rng(1, "dev-queries").random() for _ in range(2))
    assert first == again
    assert first != sb.derived_rng(1, "test-queries").random()
    assert first != sb.derived_rng(2, "dev-queries").random()


def test_project_configuration_follows_the_protocol() -> None:
    config = sb.load_config(Path(__file__).parents[1] / "shoptools" / "data" / "slice.toml")

    assert config.seed == 20261025
    assert (config.locale, config.small_version) == ("us", 1)
    assert (config.dev.size, config.dev.split, config.test.size, config.test.split) == (
        300,
        "train",
        700,
        "test",
    )
    assert config.gains == {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}
    assert config.min_word_letters == 4
    # Protocol v1.1 §4, option B2 (supervisor, 2026-11-14).
    assert config.shop.hidden_query_share == 0.2
    assert config.shop.out_of_stock_share == 0.1
    rules = load_category_rules(REPO_ROOT / config.shop.categories_file)
    assert 15 <= len(rules.categories) <= 25


# --- Task 2.3b: shop catalog --------------------------------------------------------------------------------


def exact_by_query(root: Path) -> dict[int, set[str]]:
    targets: dict[int, set[str]] = {}
    for row in read(root, sb.QRELS_FILE):
        if row["esci_label"] == "E":
            targets.setdefault(row["query_id"], set()).add(row["product_id"])
    return targets


def test_shop_catalog_does_not_change_the_slice_outputs(tmp_path: Path) -> None:
    config = write_repo(tmp_path / "a", hidden_share=0.2)
    assert sb.run_build_slice(tmp_path / "a", config_path=config, write=quiet) == 0
    config = write_repo(tmp_path / "b", hidden_share=0.5)
    assert sb.run_build_slice(tmp_path / "b", config_path=config, write=quiet) == 0
    first, second = (
        json.loads((tmp_path / name / sb.PROCESSED_DIR / sb.MANIFEST_NAME).read_text(encoding="utf-8"))
        for name in ("a", "b")
    )

    for name in sb.SLICE_OUTPUT_FILES:
        assert first["outputs"][name] == second["outputs"][name]
    assert first["outputs"][shop_catalog.HIDDEN_TEST_FILE] != second["outputs"][shop_catalog.HIDDEN_TEST_FILE]


def test_products_carry_every_catalog_product_with_synthetic_fields(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    catalog = read(tmp_path, sb.CATALOG_FILE)
    products = read(tmp_path, shop_catalog.PRODUCTS_FILE)

    assert [row["product_id"] for row in products] == [row["product_id"] for row in catalog]
    assert [row["name"] for row in products] == [row["product_title"] for row in catalog]
    assert {row["category"] for row in products if row["product_id"].startswith("T")} == {"Shoes"}
    assert {row["category"] for row in products if row["product_id"].startswith(("P", "U"))} == {"Devices"}
    for row in products:
        assert row["list_price_cents"] % 100 == 99
        assert 299 <= row["list_price_cents"] <= 99_999
        assert 0.54 <= row["vendor_price_cents"] / row["list_price_cents"] <= 0.76
        assert 1 <= row["vendor_id"] <= 4
        assert len(row["description"]) <= 200
    assert manifest["synthetic_fields"][shop_catalog.PRODUCTS_FILE] == list(shop_catalog.SYNTHETIC_FIELDS)
    assert len(read(tmp_path, shop_catalog.VENDORS_FILE)) == 4


def test_hidden_sets_hide_every_exact_product_of_their_queries(tmp_path: Path) -> None:
    build(tmp_path)
    targets = exact_by_query(tmp_path)
    dev = {row["query_id"] for row in read(tmp_path, sb.DEV_FILE)}
    test = {row["query_id"] for row in read(tmp_path, sb.TEST_FILE)}
    hidden = {}
    for name, own in ((shop_catalog.HIDDEN_TEST_FILE, test), (shop_catalog.HIDDEN_DEV_FILE, dev)):
        rows = read(tmp_path, name)
        queries = {row["query_id"] for row in rows}
        assert len(queries) == round(0.2 * len(own))  # 1 of 4 test queries, 1 of 3 dev queries
        assert queries <= own
        for query_id in queries:
            assert {row["product_id"] for row in rows if row["query_id"] == query_id} == targets[query_id]
        hidden[name] = {row["product_id"] for row in rows}

    assert not hidden[shop_catalog.HIDDEN_TEST_FILE] & hidden[shop_catalog.HIDDEN_DEV_FILE]


def test_out_of_stock_products_have_zero_stock_and_are_searched_targets(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    targets = exact_by_query(tmp_path)
    hidden_rows = read(tmp_path, shop_catalog.HIDDEN_TEST_FILE) + read(tmp_path, shop_catalog.HIDDEN_DEV_FILE)
    hidden_queries = {row["query_id"] for row in hidden_rows}
    hidden_products = {row["product_id"] for row in hidden_rows}
    out_of_stock = {row["product_id"] for row in read(tmp_path, shop_catalog.OUT_OF_STOCK_FILE)}
    searched = {
        p for query_id, products in targets.items() if query_id not in hidden_queries for p in products
    }

    assert out_of_stock
    assert out_of_stock <= searched - hidden_products
    products = read(tmp_path, shop_catalog.PRODUCTS_FILE)
    assert {row["product_id"] for row in products if row["stock_qty"] == 0} == out_of_stock
    assert all(3 <= row["stock_qty"] <= 150 for row in products if row["product_id"] not in out_of_stock)
    wanted = round(0.1 * (len(products) - len(hidden_products)))
    assert len(out_of_stock) == min(wanted, len(searched - hidden_products))
    assert manifest["counts"]["shop_catalog"]["out_of_stock"]["products"] == len(out_of_stock)


def test_enrichment_report_is_labelled_synthetic_and_has_no_text(tmp_path: Path) -> None:
    manifest = build(tmp_path)
    report = (tmp_path / sb.ENRICHMENT_REPORT_FILE).read_text(encoding="utf-8")

    assert "**Synthetic data.**" in report
    assert "running" not in report.lower()
    assert "gadget" not in report.lower()
    for name in shop_catalog.OUTPUT_FILES:
        assert manifest["outputs"][name]["sha256"][:16] in report
    assert "products in both hidden sets: 0 (must be 0)" in report


def test_bad_category_rules_fail_cleanly(tmp_path: Path) -> None:
    config = write_repo(tmp_path)
    (tmp_path / "categories.toml").write_text("[[category]]\nname = 'x'\n", encoding="utf-8")

    assert sb.run_build_slice(tmp_path, config_path=config, write=quiet) == 1
    assert not (tmp_path / sb.PROCESSED_DIR / sb.MANIFEST_NAME).exists()


def test_shop_settings_rules(tmp_path: Path) -> None:
    path = tmp_path / "slice.toml"
    path.write_text(config_text(1, hidden_share=1.5), encoding="utf-8")
    with pytest.raises(sb.SliceError, match="hidden.query_share"):
        sb.load_config(path)
    path.write_text(config_text(1).replace("max = 0.75", "max = 1.2"), encoding="utf-8")
    with pytest.raises(sb.SliceError, match="vendor_price_share"):
        sb.load_config(path)
