# Roof progress inspection verification — 8 September 2026

## Implemented

- Human reviewers can select one or many reviewed roof-plan elements.
- Multi-selection is enabled by default on every structural plan (beams, columns, slabs and roofs). A plain click adds/removes an item, while visible actions select all or clear the selection.
- Each selected element can be saved as complete or not complete with the current 360 keyframe as evidence.
- Roof progress is read cumulatively up to the selected capture date.
- The API validates project, floor, element IDs, duplicate IDs and evidence ownership.
- Saving roof elements writes a human progress observation for the matching roof WBS activity so Dashboard actual progress remains human-verified.

## Project data verified

| Roof plan level | Elements | Work types |
| --- | ---: | ---: |
| 5 | 54 | 4 |
| 6 | 68 | 8 |
| 7 | 15 | 4 |

## Checks

- `pytest apps/api/tests/test_roof_progress.py apps/api/tests/test_column_progress.py apps/api/tests/test_schedules_progress.py -q` — 6 passed
- `npm run lint:web` — passed
- `npm run typecheck:web` — passed
- `npm run build:web` — passed
- Python compile and Ruff checks — passed
- Local web — HTTP 200
- Public login page — HTTP 200
- Production API OpenAPI includes `roof-progress`

No real project progress value was changed during verification; the write path was tested in an isolated test database.
