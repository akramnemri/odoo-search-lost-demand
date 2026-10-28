# ADR-011 — Python tools as one uv project; host Python = Odoo image Python minor

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
Tools must run the same way on Windows, macOS and Linux, with one entry point.

## Decision
One `uv` project (`shoptools`, CLI `shop`), dependencies locked in `uv.lock`. Host Python pinned to the Odoo image's
Python minor version (3.12, ADR-018).

## Consequences
`uv run shop ...` works the same on every machine; no global Python packages.

## Revisit when
—
