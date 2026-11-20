"""Product index outbox and its flush job (Task 3.2, FR1: a product change is searchable within 60 s).

How a change travels (docs/ai/01_ARCHITECTURE.md §8):
1. a hook (models/product_template.py, models/stock_quant.py) calls `_enqueue(template_ids)` while Odoo
   changes a product; the IDs are gathered per transaction and written as outbox rows by a pre-commit
   callback, so a row exists if and only if the change is committed (same transaction, no lost change);
2. the same callback asks for an immediate run of the flush job (`ir.cron._trigger`,
   odoo/addons/base/models/ir_cron.py: a trigger row, then a NOTIFY after the commit wakes a cron worker);
3. the job (`_cron_send_to_index`) reads the rows, merges them per product, reads the products as they are
   now, sends one bulk request per 500 products, and deletes the rows that went through. The job also runs
   every minute without a trigger: it retries what failed and catches up after an outage.

Rules that keep the shop safe (CLAUDE.md, §13): the hooks only add IDs to a set, never call Elasticsearch,
never raise; the job never raises for an Elasticsearch problem (Odoo deactivates a cron job that keeps
failing: `_update_failure_count`, 5 failures over 7 days), it logs and leaves the rows waiting. A
rebuild and the job never run together (PostgreSQL advisory lock, see `REBUILD_LOCK`).
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import SQL, split_every

from ..services.config import ConfigError
from ..services.es_client import DeadlineExceeded, describe_error
from ..services.index_sync import FAILING_AFTER_ATTEMPTS, index_not_ready, retry_delay, send_changes
from ..services.product_index import PRODUCTS, IndexNames, build_document, load_definition
from . import res_config_settings

_logger = logging.getLogger(__name__)

CRON_XMLID = "website_sale_lost_demand.ir_cron_product_index_sync"
PENDING_KEY = (
    "website_sale_lost_demand.index_queue"  # cr.precommit.data key: template IDs of this transaction
)
# PostgreSQL advisory lock shared by the flush job and the full rebuild ("LD" + 3.2). Transaction-level:
# released at commit or rollback, never left behind by a crashed worker.
REBUILD_LOCK = 0x4C44_0302
BATCH_SIZE = 500  # products per bulk request, as the rebuild
ROWS_PER_READ = 5000  # outbox rows read at once; a batch merges them per product
SYNC_TIMEOUT_SECONDS = 30.0  # hard deadline of one Elasticsearch call of the job
TIME_BUDGET_SECONDS = 50.0  # then the job stops and asks to run again (Odoo's "partially done")


@dataclass
class FlushResult:
    """What one run did; also what the tests and `shop` tools read."""

    sent: int = 0  # products whose document was written or deleted
    failed: int = 0  # products Elasticsearch refused (retried later)
    waiting: str = ""  # why nothing was sent (index not ready, rebuild running, outage)
    errors: list[str] = field(default_factory=list)


class LostDemandIndexQueue(models.Model):
    _name = "lost_demand.index.queue"
    _description = "Product index outbox"
    _order = "id"
    _log_access = False  # rows live seconds; enqueued_at says when, the user does not matter

    template_id = fields.Integer(
        string="Product template ID",
        required=True,
        index=True,
        help="A plain number, not a link: the row must outlive a deleted product, whose document is removed.",
    )
    enqueued_at = fields.Datetime(string="Enqueued at", required=True, default=fields.Datetime.now)
    next_attempt_at = fields.Datetime(
        string="Next attempt at", required=True, default=fields.Datetime.now, index=True
    )
    attempts = fields.Integer(string="Refusals", default=0, help="How many times Elasticsearch refused it.")
    last_error = fields.Char(string="Last error")

    # --- writing side: called from hooks, inside a shopper's or a manager's transaction ---

    @api.model
    def _enqueue(self, template_ids):
        """Remember `template_ids` for this transaction; rows are written just before it commits."""
        ids = {int(template_id) for template_id in template_ids if template_id}
        if not ids:
            return
        precommit = self.env.cr.precommit
        pending = precommit.data.get(PENDING_KEY)
        if pending is None:
            pending = precommit.data[PENDING_KEY] = set()
            precommit.add(self._write_pending)
        pending.update(ids)

    def _write_pending(self):
        """Pre-commit callback: one row per changed product of the transaction, then a cron trigger."""
        ids = self.env.cr.precommit.data.pop(PENDING_KEY, set())
        if not ids:
            return
        self.sudo().create([{"template_id": template_id} for template_id in sorted(ids)])
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)  # missing while the module installs
        if cron:
            cron.sudo()._trigger()

    # --- reading side: the flush job ---

    @api.model
    def _cron_send_to_index(self):
        """Scheduled action (every minute, and on trigger). Commits after each batch."""
        result = self._send_to_index(commit=True)
        if result.sent or result.failed:
            _logger.info("Product index sync: %s sent, %s refused", result.sent, result.failed)

    @api.model
    def _try_lock(self):
        self.env.cr.execute(SQL("SELECT pg_try_advisory_xact_lock(%s)", REBUILD_LOCK))
        return self.env.cr.fetchone()[0]

    @api.model
    def _send_to_index(
        self, commit=False, names: IndexNames = PRODUCTS, budget=TIME_BUDGET_SECONDS
    ) -> FlushResult:
        """Send waiting changes. `commit=False` (tests, shell) keeps everything in the caller's transaction.

        Not called `_flush`: that is the ORM's own method on every model (pending writes to SQL).
        """
        result = FlushResult()
        started = time.monotonic()
        try:
            service = res_config_settings.get_es_service()
        except ConfigError as error:
            result.waiting = f"Elasticsearch is not configured: {error}"
            return result
        errors = (*service.client_errors(), DeadlineExceeded)
        definition = load_definition()
        try:
            result.waiting = service.admin_call(
                lambda client: index_not_ready(client, definition, names), SYNC_TIMEOUT_SECONDS
            )
        except errors as error:
            result.waiting = f"Elasticsearch unreachable: {describe_error(error)}"
        if result.waiting:
            _logger.info("Product index sync waits: %s", result.waiting)
            return result

        while time.monotonic() - started < budget:
            if not self._try_lock():  # taken again after every commit: a rebuild may have started
                result.waiting = "a product index rebuild is running"
                break
            rows = self._due_rows()
            if not rows:
                break
            by_template = defaultdict(list)
            for row_id, template_id in rows:
                by_template[template_id].append(row_id)
            for chunk in split_every(BATCH_SIZE, list(by_template)):
                documents, deletions = self._changes(chunk)
                try:
                    outcome = service.admin_call(
                        lambda client, d=documents, x=deletions: send_changes(client, d, x, names),
                        SYNC_TIMEOUT_SECONDS,
                    )
                except errors as error:
                    # The request failed as a whole: every row waits for the next run, unchanged.
                    result.waiting = f"Elasticsearch unreachable: {describe_error(error)}"
                    _logger.warning("Product index sync stopped: %s", result.waiting)
                    return result
                self._settle(outcome, {t: by_template[t] for t in chunk})
                result.sent += len(outcome.done)
                result.failed += len(outcome.failed)
                result.errors.extend(f"{t}: {e}" for t, e in sorted(outcome.failed.items())[:3])
                if commit:
                    self.env["ir.cron"]._commit_progress(len(chunk))
                else:
                    self.env.flush_all()
                if time.monotonic() - started >= budget:
                    break
        if commit and self._due_rows(limit=1):
            # Out of time with work left: Odoo runs the job again as soon as possible.
            self.env["ir.cron"]._commit_progress(remaining=1)
        return result

    @api.model
    def _due_rows(self, limit=ROWS_PER_READ):
        """(row ID, template ID) of rows due now, oldest first; rows another flush holds are skipped."""
        self.flush_model(["next_attempt_at"])
        self.env.cr.execute(
            SQL(
                "SELECT id, template_id FROM lost_demand_index_queue WHERE next_attempt_at <= %s "
                "ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED",
                fields.Datetime.now(),
                limit,
            )
        )
        return self.env.cr.fetchall()

    @api.model
    def _changes(self, template_ids):
        """Documents of the products still indexed, and the IDs of those whose document must go."""
        index = self.env["lost_demand.product.index"]
        indexed = index._templates().search(index._indexable_domain() + [("id", "in", list(template_ids))])
        documents = [build_document(values) for values in index._product_values(indexed)]
        deletions = sorted(set(template_ids) - set(indexed.ids))
        return documents, deletions

    @api.model
    def _settle(self, outcome, rows_by_template):
        """Delete the rows the index now reflects; give refused rows a later retry."""
        if outcome.done:
            # Older rows of the same products (waiting for a retry) are covered by this send as well. Rows
            # written after this run read the products are newer: kept for the next run.
            newest = max(row for t in outcome.done for row in rows_by_template[t])
            self.search([("template_id", "in", sorted(outcome.done)), ("id", "<=", newest)]).unlink()
        now = fields.Datetime.now()
        for template_id, error in outcome.failed.items():
            for row in self.browse(rows_by_template[template_id]):
                attempts = row.attempts + 1
                row.write(
                    {
                        "attempts": attempts,
                        "next_attempt_at": now + timedelta(seconds=retry_delay(attempts)),
                        "last_error": error[:500],
                    }
                )

    # --- after a full rebuild, and the backlog shown to administrators ---

    @api.model
    def _after_rebuild(self):
        """Rows that waited during the rebuild (or for a missing index) are due now: retry them at once."""
        waiting = self.sudo().search([("next_attempt_at", ">", fields.Datetime.now())])
        waiting.write({"next_attempt_at": fields.Datetime.now(), "attempts": 0})
        if self.sudo().search_count([], limit=1):
            cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()

    @api.model
    def _backlog(self):
        """(waiting rows, products failing, oldest enqueued_at or False) for the settings page."""
        queue = self.sudo()
        oldest = queue.search([], order="enqueued_at", limit=1).enqueued_at
        failing = queue.search([("attempts", ">=", FAILING_AFTER_ATTEMPTS)])
        return queue.search_count([]), len(set(failing.mapped("template_id"))), oldest
