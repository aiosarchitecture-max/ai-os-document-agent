# Canvas storage authority

CAP-023 stores the authoritative canvas document in PostgreSQL through the authenticated `/canvas/document` API served by `app.main:app`.

`data/canvas_state.json` and direct GitHub commits are legacy behavior and must not be used for live canvas persistence. They are intentionally rejected by CI because they create split-brain state, bypass optimistic locking, and can overwrite data outside the application audit trail.

Operational rule: all canvas reads and writes go through the Render API and PostgreSQL. GitHub stores source code only.
