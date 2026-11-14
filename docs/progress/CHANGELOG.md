# Changelog

Milestone releases promoted from `develop` to `main` (`docs/ai/03_GIT_TESTING_PIPELINE.md` §2, §13). Details in the
milestone notes (`docs/report/notes/`).

## m1-stack — 2026-11-14

### What works now
- The whole stack starts with one command (`uv run shop up`): Odoo 19 Community, PostgreSQL 16, Elasticsearch and
  Kibana 9.5.5 on the free Basic license, security on, ports on localhost only. Clean start healthy in 93 s.
- `uv run shop db create` builds the shop database (website, guest checkout, Demo payment provider, integration user
  with a JSON-2 API key); `shop snapshot save / restore` brings a state back in under a minute.
- Module `website_sale_lost_demand` 19.0.0.1.0 installs from Apps; Settings › Website shows the Elasticsearch status
  (reachable, version, license, health, circuit) and keeps working when Elasticsearch is down.
- `uv run shop doctor` checks the machine, the stack, Elasticsearch, Kibana and Odoo.
- Tests: 266 tools tests (`shop test tools`), 13 module tests including Elasticsearch (`shop test module --es`).
- CI on every pull request: lint, tools tests on Ubuntu and Windows, compose validation, and the module installed and
  tested on a fresh database against the real stack; all required on `develop` and `main`.
- Odoo can be debugged in Docker from PyCharm (`docs/setup/PYCHARM.md`, run configurations in `.run/`).

### Known limitations
- Shop search does not use Elasticsearch yet (M3); no events, dashboards or lost-demand logic yet (M4–M6); the catalog
  is empty until the ESCI import (M2).
- Python changes need an Odoo restart: the repository is on the Windows drive, so the container gets no file-change
  events (ADR-014).
- Docker debugging needs PyCharm Professional (trial until 2026-11-14 or 15; free JetBrains student license chosen,
  application by the supervisor).
- The doctor does not honour `COMPOSE_PROJECT_NAME`: with a second Compose project its port checks fail.
- Shop-owner interview #1 (Task 1.6) not done yet.
