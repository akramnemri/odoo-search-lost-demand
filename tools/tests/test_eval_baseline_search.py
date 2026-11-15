from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from shoptools.data import slice_builder
from shoptools.eval import baseline_search as bs

# Shop pages reduced to the markup the parser reads (Odoo 19's website_sale, checked 2026-11-15).
HEADER = "<h1><span class=\"text-muted\">Search results for </span>'<strong>{term}</strong>' {count}</h1>"
GRID = '<section id="o_wsale_products_grid">{items}</section>'
ITEM = '<a href="/shop/{slug}-{id}"><img/></a><a href="/shop/{slug}-{id}">name</a>'


def page(term: str, count: int | None, ids: list[int], fuzzy_from: str | None = None) -> str:
    count_html = f'<small class="text-muted"> ({count})</small>' if count is not None else ""
    fuzzy = (
        f"<div>No results found for '<span>{fuzzy_from}</span>'. "
        f"Showing results for '<span>{term}</span>'.</div>"
        if fuzzy_from
        else ""
    )
    items = "".join(ITEM.format(slug=f"product-{i}", id=i) for i in ids)
    menu = '<a href="/shop/category/shoes-17">Shoes</a><a href="/shop/old-thing-999">before the grid</a>'
    return menu + HEADER.format(term=term, count=count_html) + fuzzy + GRID.format(items=items)


def test_parse_a_results_page() -> None:
    parsed = bs.parse_shop_page(page("otterbox &amp; co", 9, [12, 7, 12, 3]))

    assert parsed == bs.SearchPage(term="otterbox & co", total=9, fuzzy_term=None, template_ids=[12, 7, 3])


def test_parse_a_page_where_odoo_used_another_word() -> None:
    parsed = bs.parse_shop_page(page("sneakers", 110, [1, 2], fuzzy_from="sneakrs"))

    assert (parsed.total, parsed.fuzzy_term, parsed.template_ids) == (110, "sneakers", [1, 2])


def test_parse_a_page_without_results() -> None:
    parsed = bs.parse_shop_page(page("iphne case", None, []))

    assert (parsed.total, parsed.fuzzy_term, parsed.template_ids) == (0, None, [])


def test_a_page_that_is_not_a_search_page_is_refused() -> None:
    with pytest.raises(bs.BaselineError, match="not a shop search page"):
        bs.parse_shop_page("<html>Internal Server Error</html>")


def test_observe_ranks_the_first_expected_product_on_page_one() -> None:
    pages = {"red shoes": page("red shoes", 30, [10, 11, 12])}
    esci_of = {10: "A", 12: "C"}  # 11 is not in the id map

    found = bs.observe("red shoes", ["C", "Z"], pages.__getitem__, esci_of)

    assert found.page_products == ["A", None, "C"]
    assert found.first_expected_rank == 3
    assert found.outcome == "expected product on page 1"


@pytest.mark.parametrize(
    ("total", "fuzzy", "rank", "outcome"),
    [
        (0, None, None, "no results"),
        (5, "word", 1, "replaced by another word"),
        (5, None, None, "results, expected product not on page 1"),
        (5, None, 2, "expected product on page 1"),
    ],
)
def test_outcomes(total: int, fuzzy: str | None, rank: int | None, outcome: str) -> None:
    assert bs.Observation("q", ["A"], total, fuzzy, [], rank).outcome == outcome


def test_dev_rates_by_length_and_negation() -> None:
    observations = [
        bs.Observation("socks", ["A"], 4, None, ["A"], 1),
        bs.Observation("red wool socks", ["A"], 0, None, [], None),
        bs.Observation("fridge without freezer for dorm", ["A"], 0, None, [], None),
        bs.Observation("lamp not led", ["A"], 3, None, [], None),
    ]

    rates = bs.dev_rates(observations)

    assert rates["all"]["queries"] == 4
    assert rates["all"]["no results"] == 2
    assert rates["1–2 words"]["exact match on page 1"] == 1
    assert rates["5+ words"]["no results"] == 1
    assert rates["with a negation word"]["queries"] == 2
    assert rates["all"]["median results"] == 3


# --- query file and end-to-end run on a small fake slice ----------------------------------------------------


