# S1 and PC1 slab workflows — 8 September 2026

## Scope

The reviewed ST-04, ST-05, and ST-06 structural plans define separate S1 and
PC1 floor areas on floors 2–4. Floor 1 (ST-03) remains on its existing workflow
as explicitly requested.

## Workflows

- S1: Shoring, rebar tying, formwork, concrete, form stripping (5 stages,
  20% each).
- PC1: Shoring, precast slab placement, reinforcement, formwork, concrete,
  form stripping (6 stages, 16.67% each).

The API validates stages against the selected slab type. `PLACE_PRECAST` cannot
be saved against S1. Mixed multi-selection applies each action only to eligible
slabs, so precast placement updates PC1 zones without contaminating S1 data.
Historical ordinal floor 2–4 stage values are interpreted through the new
workflow on read; the historical rows are not destructively rewritten.

## Existing-data classification

- Floors updated: 2, 3, 4
- Active slab zones classified: 85
- S1: 49 zones
- PC1: 36 zones
- Floor 1 changed: 0 zones
- Reversible geometry backup: `.codex_tmp/slab-types-before-20260908.json`

## Verification

Browser verification passed on all three floors with no page or request errors:

- Floor 2: S1 17, PC1 12
- Floor 3: S1 16, PC1 12
- Floor 4: S1 16, PC1 12

Each S1 selection showed exactly the five requested labels. Each PC1 selection
showed exactly the six requested labels. The API test verifies per-type stage
validation and area-weighted overall progress (including the different 5/6
stage denominators). Full API suite: 139 passed. Ruff, ESLint, TypeScript, and
Next.js production build passed.
