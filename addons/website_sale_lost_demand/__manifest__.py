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
    """,
    "version": "19.0.0.4.0",
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
        "views/res_config_settings_views.xml",
        "views/product_template_views.xml",
    ],
    "installable": True,
    "application": False,
}
