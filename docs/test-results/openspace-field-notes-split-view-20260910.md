# OpenSpace-style viewer completion — 10 September 2026

## Delivered

- Split View compares two capture dates side by side and can lock panorama direction between panes.
- Capture date and floor selectors remain limited to structural captures through 3 July 2026.
- Field Notes are anchored to the exact project, capture, floor, keyframe, plan coordinate, and panorama view.
- Field Notes support P1, P2, P3, completed, and verified statuses; assignee; due date; tags; comments; image/PDF attachments; and red freehand markup.
- The Field Notes workspace supports search and filters for floor, capture date, status, assignee, and tag.
- A printable report uses the active filters and includes status totals, evidence, markup, location, owner, assignee, due date, tags, and description.
- Viewer navigation exposes only working Compare and Field Notes destinations.

## Data integrity controls

- The API validates that capture, floor, and keyframe belong to the same project and capture before creating a note.
- An assignee must be a current member of the same project.
- Markup coordinates and total point count are validated before storage.
- Field Notes are retained as inspection history; completion uses workflow status rather than destructive deletion.

## Verification

- Database migration at `b82c6f1d3502 (head)`.
- API test suite: 154 passed.
- Web behavior tests: 9 passed.
- Ruff, ESLint, and TypeScript checks passed.
- Next.js production build passed and emitted the compare, field-notes, and API proxy routes.
- Manual browser verification covered the Field Notes list, the create-note drawer, Split View, lock behavior, and structural capture cutoff.
- The temporary QA account was removed after testing; no project Field Notes were created during UI verification.

## External dependency not enabled

- Outbound email alerts are intentionally not shown because no project mail provider has been configured. Assignment, due dates, comments, and status tracking work inside the application.
