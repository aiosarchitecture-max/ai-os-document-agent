[README.md](https://github.com/user-attachments/files/28560555/README.md)
# AI_OS Document Agent v0.6.0

Adds:
- Unique object IDs: NOTE-YYYYMMDD-0001, PROJECT-YYYYMMDD-0001, DECISION-YYYYMMDD-0001
- Metadata block for every object
- UTC + Europe/Bratislava timestamps
- Entity registry support
- Basic relation support
- find-by-id endpoint
- list-projects, list-decisions, list-notes endpoints

Temporary test mode:
- Authorization is disabled in _check_token().
- Restore x-ai-os-token before production/public use.
