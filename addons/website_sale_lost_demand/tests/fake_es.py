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
    """Stands for the client's ApiError/TransportError."""


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