def write_slice(root: Path) -> None:
    processed = root / slice_builder.PROCESSED_DIR
    processed.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "query_id": [1, 2],
                "query": ["red shoes", "wool socks without holes"],
                "query_normalized": ["red shoes", "wool socks without holes"],
            }
        ),
        processed / slice_builder.DEV_FILE,
    )
    pq.write_table(
        pa.table({"query_id": [9], "query": ["Blue Hat"], "query_normalized": ["blue hat"]}),
        processed / slice_builder.TEST_FILE,
    )
    pq.write_table(
        pa.table(
            {
                "query_set": ["dev", "dev", "dev", "test", "test"],
                "query_id": [1, 1, 2, 9, 9],
                "product_id": ["A", "B", "C", "H", "B"],  # B is judged for a test query too
                "esci_label": ["E", "E", "E", "E", "S"],
                "gain": [1.0, 1.0, 1.0, 1.0, 0.1],
            }
        ),
        processed / slice_builder.QRELS_FILE,
    )
    pq.write_table(
        pa.table(
            {"product_id": ["A", "B", "C", "H"], "template_id": [10, 11, 12, 19], "variant_id": [0, 0, 0, 0]}
        ),
        processed / "odoo_id_map.parquet",
    )


def write_queries(root: Path, entries: list[dict]) -> None:
    lines = []
    for entry in entries:
        lines.append("[[query]]")
        for key, value in entry.items():
            lines.append(f"{key} = {json.dumps(value)}")
    target = root / bs.QUERY_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


GOOD = {
    "group": "typo",
    "query": "red shoez",
    "control": "red shoes",
    "expected": ["A"],
    "source": "dev query 1",
    "why": "typo",
}


def test_the_query_file_must_stay_on_dev_data(tmp_path: Path) -> None:
    write_slice(tmp_path)
    dev = bs.read_dev_data(tmp_path)
    write_queries(
        tmp_path,
        [
            {**GOOD, "query": "BLUE hat!", "control": "blue cap"},  # a test query, normalized
            {**GOOD, "expected": ["B"]},  # judged for a test query
            {**GOOD, "group": "spelling"},
        ],
    )

    with pytest.raises(bs.BaselineError) as refused:
        bs.load_hand_picked(tmp_path / bs.QUERY_FILE, dev)
    message = str(refused.value)
    assert "'BLUE hat!' is a test query" in message
    assert "B is not a dev-only judged product" in message
    assert "unknown group 'spelling'" in message


def test_a_run_writes_the_table_and_the_run_folder(tmp_path: Path) -> None:
    write_slice(tmp_path)
    write_queries(tmp_path, [GOOD])
    pages = {
        "red shoez": page("red shoez", None, []),
        "red shoes": page("red shoes", 2, [11, 10]),
        "wool socks without holes": page("wool socks without holes", None, []),
    }
    lines: list[str] = []

    assert bs.run_baseline_search(tmp_path, fetch=pages.__getitem__, write=lines.append) == 0
    summary = (tmp_path / bs.SUMMARY_FILE).read_text(encoding="utf-8")
    assert "| typo | `red shoez` | **0** | `red shoes` | 2 results; expected: #2 |" in summary
    assert "| all | 2 | 1 (50%) | 0 (0%) | 1 (50%) |" in summary
    run_dir = next((tmp_path / "results").glob("baseline-search-*"))
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert meta["requests"] == 4
    assert meta["database_state"].startswith("snapshot baseline-catalog")
    observations = json.loads((run_dir / "observations.json").read_text(encoding="utf-8"))
    assert observations["hand_picked"][0]["control"]["first_expected_rank"] == 2


def test_hand_picked_only(tmp_path: Path) -> None:
    write_slice(tmp_path)
    write_queries(tmp_path, [GOOD])
    pages = {"red shoez": page("red shoez", None, []), "red shoes": page("red shoes", 1, [10])}

    assert (
        bs.run_baseline_search(tmp_path, with_dev=False, fetch=pages.__getitem__, write=lambda _: None) == 0
    )
    assert "All 2 dev queries" not in (tmp_path / bs.SUMMARY_FILE).read_text(encoding="utf-8")


def test_the_table_keeps_the_dirty_mark_and_singular_result() -> None:
    meta = {"run_id": "r", "git": "a" * 40 + "-dirty", "start": "t", "requests": 1, "seconds": 1.0}
    entry = bs.HandPicked("typo", "q", ["A"], "s", "w")
    one = bs.Observation("q", ["A"], 1, None, ["A"], 1)

    summary = bs.render_summary(meta, [(entry, one, None)], {})

    assert f"git `{'a' * 12}-dirty`" in summary
    assert "1 result; expected: #1" in summary
