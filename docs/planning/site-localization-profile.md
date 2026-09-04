# Site Localization Profile

- Project: อาคารหอพัก 4 ชั้น
- Site WGS84: `18.81170172078409, 98.96763232662926`
- Surveyed road-facing plan edge: Grid `6`, spanning Grid `A` through `D`
- Plan-coordinate convention: Grid 6 is the right/maximum-X edge of the normalized floor plan.
- Capture convention: timestamp `00:00` is the user-selected camera start position.

The GPS coordinate georeferences the site but does not provide indoor camera
positions for an MP4. The localization pipeline therefore preserves Stella
VSLAM's relative camera graph, pins timestamp 00:00 to the selected start, and
uses the surveyed Grid 6 road edge to remove the 180/360-degree orientation
ambiguity when a capture starts near that edge.
