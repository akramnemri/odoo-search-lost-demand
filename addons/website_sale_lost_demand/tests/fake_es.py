"""Fake Elasticsearch service for the Odoo unit tests: same interface as services.es_client.EsService."""

from ..services.es_client import ClusterStatus
from ..services.product_index import IndexStatus

HEALTHY = ClusterStatus(
    reachable=True,
    version="9.5.5",
    license_type="basic",
    license_status="active",
    health="green",
    breaker="closed",
    checked_at=1_762_400_000.0,
)
DOWN = ClusterStatus(
    reachable=False,
    breaker="open",
    error="ConnectionError: Connection error caused by: name resolution failed",
    checked_at=1_762_400_000.0,
)


class FakeEsError(Exception):
    """Stands for the client's ApiError/TransportError (`status_code` like ApiError's)."""

    def __init__(self, message="", status_code=None):
        super().__init__(message)
        self.status_code = status_code


class _Indices:
    def __init__(self, cluster):
        self._cluster = cluster

    def get_alias(self, index):
        self._cluster.check()
        if not self._cluster.index:
            return {}
        return {self._cluster.index: {"aliases": {self._cluster.alias: {}}}}

    def get_mapping(self, index):
        self._cluster.check()
        meta = {"definition_version": self._cluster.version} if self._cluster.version else {}
        return {self._cluster.index: {"mappings": {"_meta": meta}}}


class _Synonyms:
    """Synonyms sets by name (Task 3.6): a missing set answers 404, like Elasticsearch."""

    def __init__(self, cluster):
        self._cluster = cluster
        self.sets = {}
        self.puts = []

    def get_synonym(self, id, size):
        self._cluster.check()
        if id not in self.sets:
            raise FakeEsError("resource_not_found_exception", status_code=404)
        return {"count": len(self.sets[id]), "synonyms_set": list(self.sets[id])}

    def put_synonym(self, id, synonyms_set):
        self._cluster.check()
        self.puts.append((id, list(synonyms_set)))
        self.sets[id] = list(synonyms_set)
        return {"result": "updated"}


class FakeCluster:
    """An index behind an alias that keeps documents in a dict; `down=True` makes every call fail;
    `refuse` maps a template ID to the error Elasticsearch gives for its item."""

    def __init__(self, version, alias="shop-products", index="shop-products-v9"):
        self.alias, self.index, self.version = alias, index, version
        self.documents = {}
        self.down = False
        self.refuse = {}
        self.bulk_calls = []
        self.indices = _Indices(self)
        self.synonyms = _Synonyms(self)

    def check(self):
        if self.down:
            raise FakeEsError("ConnectionError: connection refused")

    def bulk(self, operations, require_alias=False):
        self.check()
        assert require_alias, "the sync must write through the alias only"
        self.bulk_calls.append(operations)
        items, errors = [], False
        pairs = iter(operations)
        for action in pairs:
            ((kind, meta),) = action.items()
            assert meta["_index"] == self.alias
            doc_id = meta["_id"]
            source = next(pairs) if kind == "index" else None
            if int(doc_id) in self.refuse:
                errors = True
                items.append(
                    {
                        kind: {
                            "_id": doc_id,
                            "status": 400,
                            "error": {
                                "type": "document_parsing_exception",
                                "reason": self.refuse[int(doc_id)],
                            },
                        }
                    }
                )
            elif kind == "index":
                self.documents[doc_id] = source
                items.append({kind: {"_id": doc_id, "status": 200}})
            else:
                found = self.documents.pop(doc_id, None) is not None
                items.append(
                    {
                        kind: {
                            "_id": doc_id,
                            "status": 200 if found else 404,
                            "result": "deleted" if found else "not_found",
                        }
                    }
                )
        return {"errors": errors, "items": items}


class FakeEsService:
    """Answers with a fixed status and counts the calls; no network. `cluster` serves `admin_call`."""

    def __init__(
        self, status: ClusterStatus = HEALTHY, index: IndexStatus | None = None, cluster=None
    ) -> None:
        self.status = status
        self.index = index or IndexStatus()
        self.cluster = cluster
        self.calls = 0

    def cluster_status(self, refresh: bool = False) -> ClusterStatus:
        self.calls += 1
        return self.status

    def product_index_status(self) -> IndexStatus:
        return self.index

    def admin_call(self, operation, timeout=None):
        if self.cluster is None:
            raise FakeEsError("no fake cluster")
        return operation(self.cluster)

    def client_errors(self):
        return (FakeEsError,)


class FakeSearchClient:
    """Low-level client for a real `EsClient` in shop search tests: answers `search` with `ranked` template
    IDs (whatever the query), or fails (`down`), or hangs until `release` is set (`hang`). IDs in `sold_out`
    carry `in_stock: false` when the query asks for the stock flag (engine es_tuned_stock)."""

    def __init__(self, ranked=()):
        self.ranked = list(ranked)
        self.sold_out = set()
        self.down = False
        self.hang = None  # a threading.Event to make calls hang
        self.requests = []

    def options(self, request_timeout):
        return self

    def search(self, index, body):
        self.requests.append({"index": index, **body})
        if self.hang is not None:
            self.hang.wait(timeout=10)
        if self.down:
            raise FakeEsError("ConnectionError: connection refused")
        hits = []
        for template_id in self.ranked:
            hit = {"_id": str(template_id)}
            if "docvalue_fields" in body:
                hit["fields"] = {"in_stock": [template_id not in self.sold_out]}
            hits.append(hit)
        return {"took": 3, "hits": {"hits": hits}}
