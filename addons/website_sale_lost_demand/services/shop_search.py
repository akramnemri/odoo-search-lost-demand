"""One shop search through Elasticsearch, and the evaluation switch that picks its engine (Task 3.3).

Pure Python except for the client call, which goes through `EsClient.guarded()` (timeout, circuit breaker):
any failure there raises `EsUnavailable`, and an answer of the wrong shape raises `MalformedResponse`.
The controller (controllers/main.py) answers both with Odoo's native search.

Evaluation switch (docs/ai/01_ARCHITECTURE.md §7, docs/ai/02_CODING_STANDARDS.md §11): a request may choose
its engine with the `X-Lost-Demand-Engine` header only when it also sends `X-Lost-Demand-Key` equal to the
load-test key of the environment. Without a configured key, or with a wrong one, the header is ignored and
the shopper's default engine is used. Only a request with the right key learns which engine answered
(`X-Lost-Demand-Engine-Used`): the evaluation needs it to notice a fallback; shoppers do not.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .query_builder import DEFAULT_ENGINE, ENGINES, ES_ENGINES, SearchFilters, build_search, hit_ids

KEY_HEADER = "X-Lost-Demand-Key"
ENGINE_HEADER = "X-Lost-Demand-Engine"
ENGINE_USED_HEADER = "X-Lost-Demand-Engine-Used"
ODOO_FALLBACK = "odoo_fallback"  # the engine name events will carry (M4) when Elasticsearch failed


@dataclass(frozen=True)
class EngineChoice:
    engine: str
    trusted: bool  # the request carried the right load-test key


def _same_secret(sent: str, expected: str) -> bool:
    # Constant-time comparison: the time taken does not tell how many characters were right.
    return hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8"))


def choose_engine(headers: Mapping[str, str], load_test_key: str) -> EngineChoice:
    """The engine of one shop request. `load_test_key` is "" when the switch is disabled."""
    sent = (headers.get(KEY_HEADER) or "").strip()
    trusted = bool(load_test_key and sent) and _same_secret(sent, load_test_key)
    wanted = (headers.get(ENGINE_HEADER) or "").strip()
    if trusted and wanted in ENGINES:
        return EngineChoice(wanted, trusted=True)
    return EngineChoice(DEFAULT_ENGINE, trusted=trusted)


@dataclass(frozen=True)
class SearchOutcome:
    """What answered one shop search; kept on the request for the shop page (and for search events, M4)."""

    search: str  # the search text as the shop lookup received it
    engine: str  # an Elasticsearch engine, "odoo" (chosen by the switch) or "odoo_fallback"
    hit_ids: tuple[int, ...] = ()  # Elasticsearch's ranked template IDs, before Odoo's filters
    took_ms: int | None = None  # Elasticsearch's own time for the search
    reason: str = ""  # why Odoo answered instead (short, never the query text)

    @property
    def served_by_elasticsearch(self) -> bool:
        return self.engine in ES_ENGINES


@dataclass(frozen=True)
class SearchHits:
    ids: tuple[int, ...]
    took_ms: int | None


def search_template_ids(
    service: Any, alias: str, engine: str, text: str, filters: SearchFilters, size: int
) -> SearchHits:
    """Ranked template IDs for `text` (already cleaned). Raises EsUnavailable or MalformedResponse."""
    body = build_search(engine, text, filters, size)

    def run(client: Any) -> Mapping[str, Any]:
        # Runs in a worker thread: only the client may be used here (es_client module docstring).
        response = client.search(index=alias, body=body)
        answer = getattr(response, "body", response)  # ObjectApiResponse in production, a dict in tests
        return answer if isinstance(answer, Mapping) else {}

    response = service.guarded(run)
    took = response.get("took")
    return SearchHits(ids=tuple(hit_ids(response)), took_ms=took if isinstance(took, int) else None)
