# 00 — How to Use This Prompt Pack (for the supervisor)

This file is for you, the human supervisor. It explains how to run the AI coding sessions, what to paste,
what to check, and what only you can do.

---

## 1. What is in the pack

| File | Purpose | Who reads it |
|---|---|---|
| `CLAUDE.md` (repository root) | Short always-loaded rules and work loop | The agent, every session |
| `docs/ai/00_HOW_TO_USE.md` | This guide | You |
| `docs/ai/01_ARCHITECTURE.md` | What we build and how it is structured (requirements, decisions, module, flows) | The agent, on demand |
| `docs/ai/02_CODING_STANDARDS.md` | How code must be written (Python, Odoo, Elasticsearch, data, Locust, evaluation) | The agent, on demand |
| `docs/ai/03_GIT_TESTING_PIPELINE.md` | Branches, test gates, CI, releases, demo checklist, task report format | The agent, on demand |
| `docs/ai/04_DATA_SEARCH_EVALUATION.md` | Datasets, catalog slice, index and query design, event schema, lost-demand rules, evaluation protocol | The agent, for data/search/evaluation work |
| `docs/ai/05_ROADMAP.md` | Milestones M0–M11 and bounded tasks | The agent, current milestone only |
| `docs/ai/06_ENVIRONMENT_SETUP.md` | Tool detection, version pinning, installs, doctor, troubleshooting | The agent, in M0 and when the environment breaks |
| `docs/progress/STATUS.md` | Live memory between sessions (created in Task 0.2) | Both |

## 2. One-time setup (you)

1. Create an empty GitHub repository (suggested name: `odoo-search-lost-demand`). Public is fine; the pack forbids committing secrets or data.
2. Clone it and add the pack:

   ```bash
   git clone <REPO_URL>
   cd odoo-search-lost-demand
   # copy CLAUDE.md to the root and the docs/ folder of the pack
   mkdir -p docs/sources
   # put the specification PDF in docs/sources/
   git add .
   git commit -m "docs: add AI prompt pack and project specification"
   git push origin main
   git switch -c develop
   git push -u origin develop
   ```

   If Git is not installed yet, create a normal folder, put the files in it and start the agent there:
   Task 0.3 installs Git and Task 0.4 connects the folder to GitHub.

3. Start the coding agent **inside the repository folder** and paste prompt **0** below.

GitHub settings (default branch, rulesets, merge methods) are done in Task 0.6; the agent gives you the exact clicks.

## 3. What to expect in Milestone 0

- The agent first only **looks**: it lists your OS, RAM, disk, tools and versions, and stops.
- Then it **researches** the right versions online and asks you to approve a version table.
- Then it **installs** what is missing, one tool at a time, each time telling you the command, the source, the size, and whether
  you will see an admin prompt or need a reboot. You click the UAC/sudo prompts; you accept Docker Desktop's terms; you log in to
  PyCharm with your JetBrains student license.
- At the end, `uv run shop doctor` shows the machine is ready, and the same command will tell you later what broke.

Plan 2–4 hours with the laptop plugged in and a stable connection (several GB of downloads now, more for datasets later).
Windows may need a reboot for WSL2.

## 4. The session loop

```text
You: start-of-session prompt (A)
Agent: reads STATUS.md + current milestone, posts a plan, waits
You: "go" (B) or corrections
Agent: implements one task, runs checks, opens a PR, posts the TASK REPORT, stops
You: run the manual test steps
You: report the result (C or D)
Agent: fixes, or (after your merge) cleans up and proposes the next task
```

Rules of thumb:

- One task per round. If the agent starts a second task, stop it (prompt J).
- Read the plan before saying "go": it is the cheapest moment to correct direction. Check it names the Odoo 19.0 source it will override.
- You merge the PRs (squash). The agent never merges into `develop` or `main`.
- Start a **new session** at each milestone boundary, or when answers get slower, vaguer or start forgetting rules.

## 5. Prompts to copy and paste

### 0 — Very first session

```text
First session on this project. Read CLAUDE.md, then docs/ai/06_ENVIRONMENT_SETUP.md, then the M0 section of
docs/ai/05_ROADMAP.md. Start Task 0.1: a read-only inventory of this machine. Do not install, configure or download anything.
Post the inventory table and stop.
```

