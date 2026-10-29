"""Configure a fresh shop database. Runs INSIDE the Odoo container, in `odoo shell` (Task 1.2a).

`uv run shop db create` sends this file on stdin, followed by a call `configure(env, {...})` whose settings
carry the secrets: they never appear on a command line, in the environment of a process or in a log.
The last stdout line is `SHOP_RESULT <json>`; it holds the integration user's API key, which the host tool
writes to `.env` and never prints.

Facts checked in the 19.0 source (.odoo-src/odoo):
- a new database has the login `admin` with the password `admin` (base/data/res_users_data.xml);
- the main company currency is USD (base/data/res_company_data.xml) and, with no country set, installing
  `account` loads the generic chart of accounts (account/models/ir_module.py::write);
- guest checkout is `account_on_checkout = 'optional'` (website_sale/models/website.py);
- the demo provider installs in test mode, published (payment_demo/data/payment_provider_data.xml);
- `res.users.apikeys._generate(scope, name, expiration_date)`: scope None = global key, required by JSON-2
  (base/models/ir_http.py::_auth_method_bearer); no expiry is allowed for a system/sudo environment;
- `odoo shell` rolls back at the end unless the script commits (cli/shell.py).
"""

import json

RESULT_PREFIX = "SHOP_RESULT "

# Rights for the host tools (catalog import in Task 2.4: products, vendors, vendor prices, stock);
# deliberately no Administration/Settings group (supervisor decision, 2026-10-29).
INTEGRATION_GROUPS = (
    "base.group_user",
    "sales_team.group_sale_manager",
    "stock.group_stock_manager",
    "purchase.group_purchase_manager",
)


def configure(env, settings):
    from odoo import Command

    demo_modules = env["ir.module.module"].search([("state", "=", "installed"), ("demo", "=", True)])
    if demo_modules:
        raise RuntimeError(f"demo data is installed in: {', '.join(demo_modules.mapped('name'))}")

    company = env.ref("base.main_company")
    company.write({"name": settings["company_name"]})
    if company.currency_id != env.ref("base.USD"):
        raise RuntimeError(f"company currency is {company.currency_id.name}, expected USD")

    website = env.ref("website.default_website")
    website.write({"name": settings["website_name"], "account_on_checkout": "optional"})

    provider = env.ref("payment.payment_provider_demo")
    if provider.state != "test" or not provider.is_published:
        provider.write({"state": "test", "is_published": True})

    env.ref("base.user_admin").write({"password": settings["admin_password"]})

    integration_user = (
        env["res.users"]
        .with_context(no_reset_password=True)
        .create(
            {
                "name": "Shop integration (synthetic)",
                "login": settings["integration_login"],
                "group_ids": [Command.set([env.ref(xml_id).id for xml_id in INTEGRATION_GROUPS])],
            }
        )
    )
    # sudo(): only a system environment may create a key without an expiration date.
    api_key = env["res.users.apikeys"].with_user(integration_user).sudo()._generate(None, "shop tools", None)

    env.cr.commit()
    result = {
        "api_key": api_key,
        "company": company.name,
        "currency": company.currency_id.name,
        "chart_template": company.chart_template,
        "website": website.name,
        "lang": env.ref("base.user_admin").lang,
        "payment_provider": f"{provider.name} ({provider.state})",
        "modules": sorted(env["ir.module.module"].search([("state", "=", "installed")]).mapped("name")),
    }
    print(RESULT_PREFIX + json.dumps(result))
