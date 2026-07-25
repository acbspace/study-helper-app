"""Column types that behave identically on PostgreSQL and SQLite.

See ADR-0003: production runs PostgreSQL; the default test engine is SQLite, so models
must not depend on dialect-only types.
"""

from __future__ import annotations

from sqlalchemy import JSON, DateTime, Uuid
from sqlalchemy.dialects.postgresql import JSONB

# Timezone-aware everywhere; storage is always UTC (docs/architecture/SYSTEM_DESIGN.md §4).
UtcDateTime = DateTime(timezone=True)

# JSONB where available, plain JSON elsewhere.
JsonDocument = JSON().with_variant(JSONB(), "postgresql")

# Native uuid on PostgreSQL, CHAR(32) on SQLite — same Python type either way.
UuidType = Uuid(as_uuid=True)
