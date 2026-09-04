# Working agreement for Codex

This repository supports two independent workstreams: product development and
the graduation thesis. Always identify the requested workstream before editing.

## Non-negotiable project rules

- The current scope is structural construction progress verified by a human
  reviewer from 360-degree evidence. AI/CV is used for localization only.
- Do not present archived AI progress predictions as the current product scope.
- Do not commit `.env`, credentials, databases, source videos, model weights,
  generated media, backups, or private advisor recordings.
- Never rewrite or delete inspection history. Progress records must remain
  auditable and attributable to a user and timestamp.
- The capture dated 20 December 2025 (20/12/2568), capture ID
  `b78c9804-76c2-4e96-93d4-53cf55ffba3f`, is the accepted Virtual Tour and 3D
  warp-point reference. Do not modify its Virtual Tour, camera poses, route,
  calibration, or 3D warp-point data unless the project owner explicitly asks
  for that exact capture to be changed.
- Do not claim that a localization, accuracy, dashboard, WBS migration, or
  acceptance criterion is complete without reproducible evidence.

## Product-development workstream

Product code lives mainly in `apps/`, `workers/`, `packages/`, `scripts/`,
`infra/`, and `ml/`. Preserve user data and unrelated local changes. Read any
more specific `AGENTS.md` below the directory being edited. Run checks
proportional to the change and record durable test evidence under
`docs/test-results/` when it supports the thesis.

Recommended branch: `web-development`.

## Thesis workstream

Thesis work belongs in `docs/thesis/`, `docs/advisor-meetings/`,
`docs/system-design/`, and `docs/test-results/`. A thesis-only task must not edit
application code, migrations, databases, runtime configuration, or generated
localization data unless the project owner explicitly expands the scope.

Use repository evidence as the source of truth. Label proposals, future work,
and unverified results clearly. Cite the exact source document or code path used
for technical claims. Never invent experimental metrics or advisor decisions.

Recommended branch: `thesis-writing`.

## Source priority

When sources disagree, use this order:

1. The project owner's latest explicit instruction.
2. `PROJECT_CONTEXT.md` and the current Scope v2 documents.
3. Reproducible test results and current implementation.
4. Older planning documents and archived baselines.

Start a thesis task with `THESIS_HANDOFF.md` and
`docs/thesis/CODEX_START_PROMPT_TH.md`.
