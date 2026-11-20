"""Shop search through Elasticsearch, with Odoo's own search as the fallback (Task 3.3, FR1-FR3).

Odoo 19.0 source (`.odoo-src/odoo/addons`), read before overriding:

- website_sale/controllers/main.py, `WebsiteSale.shop()` (l.285): calls `_shop_lookup_products()` (l.370) for
  the products and their count, then `_get_shop_domain()` (l.375) for the price range (l.383), the category
  list (l.426) and the attribute filters (l.478); the pager slices the products in their order (l.467).
- `WebsiteSale._shop_lookup_products()` (l.239): `website._search_with_fuzzy("products_only", ...)`
  (website/models/website.py l.2052) = `product.template._search_get_detail()` (website_sale/models/
  product_template.py l.873: published, website, company, category, tags, price, attributes) AND every
  word `ilike` the name, reference or descriptions, in the shop's sort order, plus a similar-word retry.
- `WebsiteSale._get_shop_domain()` (l.158): the same filters without tags and price, with the words.

What we change, only when there is a search text and the engine is an Elasticsearch one:

1. Elasticsearch ranks the products (services/shop_search.py, at most `search_max_hits`).
2. Odoo keeps only the ranked products that its own base domain of `_search_get_detail()` allows, as the
   shopper (same access rules as the native search), and keeps Elasticsearch's order — or sorts them with the
   shop's order when the shopper picked one in the sort menu.
3. `_get_shop_domain()` matches "the products Elasticsearch found" instead of the words, so categories,
   attributes and the price range describe the products shown.

On any Elasticsearch problem (error, timeout, open circuit, missing settings, odd answer) `super()` runs:
the shopper gets Odoo's native results and never an error page. `EsClient.guarded()` logs a warning once
per breaker opening; single fallbacks are logged at debug level, without the query text.
"""

import logging
import os

from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.fields import Domain
from odoo.http import request

from ..services.config import ConfigError, load_test_key
from ..services.es_client import EsService, EsUnavailable, shared_service
from ..services.product_index import PRODUCTS
from ..services.query_builder import ODOO, MalformedResponse, SearchFilters, clean_query
from ..services.shop_search import (
    ENGINE_USED_HEADER,
    ODOO_FALLBACK,
    SearchOutcome,
    choose_engine,
    search_template_ids,
)

_logger = logging.getLogger(__name__)
# Attribute of the current `odoo.http.request` holding this request's SearchOutcome (one request, one search).
OUTCOME_ATTRIBUTE = "lost_demand_search"


def es_service() -> EsService:
    """The process-wide Elasticsearch service; tests patch this function."""
    return shared_service()


def search_alias() -> str:
    """The product alias shop searches read; tests patch it to use their own index."""
    return PRODUCTS.alias


def search_outcome() -> SearchOutcome | None:
    """This request's search outcome, if the shop lookup ran."""
    return getattr(request, OUTCOME_ATTRIBUTE, None)


class WebsiteSaleLostDemand(WebsiteSale):
    def _shop_lookup_products(self, options, post, search, website):
        choice = choose_engine(request.httprequest.headers, load_test_key(os.environ))
        text = clean_query(search)
        if not text or choice.engine == ODOO:
            # No search text (category browsing) or the evaluation asked for Odoo: the native lookup.
            return self._lost_demand_native(choice, search, ODOO, "", options, post, website)
        try:
            service = es_service()
            filters = SearchFilters(website_id=website.id, category_ids=self._lost_demand_categories(options))
            hits = search_template_ids(
                service, search_alias(), choice.engine, text, filters, service.config.search_max_hits
            )
        except (EsUnavailable, ConfigError, MalformedResponse) as error:
            _logger.debug("shop search answered by Odoo: %s", error)
            return self._lost_demand_native(
                choice, search, ODOO_FALLBACK, type(error).__name__, options, post, website
            )
        products = self._lost_demand_products(hits.ids, options, post, website)
        self._lost_demand_record(choice, SearchOutcome(search, choice.engine, hits.ids, hits.took_ms))
        _logger.debug(
            "shop search: engine %s, %d hits, %d shown, took %s ms",
            choice.engine,
            len(hits.ids),
            len(products),
            hits.took_ms,
        )
        # No similar-word term: Elasticsearch's answer is final, typo tolerance is part of the query.
        return False, len(products), products

    def _get_shop_domain(self, search, category, attribute_value_dict, search_in_description=True):
        outcome = search_outcome()
        if outcome is None or not outcome.served_by_elasticsearch or search != outcome.search:
            return super()._get_shop_domain(search, category, attribute_value_dict, search_in_description)
        # Odoo's domain without the words (sale_product_domain, category, attributes), limited to the
        # products Elasticsearch found: what `shop()` derives from it then describes the products shown.
        without_words = super()._get_shop_domain("", category, attribute_value_dict, search_in_description)
        return without_words & Domain("id", "in", list(outcome.hit_ids))

    # --- helpers (prefixed: never collide with an Odoo method) ---

    def _lost_demand_native(self, choice, search, engine, reason, options, post, website):
        self._lost_demand_record(choice, SearchOutcome(search, engine, reason=reason))
        return super()._shop_lookup_products(options, post, search, website)

    def _lost_demand_record(self, choice, outcome):
        setattr(request, OUTCOME_ATTRIBUTE, outcome)
        if choice.trusted:
            request.future_response.headers[ENGINE_USED_HEADER] = outcome.engine

    def _lost_demand_categories(self, options):
        """The selected category and its subcategories, for Elasticsearch's filter.

        sudo: only narrows Elasticsearch's candidates the way Odoo's `child_of` filter will (a superset at
        worst); Odoo's own domain decides what the shopper may see.
        """
        try:
            category_id = int(options.get("category") or 0)
        except (TypeError, ValueError):
            return ()
        if not category_id:
            return ()
        categories = request.env["product.public.category"].sudo().search([("id", "child_of", category_id)])
        return tuple(categories.ids)

    def _lost_demand_products(self, ranked_ids, options, post, website):
        """The ranked products Odoo's shop filters allow, in Elasticsearch's order (or the chosen sort)."""
        Product = request.env["product.template"].with_context(bin_size=True)
        if not ranked_ids:
            return Product
        order = self._get_search_order(post)
        detail = Product._search_get_detail(website, order, options)
        domain = Domain.AND(detail["base_domain"]) & Domain("id", "in", list(ranked_ids))
        if post.get("order"):
            # The shopper picked a sort (price, name, newest...): Odoo's order over Elasticsearch's hits.
            return Product.search(domain, order=order)
        allowed = Product.search(domain)
        rank = {template_id: position for position, template_id in enumerate(ranked_ids)}
        return allowed.sorted(key=lambda product: rank[product.id])
