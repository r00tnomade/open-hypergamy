"""Regenerate migrations/migration_manifest.json. Run only when ADDING a migration."""

import hashlib
import json
import re
from pathlib import Path

d = Path(__file__).resolve().parents[1] / "migrations"
entries = []
for p in sorted(d.glob("*.sql")):
    m = re.match(r"^(\d{4})_([a-z0-9_]+)\.sql$", p.name)
    assert m, p.name
    entries.append(
        {"version": int(m[1]), "name": m[2], "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    )
(d / "migration_manifest.json").write_text(json.dumps({"migrations": entries}, indent=2) + "\n")
print(f"{len(entries)} migration(s) in manifest")
