#!/usr/bin/env bash
set -euo pipefail

# Respeita os dois nomes já usados nas instalações da FCAR.
fcar_target_path="${FCAR_DB_PATH:-${DB_PATH:-}}"
if [[ -n "$fcar_target_path" ]]; then
  export FCAR_DB_PATH="$fcar_target_path"
  export DB_PATH="$fcar_target_path"
  python - <<'PY'
import os
from pathlib import Path
import sqlite3
import tempfile

target = Path(os.environ["FCAR_DB_PATH"]).expanduser()
source = Path("oficina.db")
target.parent.mkdir(parents=True, exist_ok=True)
# Nunca substitui um banco que já esteja no volume.
if not target.exists() and source.is_file() and source.resolve() != target.resolve():
    handle, temporary = tempfile.mkstemp(prefix=".fcar-seed-", dir=target.parent)
    os.close(handle)
    try:
        with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
            with sqlite3.connect(temporary) as destination:
                original.backup(destination)
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        Path(temporary).unlink(missing_ok=True)
PY
fi
exec gunicorn wsgi:app --bind "0.0.0.0:${PORT:-5055}" --workers 1 --timeout 120
