[README.md](https://github.com/user-attachments/files/28561890/README.md)
# AI_OS Document Agent v0.7.1 Compact Responses

Fixes:
- Reduces GPT Action response size to avoid ResponseTooLargeError
- Adds /create-entity endpoint
- Keeps /create-relation, /get-relations, /get-object
- Keeps UTC + Europe/Bratislava timestamps
- Keeps object IDs

Temporary test mode:
- Authorization is disabled in _check_token().
- Restore x-ai-os-token before production/public use.
