"""Host tests of addons/website_sale_lost_demand/services/product_index.py with an in-memory Elasticsearch."""

from __future__ import annotations

import fnmatch
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from services.config import EsConfig
from services.es_client import EsClient
from services.product_index import (
    DEFINITION_DIR,
    PRODUCTS,
    SYNONYMS_SET,
    IndexNames,
    IndexStatus,
    ProductValues,
    RebuildError,
    alias_holders,
    build_document,
    bulk_failures,
    bulk_operations,
    load_definition,
    next_index,
    read_status,
    rebuild,
    swap_actions,
)

# --- an in-memory cluster with the calls the service makes ---


class FakeIndices:
    def __init__(self, owner: FakeCluster) -> None:
        self._owner = owner

    def get_alias(self, index: str) -> dict[str, Any]:
        self._owner.calls.append("get_alias")
        return {
            name: {"aliases": {alias: {} for alias in data["aliases"]}}
            for name, data in self._owner.indices.items()
            if fnmatch.fnmatch(name, index)
        }

    def create(self, index: str, settings: dict[str, Any], mappings: dict[str, Any]) -> dict[str, Any]:
        self._owner.calls.append(f"create {index}")
        assert index not in self._owner.indices
        self._owner.indices[index] = {
            "aliases": set(),
            "docs": {},
            "settings": settings,
            "mappings": mappings,
        }
        return {"acknowledged": True}

    def refresh(self, index: str) -> dict[str, Any]:
        self._owner.calls.append(f"refresh {index}")
        return {}

    def update_aliases(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        self._owner.calls.append("update_aliases")
        for action in actions:
            ((kind, target),) = action.items()
            aliases = self._owner.indices[target["index"]]["aliases"]
            if kind == "add":
                aliases.add(target["alias"])
            else:
                aliases.discard(target["alias"])
        return {"acknowledged": True}


class FakeSynonyms:
    def __init__(self, owner: FakeCluster) -> None:
        self._owner = owner

    def get_synonyms_sets(self, size: int) -> dict[str, Any]:
        sets = self._owner.synonym_sets
        return {
            "count": len(sets),
            "results": [{"synonyms_set": name, "count": len(r)} for name, r in sets.items()],
        }

    def put_synonym(self, id: str, synonyms_set: list[dict[str, str]]) -> dict[str, Any]:  # noqa: A002 - client API
        self._owner.calls.append(f"put_synonym {id}")
        self._owner.synonym_sets[id] = list(synonyms_set)
        return {"result": "created"}


class FakeCluster:
    def __init__(self) -> None:
        self.indices: dict[str, dict[str, Any]] = {}
        self.synonym_sets: dict[str, list[dict[str, str]]] = {}
        self.calls: list[str] = []
        self.refuse_ids: set[str] = set()
        self.lose_ids: set[str] = set()  # accepted but never counted, as if lost
        self.indices_api = FakeIndices(self)
        self.synonyms = FakeSynonyms(self)

    def bulk(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append("bulk")
        items, errors = [], False
        for action, document in zip(operations[::2], operations[1::2], strict=True):
            target = action["index"]
            if target["_id"] in self.refuse_ids:
                errors = True
                items.append(
                    {
                        "index": {
                            "_id": target["_id"],
                            "status": 400,
                            "error": {"type": "document_parsing_exception", "reason": "bad field"},
                        }
                    }
                )
                continue
            if target["_id"] not in self.lose_ids:
                self.indices[target["_index"]]["docs"][target["_id"]] = document
            items.append({"index": {"_id": target["_id"], "status": 201}})
        return {"errors": errors, "items": items}

    def count(self, index: str) -> dict[str, Any]:
        names = [name for name, data in self.indices.items() if name == index or index in data["aliases"]]
        return {"count": sum(len(self.indices[name]["docs"]) for name in names)}


@pytest.fixture
def cluster() -> FakeCluster:
    return FakeCluster()


class ClientView:
    """`client.indices` must be the API object; the cluster keeps the data in `.indices`."""

    def __init__(self, cluster: FakeCluster) -> None:
        self.cluster = cluster
        self.indices = cluster.indices_api
        self.synonyms = cluster.synonyms
        self.bulk = cluster.bulk
        self.count = cluster.count


@pytest.fixture
def client(cluster: FakeCluster) -> ClientView:
    return ClientView(cluster)


def products(count: int, start: int = 1) -> list[ProductValues]:
    return [
        ProductValues(template_id=i, name=f"Product {i}", qty_available=float(i % 3))
        for i in range(start, start + count)
    ]


def batches(items: list[ProductValues], size: int = 2) -> list[list[ProductValues]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# --- definition ---


def test_the_committed_definition_loads() -> None:
    definition = load_definition()
    assert definition.settings["number_of_replicas"] == 0
    assert definition.mappings["dynamic"] == "strict"
    assert definition.synonyms_seed == []  # chosen on dev queries in Tasks 3.5/3.6, not before
    analyzers = definition.settings["analysis"]["analyzer"]
    assert "shop_synonyms" in analyzers["shop_search"]["filter"]
    assert "shop_synonyms" not in analyzers["shop_index"]["filter"]  # synonyms at search time only


def test_every_document_field_is_mapped() -> None:
    mapped = set(load_definition().mappings["properties"])
    full = ProductValues(
        template_id=1,
        name="n",
        ref="r",
        description="d",
        brand="b",
        categories=[(1, "c")],
        updated_at=datetime(2026, 11, 20),
    )
    assert set(build_document(full)) == mapped


def _write_definition(folder: Path, settings: Any = None, mappings: Any = None, seed: Any = None) -> Path:
    base = load_definition()
    for name, value in (
        ("settings.json", settings or base.settings),
        ("mappings.json", mappings or base.mappings),
        ("synonyms-seed.json", base.synonyms_seed if seed is None else seed),
    ):
        (folder / name).write_text(json.dumps(value), encoding="utf-8")
    return folder


def test_definition_with_another_synonyms_set_is_refused(tmp_path: Path) -> None:
    settings = json.loads((DEFINITION_DIR / "settings.json").read_text(encoding="utf-8"))
    settings["analysis"]["filter"]["shop_synonyms"]["synonyms_set"] = "other"
    with pytest.raises(ValueError, match="synonyms set"):
        load_definition(_write_definition(tmp_path, settings=settings))


def test_definition_with_a_dynamic_mapping_is_refused(tmp_path: Path) -> None:
    mappings = dict(load_definition().mappings, dynamic=True)
    with pytest.raises(ValueError, match="strict"):
        load_definition(_write_definition(tmp_path, mappings=mappings))


def test_definition_with_a_malformed_seed_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="list of"):
        load_definition(_write_definition(tmp_path, seed=[{"synonyms": "a, b"}]))


# --- documents ---


def test_document_of_a_full_product() -> None:
    product = ProductValues(
        template_id=7,
        name=" Throttle cable ",
        ref="B000ABC",
        description="For mowers.\n",
        brand="Acme",
        categories=[(3, "Automotive"), (9, "Tools")],
        price=12.345,
        qty_available=4.0,
        published=True,
        website_id=1,
        updated_at=datetime(2026, 11, 20, 8, 30, 5),
    )
    assert build_document(product) == {
        "template_id": 7,
        "ref": "B000ABC",
        "name": "Throttle cable",
        "description": "For mowers.",
        "brand": "Acme",
        "categories": ["Automotive", "Tools"],
        "category_ids": [3, 9],
        "price": 12.35,
        "qty_available": 4.0,
        "in_stock": True,
        "published": True,
        "website_ids": [1],
        "updated_at": "2026-11-20T08:30:05Z",
    }


@pytest.mark.parametrize("quantity", [0.0, -2.0])
def test_document_of_a_bare_product(quantity: float) -> None:
    document = build_document(ProductValues(template_id=1, name="Mug", brand="  ", qty_available=quantity))
    assert document["in_stock"] is False
    assert document["website_ids"] == []  # on every website
    assert document["published"] is False
    assert not {"ref", "description", "brand", "updated_at"} & set(document)


def test_bulk_operations_use_the_template_id() -> None:
    operations = bulk_operations("shop-products-v2", [{"template_id": 5, "name": "a"}])
    assert operations == [
        {"index": {"_index": "shop-products-v2", "_id": "5"}},
        {"template_id": 5, "name": "a"},
    ]


def test_bulk_failures() -> None:
    assert bulk_failures({"errors": False, "items": [{"index": {"_id": "1", "status": 201}}]}) == []
    response = {
        "errors": True,
        "items": [
            {"index": {"_id": "1", "status": 201}},
            {
                "index": {
                    "_id": "2",
                    "status": 400,
                    "error": {"type": "mapper_parsing_exception", "reason": "bad"},
                }
            },
            {"index": {"_id": "3", "status": 429, "error": "rejected"}},
        ],
    }
    assert bulk_failures(response) == ["2: mapper_parsing_exception: bad", "3: error: rejected"]


# --- names and alias ---


def test_next_index() -> None:
    assert next_index([]) == "shop-products-v1"
    assert next_index(
        ["shop-products-v1", "shop-products-v3", "shop-products-v2-old", "shop-products-test-v9"]
    ) == ("shop-products-v4")
    assert next_index(
        ["shop-products-test-v9"], IndexNames("shop-products-test", "shop-products-test-v")
    ) == ("shop-products-test-v10")


def test_swap_actions_move_the_alias_in_one_call() -> None:
    assert alias_holders({"shop-products-v1": ["shop-products"], "shop-products-v2": []}) == [
        "shop-products-v1"
    ]
    assert swap_actions("shop-products-v2", ["shop-products-v1"]) == [
        {"remove": {"index": "shop-products-v1", "alias": "shop-products"}},
        {"add": {"index": "shop-products-v2", "alias": "shop-products"}},
    ]
    assert swap_actions("shop-products-v1", []) == [
        {"add": {"index": "shop-products-v1", "alias": "shop-products"}}
    ]


# --- rebuild ---


def test_first_rebuild(client: ClientView, cluster: FakeCluster) -> None:
    ticks = iter([10.0, 25.0])
    sent: list[int] = []
    result = rebuild(
        client,
        load_definition(),
        batches(products(5)),
        expected=5,
        clock=lambda: next(ticks),
        progress=sent.append,
    )

    assert (result.index, result.previous, result.documents, result.seconds) == (
        "shop-products-v1",
        (),
        5,
        15.0,
    )
    assert result.synonyms_created
    assert cluster.synonym_sets == {SYNONYMS_SET: []}
    assert cluster.indices["shop-products-v1"]["aliases"] == {"shop-products"}
    assert sent == [2, 4, 5]
    # The synonyms set exists before the index that refers to it.
    assert cluster.calls.index(f"put_synonym {SYNONYMS_SET}") < cluster.calls.index("create shop-products-v1")
    assert "5 products indexed into shop-products-v1" in result.summary()


def test_second_rebuild_moves_the_alias_and_keeps_the_old_index(
    client: ClientView, cluster: FakeCluster
) -> None:
    rebuild(client, load_definition(), batches(products(3)), expected=3)
    cluster.synonym_sets[SYNONYMS_SET] = [
        {"id": "r1", "synonyms": "sneakers, trainers"}
    ]  # managed in Odoo later

    result = rebuild(client, load_definition(), batches(products(4)), expected=4)

    assert (result.index, result.previous, result.synonyms_created) == (
        "shop-products-v2",
        ("shop-products-v1",),
        False,
    )
    assert cluster.indices["shop-products-v1"]["aliases"] == set()
    assert cluster.indices["shop-products-v2"]["aliases"] == {"shop-products"}
    assert cluster.synonym_sets[SYNONYMS_SET] == [
        {"id": "r1", "synonyms": "sneakers, trainers"}
    ]  # not overwritten
    assert read_status(client) == IndexStatus(("shop-products-v2",), 4)


def test_refused_documents_leave_the_alias(client: ClientView, cluster: FakeCluster) -> None:
    rebuild(client, load_definition(), batches(products(3)), expected=3)
    cluster.refuse_ids = {"2"}

    with pytest.raises(
        RebuildError, match=r"refused 1 products in shop-products-v2 \(first: 2: document_parsing"
    ):
        rebuild(client, load_definition(), batches(products(3)), expected=3)

    assert cluster.indices["shop-products-v1"]["aliases"] == {"shop-products"}
    assert "update_aliases" not in cluster.calls[cluster.calls.index("create shop-products-v2") :]


@pytest.mark.parametrize(("lost", "expected"), [({"3"}, 3), (set(), 4)])
def test_a_count_mismatch_leaves_the_alias(
    client: ClientView, cluster: FakeCluster, lost: set[str], expected: int
) -> None:
    rebuild(client, load_definition(), batches(products(3)), expected=3)
    cluster.lose_ids = lost

    with pytest.raises(RebuildError, match="was not moved"):
        rebuild(client, load_definition(), batches(products(3)), expected=expected)

    assert cluster.indices["shop-products-v1"]["aliases"] == {"shop-products"}
    assert read_status(client).indices == ("shop-products-v1",)


def test_a_separate_alias_never_touches_the_shop_alias(client: ClientView, cluster: FakeCluster) -> None:
    rebuild(client, load_definition(), batches(products(2)), expected=2)
    names = IndexNames("shop-products-test", "shop-products-test-v")

    result = rebuild(client, load_definition(), batches(products(1)), expected=1, names=names)

    assert result.index == "shop-products-test-v1"
    assert read_status(client) == IndexStatus(("shop-products-v1",), 2)
    assert read_status(client, names) == IndexStatus(("shop-products-test-v1",), 1)


def test_status_without_an_index(client: ClientView) -> None:
    assert read_status(client) == IndexStatus()
    assert not IndexStatus().exists


# --- through EsClient (timeout, errors) ---


class Unreachable(Exception):
    pass


class DownClient:
    def options(self, request_timeout: float) -> DownClient:
        return self

    @property
    def indices(self) -> Any:
        raise Unreachable("Connection refused")


CONFIG = EsConfig(
    url="http://elasticsearch:9200",
    username="odoo_app",
    password="fake-value",  # pragma: allowlist secret
)


def test_index_status_through_the_service(client: ClientView, cluster: FakeCluster) -> None:
    class Options(ClientView):
        def options(self, request_timeout: float) -> Options:
            return self

    rebuild(client, load_definition(), batches(products(2)), expected=2)
    service = EsClient(CONFIG, client=Options(cluster), errors=(Unreachable,))
    assert service.product_index_status() == IndexStatus(("shop-products-v1",), 2)
    assert PRODUCTS.alias == "shop-products"


def test_index_status_when_elasticsearch_is_down() -> None:
    service = EsClient(CONFIG, client=DownClient(), errors=(Unreachable,))
    status = service.product_index_status()
    assert not status.exists
    assert status.error == "Unreachable: Connection refused"
