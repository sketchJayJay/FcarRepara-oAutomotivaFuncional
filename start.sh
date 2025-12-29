#!/usr/bin/env bash
set -e

# Se você configurou um disco persistente no Render e definiu FCAR_DB_PATH,
# copie a oficina.db do repositório para o disco apenas na primeira execução.
if [[ -n "${FCAR_DB_PATH:-}" ]]; then
  mkdir -p "$(dirname "$FCAR_DB_PATH")"
  if [[ ! -f "$FCAR_DB_PATH" ]] && [[ -f "oficina.db" ]]; then
    cp "oficina.db" "$FCAR_DB_PATH"
  fi
fi

# 1 worker é mais seguro com SQLite (evita concorrência).
exec gunicorn wsgi:app --bind 0.0.0.0:${PORT:-5055} --workers 1
