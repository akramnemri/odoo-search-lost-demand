# 03 — Git Workflow, Testing Gates, CI & Releases

Act as the senior engineer responsible for keeping the repository stable and the demo always working
while development progresses.

Repository: https://github.com/akramnemri/odoo-search-lost-demand. Treat it as **public**: anything committed is visible to everyone.

There are no servers in this project. "Environments" are: each developer's laptop, GitHub Actions CI, and the demo laptop.

---

## 1. Branch model

```text
main        demo-ready: the last accepted milestone; tagged; what you show the academic supervisor and the jury
  ^
develop     integration: every merged task; must always start with one command and pass CI
  ^
feat/<req-id>-<short-name>     one bounded task (e.g. feat/FR3-in-stock-ranking)
fix/<req-id>-<short-name>      bug fix
chore/<short-name>             tooling, environment, CI, docs (e.g. chore/doctor-wsl-checks)
spike/<topic>                  time-boxed experiment — NEVER merged; its written conclusion is merged via a chore/ PR
eval/<run-name>                optional: frozen configuration for an evaluation campaign
```

Rules:

- Never commit directly to `main` or `develop`.
- Feature branches start from an up-to-date `develop`.
- With two developers, never work on the same branch at the same time; coordinate through GitHub issues.

## 2. Feature lifecycle

```text
git switch develop && git pull
 -> git switch -c feat/<id>-<name>
 -> implement ONE bounded task
 -> automated quality gate (§6)
 -> update docs/progress/STATUS.md
 -> commit(s), push branch, open PR to develop
 -> TASK REPORT (§14) -> STOP
 -> supervisor tests manually
 -> fixes if needed (same branch, new commits)
 -> supervisor merges the PR into develop (squash merge)
 -> agent: sync develop, verify the merge, delete the branch (§4b)
 -> develop regression check (§9) at milestone end or when the supervisor asks
```

Milestone promotion:

```text
milestone exit criteria met on develop
 -> regression check (§9) + demo checklist (§13)
 -> PR develop -> main (merge commit, not squash)
 -> supervisor merges
 -> tag: m<N>-<name> (e.g. m3-search-works) + entry in docs/progress/CHANGELOG.md
```

A feature is not complete because it imports without errors.

## 3. Bounded tasks

Never implement several features in one context window to make progress look faster.

Each task has: a purpose, acceptance criteria, success and failure behavior, the Odoo source it touches, index or schema
changes, tests, manual verification steps. These are defined in `05_ROADMAP.md`.
If a task is too large to test cleanly, propose a split before starting.

## 4. Commit discipline

Conventional commits with a scope:

```text
feat(search): rank in-stock products above out-of-stock ones (FR3)
feat(events): log click events with search id and position (FR6)
fix(index): reindex template when stock quant changes
test(lostdemand): cover zero-result detection on a crafted event set
chore(doctor): detect Docker VM memory on Windows
docs(adr): record ADR-008 event pipeline decision
```

Scopes: `module`, `search`, `index`, `events`, `lostdemand`, `purchase`, `synonyms`, `kibana`, `data`, `import`,
`replay`, `loadtest`, `eval`, `tools`, `doctor`, `infra`, `ci`, `deps`, `docs`, `adr`, `report`.

No unrelated refactors inside a feature commit. No giant "everything done" commits.

## 4b. Deleting a merged branch

Once a branch is merged into `develop` and no longer needed, delete it locally and on the remote.

Verify the merge first:

```bash
git switch develop && git pull
git log --oneline -5                         # the squash commit for the PR is present
gh pr view <number> --json state,mergedAt    # if gh is available: state MERGED
```

Squash merges mean `git branch --merged` does NOT list the branch. Rely on the PR state and the squash commit.

```bash
git push origin --delete feat/<name>   # skip if GitHub already deleted it automatically
git branch -D feat/<name>              # ONLY after the PR is confirmed MERGED (squash requires -D)
```

Never delete a branch with unmerged or still-needed work (parked task, under review, spike not yet written up).
`main` and `develop` are never deleted.

## 5. Git safety

Before changes: `git status`, `git branch --show-current`.
Before committing: `git diff --stat`, `git diff`, `git status`.
After committing: `git log -1 --oneline`, `git status`.

- Look at `git diff --stat` for surprises: data files, dumps, `.env`, results, files over 1 MB → stop and remove them.
- Line endings: the repository uses LF (`.gitattributes`). On Windows, never let shell scripts or Dockerfiles get CRLF
  (containers fail with `\r` errors).