### A — Start of session

```text
New session. Read CLAUDE.md, then docs/progress/STATUS.md, then only the section of docs/ai/05_ROADMAP.md for the
current milestone. Read other docs/ai files only if the current task needs them.

Then:
1. Summarize in 5 lines where we are (milestone, last completed task, environment and data state, open issues).
2. Restate the next task, its acceptance criteria and its requirement IDs.
3. Post your plan (max ~15 lines): files you will touch, Odoo 19.0 source you will read/override (file + method),
   dependencies (with reasons), index/schema changes, tests, risks, anything you need from me.
Do not write code yet. Wait for my "go".
```

### B — Approve the plan

```text
go
```

or, for small tasks:

```text
go — autopilot for this task only. Still stop after the task report.
```

### C — Manual test passed

```text
Manual test PASSED for Task <X.Y>.
I merged PR #<n> into develop (squash).
Verify the merge, sync develop, delete the feature branch per 03 §4b, update STATUS.md,
then post the plan for the next task and wait.
```

### D — Manual test failed

```text
Manual test FAILED for Task <X.Y>.
Step <n>: <what I did>
Expected: <...>
Got: <...>
Evidence: <error message / first 20 lines of the log / screenshot description>
Doctor: <output of `uv run shop doctor` if relevant>

Diagnose before changing code: explain the probable cause and your fix plan, then wait for my "go".
Stay on the same branch.
```

### E — End of session / handoff

```text
We stop here for this session. Update docs/progress/STATUS.md so that a brand-new session can continue without this
conversation: current milestone and task, branch/PR state, environment state, data state (datasets, snapshot loaded,
index counts), decisions taken today, open issues, exact next step. Commit it on the current branch (or on a chore/status
branch if no task branch is open). Then give me a 5-line summary.
```

### F — Start of a milestone

```text
We are starting Milestone <M>. Read its section in docs/ai/05_ROADMAP.md.
Before the first task: list the milestone's tasks, the [HUMAN] and [SUPERVISOR] items I must prepare, downloads or long jobs
coming (size and time), risks you see, and any task you think should be split or reordered. Do not start Task <M.1> yet.
```

### G — Milestone promotion

```text
Milestone <M> is accepted on develop. Prepare the promotion:
1. Run the develop regression checklist (03 §9) as far as the project has progressed and report results.
2. Write the milestone note docs/report/notes/M<M>.md and the CHANGELOG entry.
3. Open the PR develop -> main (merge commit) with a release summary.
4. Give me the tag command to run after I merge, and the demo checklist (03 §13) for my next supervisor meeting.
Stop after that.
```

### H — Decision or scope change

```text
Decision: <what was decided, by whom, date>.
Record it as a new ADR in docs/decisions/, update the affected sections of docs/ai/*.md, docs/evaluation/protocol.md
and docs/ai/05_ROADMAP.md, and show me the diff before committing (chore/ branch + PR).
```

### I — Self-review before I test

```text
Before I test, review your own diff against 02_CODING_STANDARDS.md §18 (simplicity review), §11 (security and privacy)
and §2 (Odoo rules). List any problem you find and fix it, or explain why it is acceptable.
```

### J — The agent is drifting

```text
Stop. You are outside the current task (<what it is doing>). Revert anything unrelated to Task <X.Y>, re-read CLAUDE.md
and the task definition, and restate the scope in 3 lines before continuing.
```

### K — The environment broke

```text
Something in the environment is broken: <symptom>. Do not change code. Run `uv run shop doctor --verbose`, read
docs/ai/06_ENVIRONMENT_SETUP.md §8, diagnose, and propose a fix (exact commands, whether they are destructive or need admin
rights). Wait for my "go". If the fix is new, add it to docs/setup/TROUBLESHOOTING.md afterwards.
```

### L — Before a long job

```text
Before you start <download / import / replay / load test>: estimate duration, disk and memory, check free space with the
doctor, and tell me what happens if it is interrupted (resume or restart). Then run it in the background with output to a
log file under local/, and report progress every few minutes. Do not start anything else that competes for memory.
```

### M — Evaluation run

```text
Run <evaluation kind> exactly as described in docs/evaluation/protocol.md (version <v>). Restore the baseline snapshot first,
record run.json, keep raw outputs in results/<run-id>/, write the summary to results/summary/, and report the numbers with
the run ID. Do not change any configuration. Never use the test set for tuning.
```

