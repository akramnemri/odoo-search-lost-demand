"""Search synonyms managed in Odoo (Task 3.6, FR2; docs/ai/01_ARCHITECTURE.md §6.3).

Odoo is the source of truth; Elasticsearch's synonyms set is a copy (services/synonyms.py). Saving a rule
never calls Elasticsearch: it is validated here, then a pre-commit callback asks the product sync job to run
at once (`ir.cron._trigger`, the job of Task 3.2), and the job pushes the whole set when it differs from the
rules. If Elasticsearch is down, the job tries again every minute; a lost set is repaired the same way.
Administrators (Settings group) manage the rules (security/ir.model.access.csv).
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..services.config import ConfigError
from ..services.es_client import DeadlineExceeded, describe_error
from ..services.product_index import PRODUCTS, IndexNames
from ..services.synonyms import EQUIVALENT, ONE_WAY, InvalidRule, desired_set, parse_rule, sync_set
from . import res_config_settings
from .index_queue import CRON_XMLID

_logger = logging.getLogger(__name__)
SYNC_REQUEST_KEY = "lost_demand.synonyms.sync_requested"
SYNC_TIMEOUT_SECONDS = 30
STATE_PARAM = res_config_settings.SYNONYMS_STATE_PARAM  # last outcome, shown in Settings


class LostDemandSynonym(models.Model):
    _name = "lost_demand.synonym"
    _description = "Search synonym rule"
    _order = "id"

    terms = fields.Char(
        string="Words",
        required=True,
        help="Comma-separated. Same meaning: every word finds the others (sofa, couch). One-way: the words "
        "shoppers type (they keep their own meaning).",
    )
    rule_type = fields.Selection(
        [(EQUIVALENT, "Same meaning"), (ONE_WAY, "One-way")],
        string="Type",
        required=True,
        default=EQUIVALENT,
    )
    targets = fields.Char(
        string="Also search for",
        help="One-way rules only, comma-separated: what a search for the words also finds (hoodie → hooded "
        "sweatshirt).",
    )
    active = fields.Boolean(default=True)
    note = fields.Char(help="Why this rule exists, for the next administrator.")
    search_line = fields.Char(
        string="Sent to search",
        compute="_compute_search_line",
        help="Exactly what Elasticsearch receives: each word with its simple singular or plural form.",
    )

    @api.depends("terms", "targets", "rule_type")
    def _compute_search_line(self):
        for record in self:
            try:
                record.search_line = parse_rule(record.rule_type, record.terms, record.targets).line()
            except InvalidRule:
                record.search_line = False

    @api.constrains("terms", "targets", "rule_type")
    def _check_rule(self):
        for record in self:
            try:
                parse_rule(record.rule_type, record.terms, record.targets)
            except InvalidRule as error:
                raise ValidationError(str(error)) from error

    # --- every change asks for a sync ---

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._request_sync()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._request_sync()
        return result

    def unlink(self):
        result = super().unlink()
        self._request_sync()
        return result

    @api.model
    def _request_sync(self):
        """Ask the sync job to run after this transaction commits (never in a rolled-back one)."""
        precommit = self.env.cr.precommit
        if not precommit.data.get(SYNC_REQUEST_KEY):
            precommit.data[SYNC_REQUEST_KEY] = True
            precommit.add(self._trigger_sync_job)

    @api.model
    def _trigger_sync_job(self):
        self.env.cr.precommit.data.pop(SYNC_REQUEST_KEY, None)
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)  # missing while the module installs
        if cron:
            cron.sudo()._trigger()

    # --- the sync, run by the product sync job ---

    @api.model
    def _desired_set(self):
        rules = self.sudo().with_context(active_test=True).search([])
        return desired_set((rule.id, parse_rule(rule.rule_type, rule.terms, rule.targets)) for rule in rules)

    @api.model
    def _sync_to_search(self, names: IndexNames = PRODUCTS) -> str:
        """Make Elasticsearch's set equal to the active rules. Never raises (the caller is a scheduled job);
        returns and stores a short state for the settings page."""
        try:
            service = res_config_settings.get_es_service()
        except ConfigError as error:
            return self._store_state(f"error: Elasticsearch is not configured ({error})")
        desired = self._desired_set()
        errors = (*service.client_errors(), DeadlineExceeded)
        try:
            result = service.admin_call(
                lambda client: sync_set(client, names.synonyms_set, desired, service.client_errors()),
                SYNC_TIMEOUT_SECONDS,
            )
        except errors as error:
            _logger.warning("Synonyms not sent: %s", describe_error(error))
            return self._store_state(f"error: {describe_error(error)}")
        if result.pushed:
            _logger.info("Synonyms sent: %s rules in %s", result.rules, names.synonyms_set)
        return self._store_state(f"in sync: {result.rules} rules")

    @api.model
    def _store_state(self, state: str) -> str:
        params = self.env["ir.config_parameter"].sudo()
        if params.get_param(STATE_PARAM) != state:  # no write (and no database churn) every minute
            params.set_param(STATE_PARAM, state)
        return state
