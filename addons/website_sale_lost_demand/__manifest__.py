{
    "name": "Lost-Demand Search",
    "summary": "Elasticsearch shop search with fallback, and restocking from lost demand",
    "description": """
School project (ERP + Big Data). Shop search runs on Elasticsearch (free Basic license) with a
fallback to Odoo's own search; searches, clicks, carts and purchases become restocking decisions.

Task 1.3 (skeleton): Elasticsearch connection settings from the environment, read-only cluster status in
Website settings, circuit breaker, security group.
Task 2.4a: product brand (filled by the catalog importer).
    """,
    "version": "19.0.0.2.0",
    "category": "Website/Website",
    "author": "Lost Demand Project",
    "license": "LGPL-3",
    # Only what this version needs; later tasks add website_sale_stock and purchase_stock when they use them.
    "depends": ["website_sale"],
    "external_dependencies": {"python": ["elasticsearch"]},
    "data": [
        "security/website_sale_lost_demand_groups.xml",
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/product_template_views.xml",
    ],
    "installable": True,
    "application": False,
}
