# Report kit

Material for the final report and the presentation, collected **while** the project is built, so nothing has
to be reconstructed from memory at the end. Updated at the end of every task (rule in `CLAUDE.md`, work loop).

The kit gathers and points; it does not replace the sources of truth:

- numbers come only from committed scripts and recorded runs (`results/summary/`, run folders) — the kit says
  which file holds each number, it never retypes one by hand;
- decisions live in `docs/decisions/` (ADRs) and the protocol in `docs/evaluation/protocol.md`;
- milestone notes (`../notes/M<N>.md`) summarise each milestone at its end.

| File | What it holds | Update when |
|---|---|---|
| [odoo-overrides.md](odoo-overrides.md) | every Odoo model, method and view we inherit; what Odoo does there (file, line) and what we add, with short code | a task adds or changes an extension point |
| [engineering-log.md](engineering-log.md) | problems met, their cause, the fix, and the lesson — per task | a task meets a non-obvious problem |
| [figures.md](figures.md) | diagrams (Mermaid sources) and the screenshots to capture, with their state | a task adds something worth showing |
| [results-index.md](results-index.md) | every measured result the report may cite, and the command and file it comes from | a task produces or reproduces a result |
| [report-outline.md](report-outline.md) | a proposed chapter plan with the material for each chapter (a proposal: the structure and language are the supervisor's decision) | a chapter gains material |

Writing rules (from `CLAUDE.md`): English; synthetic data is called synthetic; negative results are reported;
the project is a school project (ERP + Big Data).
