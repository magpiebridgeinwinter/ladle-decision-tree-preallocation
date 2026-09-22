# Disturbance Gantt draw.io

## Requirements

- Convert the audited `real_window_1100_1120_codex_stress_001` scenario into traceable diagram data.
- Generate an editable, uncompressed draw.io file with global Gantt, affected heats, and independent AP/AQ/AR decision pages.
- Preserve the distinction between ladle preallocation and crane dispatch; do not claim physical motion without telemetry.

## Acceptance criteria

- 31 affected heats, offline crane 2500, DT 30/31, Codex 31/31, and three Codex changes are present in the output.
- Draw.io import verification passes and the semantic JSON has stable IDs and one row per affected heat.
