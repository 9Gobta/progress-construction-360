# Structural scope cutoff and Virtual Tour review gate — 10 September 2026

## Owner decisions

- Structural progress ends on 3 July 2026 (3 July 2569).
- Captures after that date are architectural work and must not appear in the structural workflow.
- Raw `.insv` ingestion is outside the current product scope; the accepted input is a stitched equirectangular MP4.
- The owner has not yet accepted the Virtual Tour set. Automatic `READY` status must not be presented as human acceptance.

## Implementation

- Added a reversible project-level `structural_tracking_end_date` setting.
- The current project is set to `2026-07-03`.
- Capture listing and navigation exclude later captures; direct detail access returns not found and new captures after the cutoff are rejected.
- No Capture, localization, inspection history, or media object was deleted.
- Added an explicit reviewer action, `ยืนยันว่า Virtual Tour ตรงกับแปลน`, which records reviewer and timestamp without moving the route or rewriting Progress.
- Corrected the map status copy so automatically accepted localization is labelled as waiting for Virtual Tour review rather than human-confirmed.

## Data snapshot

- In structural scope: 131 captures across 80 dates — 130 `READY`, 1 `REVIEW_REQUIRED`.
- Excluded architectural period: 80 captures from 4–30 July 2026 — 1 `READY`, 79 `REVIEW_REQUIRED`.
- The one in-scope `REVIEW_REQUIRED` capture is 3 July 2026, floor 1, ID `204f9ec6-05ac-4799-bb40-4751a9899956`.

`READY` is a processing result, not owner acceptance. Virtual Tour remains pending until the owner reviews and explicitly confirms each capture/floor.

## Verification

- API: all 153 tests passed; Ruff passed.
- Web: 9 unit tests passed; TypeScript, ESLint and production build passed.
- Database migration is at Alembic head `f4d3a8c91e20`.
- Runtime query returns 131 visible structural captures and 80 excluded architectural captures.
- Local Web and API readiness checks passed.
- Fresh public Quick Tunnel returned HTTP 200 on 10 September 2026.