### N — Supervisor meeting summary

```text
Prepare a one-page progress summary for my academic supervisor: what works now (with the demo steps), results with numbers
and run IDs, what changed since the last meeting, risks, decisions I need from them, and next steps with dates.
Plain language, no internal jargon. Save it as docs/report/meetings/<date>.md.
```

### O — Draft a report section

```text
Draft section "<title>" of the final report in <language>, following the approved outline in docs/report/outline.md.
Use only facts from docs/ (architecture, ADRs, milestone notes, evaluation results). Every number must cite its run ID;
synthetic data must be labelled; list the figures and screenshots needed. Save it under docs/report/drafts/.
```

## 6. Your review checklist for each PR (5–10 minutes)

- Does the PR do only the current task? Any surprise files in `git diff --stat` (data, dumps, `.env`, results, big files)?
- **Odoo:** changes only in our module; overrides call `super()`; the plan cited the 19.0 source; new models have access rights;
  module version bumped; fresh install **and** upgrade passed.
- **Elasticsearch:** templates and mappings are files in `elastic/`; only Basic-license features; shopper-facing calls have a timeout and a fallback.
- **Events:** no personal data; logging cannot break or slow the page.
- **Data and evaluation:** seeds fixed; `run.json` present for any number; tuning only on the dev set; synthetic data labelled.
- New dependencies justified and pinned (uv group or Odoo image).
- The task report lists skipped checks honestly, and the manual test steps are precise.

## 7. Only you can do these

- Approve installers that need admin/UAC/sudo rights, reboot, enable virtualization in the BIOS.
- Accept Docker Desktop's terms; activate PyCharm with the JetBrains student license.
- Create the Kaggle account, accept the REES46 dataset terms, create the API token.
- Create the GitHub repository and change its settings.
- Find shop owners, run the two interviews and the pilot demo; collect consent.
- Get academic decisions: evaluation protocol approval, scope cuts, report language and template, dates.
- Build Kibana dashboards in the browser if the agent has no browser access (it gives you a panel-by-panel spec).
- Capture screenshots and the backup demo video; validate the final report.

## 8. Keeping token usage under control

- The agent reads `STATUS.md` + one roadmap section, not everything. Remind it if it starts reading every file.
- Keep tasks small. A task that changes more than ~10 files or adds more than one new model is probably two tasks.
- New session per milestone; new session when a debugging thread gets long — after a handoff (prompt E).
- Ask for diffs of specific files rather than whole-file dumps.
- Do not paste long logs or data: the first error and ~20 lines around it; data previews of 20 rows at most.
- Long jobs run in the background (prompt L); do not let the agent wait on them in the conversation.

## 9. STATUS.md structure (the agent creates it in Task 0.2)

```markdown
# STATUS

Updated: <date> by <agent session>

## Current position
- Milestone: M<x> — <name>
- Task: <x.y> — <title> — state: planned | in progress | awaiting manual test | done
- Branch / PR: <branch> — <PR link>

## Environment
- Doctor: OK | WARN (<items>) | FAIL (<items>) — run on <date>
- RAM profile: lowmem | standard — stack versions: see docs/setup/VERSIONS.md

## Data state
- ESCI: downloaded <date>, checksum OK | not yet
- REES46: downloaded <date> | not yet
- Odoo database: <name>, snapshot loaded: <name>
- Product index: shop-products-v<N>, <count> docs (Odoo: <count>)
- Events stored: <count> (shop) / <count> (rees46)

## Last completed tasks
- <x.y> — <title> — merged <date>

## Latest results
- <metric>: <value> — run <run-id>

## Decisions since last milestone
- ADR-<n> — <one line>

## Open issues / risks
- ...

## Waiting on human / supervisor
- ...

## Next step (exact)
- ...
```

## 10. Working as a pair (if two developers)

- Each developer runs their own agent session on their own branch; never two agents on the same branch or the same files.
- The GitHub issues/board (Task 0.6) shows who does what; assign a task before starting it.
- `STATUS.md` is updated by the PR that merges; resolve conflicts in it by keeping both "last completed" entries.
- Run the doctor on both laptops; record which one is the demo machine.