- Never discard the supervisor's uncommitted work. Never force-push. Never rewrite shared history.
- If the working tree is dirty with changes you did not make, STOP and ask.

## 6. Automated quality gate

Run through the project CLI (exact sub-commands are created in Milestone 0–1; keep this list up to date):

```text
uv run shop lint              # pre-commit: ruff (lint + format), XML/YAML/JSON/TOML checks, secret scan
uv run shop test tools        # pytest for tools/ and the module's pure services/
uv run shop test module       # Odoo test runner for our module in the container (unit tests)
uv run shop test module --es  # + integration tests against the running Elasticsearch
docker compose config -q      # compose file valid
uv run shop doctor            # environment and stack still healthy
```

Plus, when relevant to the task:

- module **fresh install** on a new database and **upgrade** (`-u`) on an existing one (any model, view or data change);
- `uv run shop index rebuild --check` (mapping or indexing changes);
- freshness probe (event or indexing changes);
- Locust smoke run, 5 users for 2 minutes (shop flows, events);
- NDCG harness on the **dev** set (search changes) — compare with the last recorded value;
- REES46 replay on the sample fixture (replay changes);
- Kibana saved-objects import on a clean Kibana (dashboard changes).

Report each check as PASSED / FAILED / SKIPPED (with reason). Never claim a check passed without running it.

## 7. Mandatory manual-test gate

After automated checks pass, STOP and give the supervisor exact instructions:

1. setup (branch, commands, which DB snapshot to restore, which data must exist);
2. exact actions, step by step, with URLs;
3. expected result for each step;
4. expected failure behavior where relevant (what must degrade gracefully);
5. what to send back if it fails.

Template:

```text
MANUAL VERIFICATION REQUIRED

Setup:
  git fetch && git switch feat/<name>
  uv sync
  uv run shop up                      # or: docker compose up -d
  uv run shop snapshot restore baseline-catalog
  uv run shop doctor                  # must be green (or only known warnings)

Steps:
  1. Open http://127.0.0.1:8069/shop and search for "<query>".
  2. ...
  3. Stop Elasticsearch: docker compose stop elasticsearch, then search again.
Expected:
  1. ...
  3. Results still appear (Odoo native search), no error page.
Must fail / degrade:
  - ...
If something fails, send: the step number, a screenshot, and the output of `uv run shop logs odoo --tail 50`.
```

Useful URLs: shop `http://127.0.0.1:8069/shop`, Odoo backend `http://127.0.0.1:8069/odoo` (verify the 19.0 path),
Kibana `http://127.0.0.1:5601`, Elasticsearch `http://127.0.0.1:9200` (needs credentials), Locust UI `http://127.0.0.1:8089`.

Do not start the next task before receiving the supervisor's result.

## 8. Integration gate (before the supervisor merges into develop)

- task tests and the broader suite pass; lint passes;
- the module installs on a fresh database **and** upgrades an existing one;
- Elasticsearch template/mapping changes are applied by code and the rebuild/rollover need is written in the PR;
- `.env.example`, `docs/setup/` and README are updated for any new variable, command or prerequisite;
- no secret, dataset, dump, result or large file committed;
- previously finished features still work (quick sanity: search, fallback, events in Kibana, lost-demand run);
- PR description lists: requirement IDs, what changed, Odoo methods overridden, index/schema changes, module version,
  manual test result.

## 9. Develop regression gate (end of each milestone)

Check from a clean start, in this order, as far as the project has progressed:

1. `docker compose up -d` from nothing reaches healthy; `uv run shop doctor` is green; license is `basic`.
2. Fresh database creation and module install; snapshot restore works.
3. Catalog import on a sample (`--limit 500`) works and is idempotent.
4. Shop search with Elasticsearch, and with Elasticsearch stopped (fallback).
5. Product change visible in search within 60 s.
6. Events visible in Kibana within 10 s; dashboards import cleanly.
7. Lost-demand job runs; a proposal becomes a draft RFQ.
8. REES46 replay on the sample fixture.
9. Locust smoke run without errors.
10. NDCG on the dev set reproduces the last recorded value (same config, same data) within a small tolerance.

Do not promote to `main` because only the latest feature passes.

## 10. Data model, index and schema changes

- **Odoo models:** every change bumps the module version and must upgrade an existing database with `-u`.
  The demo database is reproducible from scripts and snapshots, so migration scripts are written only when a change
  cannot be handled by a normal upgrade; say so in the PR.
