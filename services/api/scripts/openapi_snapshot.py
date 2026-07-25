"""Write or verify the checked-in OpenAPI snapshot.

`docs/api/openapi.json` is the contract the TypeScript clients are generated from. Nothing
stops a Pydantic schema change from silently diverging from it, so CI verifies the snapshot
still matches the application and fails when it does not.

    python -m scripts.openapi_snapshot --check    # CI: exit 1 on drift
    python -m scripts.openapi_snapshot --write    # developer: refresh the snapshot

Deliberately builds the app in-process rather than fetching from a running server: the check
must work in CI without a live service, and an in-process dump cannot race a stale process.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.core.config import Environment, Settings
from app.main import create_app

SNAPSHOT_PATH = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"


def current_schema() -> dict[str, Any]:
    """The schema as the application defines it right now.

    Built with explicit local settings so the dump never depends on the developer's
    environment — and so `docs_enabled` is on, which is what exposes the schema at all.
    """
    app = create_app(Settings(STUDY_ENV=Environment.LOCAL))
    schema: dict[str, Any] = app.openapi()
    return schema


def _serialise(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write() -> int:
    SNAPSHOT_PATH.write_text(_serialise(current_schema()), encoding="utf-8")
    print(f"Wrote {SNAPSHOT_PATH}")
    return 0


def check() -> int:
    live = current_schema()
    if not SNAPSHOT_PATH.exists():
        print(f"Missing snapshot: {SNAPSHOT_PATH}", file=sys.stderr)
        print("Run: python -m scripts.openapi_snapshot --write", file=sys.stderr)
        return 1

    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if live == snapshot:
        print(f"OpenAPI snapshot is current ({len(live['paths'])} paths).")
        return 0

    print("OpenAPI snapshot is out of date.", file=sys.stderr)
    for label, diff in (
        ("added", sorted(set(live["paths"]) - set(snapshot["paths"]))),
        ("removed", sorted(set(snapshot["paths"]) - set(live["paths"]))),
    ):
        if diff:
            print(f"  paths {label}: {', '.join(diff)}", file=sys.stderr)
    print(
        "\nRegenerate it and re-run the client codegen:\n"
        "  python -m scripts.openapi_snapshot --write\n"
        "  npm run generate:api",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Fail if the snapshot has drifted.")
    group.add_argument("--write", action="store_true", help="Refresh the snapshot in place.")
    args = parser.parse_args()
    return check() if args.check else write()


if __name__ == "__main__":
    raise SystemExit(main())
