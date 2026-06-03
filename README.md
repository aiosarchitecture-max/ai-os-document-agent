[README.md](https://github.com/user-attachments/files/28571836/README.md)
# AI_OS Document Agent v0.7.2 Relation Compact Fix

Fixes:
- /create-relation now returns ultra-compact JSON
- avoids ResponseTooLargeError for relation creation
- keeps create-entity, create-project, append-note, find-by-id, get-relations, get-object
- keeps UTC + Europe/Bratislava timestamps

Temporary test mode:
- Authorization is disabled in _check_token().
- Restore x-ai-os-token before production/public use.
