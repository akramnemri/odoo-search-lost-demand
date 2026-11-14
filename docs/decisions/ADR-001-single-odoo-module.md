# ADR-001 — All Odoo changes live in one module

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
The specification asks for a reusable add-on with no changes to Odoo core, easy to upgrade.

## Decision
Every Odoo-side change lives in one module, `website_sale_lost_demand`, through inheritance only.
Odoo core and standard addons are read-only.

## Consequences
One manifest, one version number, one test suite. Pure logic goes to `services/` (testable without Odoo).
The module can grow large; files are split by responsibility, not into extra modules.

## Revisit when
Never likely.
