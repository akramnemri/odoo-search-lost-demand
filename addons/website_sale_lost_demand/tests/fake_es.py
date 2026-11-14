"""Fake Elasticsearch service for the Odoo unit tests: same interface as services.es_client.EsService."""

from ..services.es_client import ClusterStatus

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


class FakeEsService:
    """Answers with a fixed status and counts the calls; no network."""

    def __init__(self, status: ClusterStatus = HEALTHY) -> None:
        self.status = status
        self.calls = 0

    def cluster_status(self, refresh: bool = False) -> ClusterStatus:
        self.calls += 1
        return self.status
