{
    "name": "Lost-Demand Search",
    "summary": "Elasticsearch shop search with fallback, and restocking from lost demand",
    "description": """
Final-year project (ERP + Big Data). Shop search runs on Elasticsearch (free Basic license) with a
fallback to Odoo's own search; searches, clicks, carts and purchases become restocking decisions.

Task 1.3 (skeleton): Elasticsearch connection settings from the environment, read-only cluster status in
Website settings, circuit breaker, security group.
    """,
    "version": "19.0.0.1.0",
    "category": "Website/Website",
    "author": "Lost Demand PFE",
    "license": "LGPL-3",
    # Only what this version needs; later tasks add website_sale_stock and purchase_stock when they use them.
    "depends": ["website_sale"],
    "external_dependencies": {"python": ["elasticsearch"]},
    "data": [
        "security/website_sale_lost_demand_groups.xml",
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
