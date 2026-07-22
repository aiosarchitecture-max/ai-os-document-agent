# AI_OS target architecture

## Control plane

The FastAPI Sprostredkovateľ owns workflow decisions. PostgreSQL owns current operational state. Every mutation emits an audit event.

## Knowledge plane

Google Drive contains canonical documents. `document_registry` records authority, lifecycle state, location, version, and checksum. Retrieval must prefer active canonical documents and attach citations to every generated context package.

## Agent plane

The standard lifecycle is:

`NEW → RESEARCH → CREATION → OPPOSITION → REVIEW → APPROVAL → DONE`

Rework, blocked, failed, cancelled, retry, and timeout paths are explicit states. Sub-agent output is DRAFT until approved.

## Integration plane

Apps Script is a least-privilege adapter for Google-native operations. GitHub owns source. Render hosts compute and PostgreSQL. External integrations enter through authenticated adapters and idempotent commands.

## Migration principle

Use a strangler migration. Keep the current bridge available for Google-native document operations while the durable core owns task state in PostgreSQL. Google Sheets is not a second task database; any future task register is a one-way, replaceable projection from PostgreSQL. The legacy dual-write flag remains disabled.
