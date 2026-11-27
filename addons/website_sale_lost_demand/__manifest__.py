{
    "name": "Lost-Demand Search",
    "summary": "Elasticsearch shop search with fallback, and restocking from lost demand",
    "description": """
School project (ERP + Big Data). Shop search runs on Elasticsearch (free Basic license) with a
fallback to Odoo's own search; searches, clicks, carts and purchases become restocking decisions.

Task 1.3 (skeleton): Elasticsearch connection settings from the environment, read-only cluster status in
Website settings, circuit breaker, security group.
Task 2.4a: product brand (filled by the catalog importer).
Task 3.1: product index in Elasticsearch (definition in elastic/products/), full rebuild with an alias swap,
index status and rebuild button in Website settings.
Task 3.2: incremental sync within 60 s: product, variant, category and stock changes go to an outbox in
the same transaction; a cron job (triggered at once) sends them in bulk, with retries; backlog in settings.
Task 3.3: shop search through Elasticsearch (engines es_plain, es_tuned, es_tuned_stock): Elasticsearch ranks,
Odoo filters with its own rules and keeps the order; any Elasticsearch problem falls back to Odoo's search.
Task 3.6: search synonyms managed in Odoo (Website > Configuration > Search synonyms), sent to
Elasticsearch's synonyms set by the sync job; typed words rank before synonym-only matches.
""",
    "version": "19.0.0.6.0",
    "category": "Website/Website",
    "author": "Lost Demand Project",
    "license": "LGPL-3",
    # Only what this version needs: website_sale_stock for stock quantities in the product index (Task 3.1);
    # purchase_stock comes with the restock proposals (M6).
    "depends": ["website_sale", "website_sale_stock"],
    "external_dependencies": {"python": ["elasticsearch"]},
    "data": [
        "security/website_sale_lost_demand_groups.xml",
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/synonym_views.xml",
        "views/res_config_settings_views.xml",
        "views/product_template_views.xml",
        "data/lost_demand_synonym_data.xml",
    ],
    "installable": True,
    "application": False,
}
