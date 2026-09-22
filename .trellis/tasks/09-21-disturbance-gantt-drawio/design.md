# Design

Use the OpenSpec change `build-disturbance-gantt-drawio` as the source of truth. Add a Python generator under `tools/` that reads the audit, emits `diagram_data.json`, and builds an uncompressed `mxfile` with three pages. Keep all semantic data in JSON and use short labels/tooltips in the diagram. Use the existing diagram-design draw.io verification scripts.
