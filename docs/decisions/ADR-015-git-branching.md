# ADR-015 — Git: feat/* → develop → main

- Status: Accepted
- Date: 2026-10-28
- Source: `docs/ai/01_ARCHITECTURE.md` §3

## Context
Supervisor meetings and the defense need a demo that always works.

## Decision
Feature branches merge into `develop` (squash); `develop` is promoted to `main` (merge commit) when a milestone is
accepted, and `main` is tagged. Nobody pushes directly to `main` or `develop` after the initial setup.

## Consequences
`main` is always demo-ready.

## Revisit when
—