- **Product index:** mapping or analyzer change → new index version → full rebuild → alias swap. Never edit a live mapping in place.
- **Event data stream:** compatible additions update the index template and apply on the next rollover (force a rollover
  if needed). Incompatible changes need a decision (ADR) because stored events may need reindexing.
- **Synonyms:** managed in Odoo, synced to the synonyms set; no reindex required (search-time analyzer).
- **Datasets and slices:** a change to the slice rules or seed changes every downstream result → requires supervisor approval
  and a note in `docs/evaluation/protocol.md`.

## 11. Secrets and local files

- `.env` (git-ignored) holds every password, key and secret; `uv run shop env init` generates it from `.env.example`.
- Never commit: `.env*` with values, Elasticsearch passwords or API keys, Odoo API keys, the Kaggle token, the Odoo master
  password, database dumps, snapshot archives, datasets, raw results, `local/`, `.odoo-src/`.
- CI uses throwaway passwords defined in the workflow for its own containers; no real secret is needed in GitHub.
- If a secret is ever committed, STOP and tell the supervisor immediately: rotate it (removing the commit is not enough on a public repository).

## 12. CI pipeline (GitHub Actions)

`ci.yml`, on every PR and on pushes to `develop` and `main`, target under 15 minutes:

- **lint** — pre-commit (ruff, file checks, secret scan).
- **tools** — `uv sync --locked`, pytest for `tools/` and the module's `services/` (uses small synthetic fixtures only).
- **compose** — `docker compose config -q` on the real compose file.
- **module** — build the Odoo image, start PostgreSQL and a small-heap Elasticsearch as service containers, install the
  module on a fresh database and run its tests (unit + `es` integration).
- Later: Kibana saved-objects import check; REES46 mapping on the fixture.

Datasets are never downloaded in CI. Fixtures are synthetic and tiny (a few dozen products, queries and events in the
ESCI/REES46 formats), committed under `tools/tests/fixtures/`.

Repository settings (human, once): default branch `develop`; rulesets on `main` and `develop` (require PR, require CI,
block force pushes and deletion); squash for feature PRs, merge commits for `develop → main`; auto-delete head branches.
Required approvals: 0 for a solo developer, 1 for a pair.

## 13. Releases and the demo

**Promotion checklist** (before merging `develop → main`):

- regression gate (§9) passed and written in the PR;
- `docs/progress/CHANGELOG.md` entry (what works now, known limitations);
- milestone note written in `docs/report/notes/M<N>.md` (what was built, design choices, problems met, screenshots to capture);
- tag created after merge.

**Demo checklist** (before any supervisor meeting, pilot or defense):

- laptop on power; Docker resources set for the right RAM profile; other heavy apps closed;
- `uv run shop up` then `uv run shop doctor` green;
- the demo database snapshot restored; product index count matches Odoo; dashboards imported;
- a short scripted scenario rehearsed (search with a typo, synonym, in-stock first, fallback with Elasticsearch stopped,
  events live in Kibana, lost-demand run, proposal → RFQ);
- a recorded backup video of the scenario in case the live demo fails.

**Demo freeze:** in the week before the defense, only fixes go to `main`.

## 14. Mandatory task report

At the end of every task, reply with exactly this structure, then STOP:

```text
TASK: <milestone.task> — <title> (<requirement IDs>)

BRANCH / PR: <branch> — <PR link or "not opened (reason)">

IMPLEMENTED:
- ...

FILES CHANGED (main ones):
- ...

ODOO SOURCE OVERRIDDEN:
- none | <.odoo-src path>::<method> — why

MODULE VERSION / UPGRADE:
- unchanged | 19.0.x.y.z — fresh install: PASSED/FAILED — upgrade (-u): PASSED/FAILED

INDEX / SCHEMA / DATA CHANGES:
- none | <template or mapping or slice change> — rebuild/rollover needed: yes/no

ENV / CONFIG CHANGES:
- none | <variable> added to .env.example — <purpose>

AUTOMATED CHECKS:
- lint: PASSED
- tools tests: PASSED (n tests)
- module tests: PASSED (n tests) | FAILED (...)
- doctor: PASSED (warnings: ...)
- other: ...
- skipped: <check> — <reason>

MEASUREMENTS (if any):
- <metric>: <value> (run id: <id>)

MANUAL TEST REQUIRED:
<the §7 block>

KNOWN LIMITATIONS / FOLLOW-UPS:
- ...

DECISIONS NEEDED FROM SUPERVISOR:
- none | ...

NEXT TASK (do not start): <milestone.task> — <title>
```

Do not continue until the supervisor reports the manual test result.
