#!/usr/bin/env sh
set -e

: "${PORT:=5055}"
: "${DB_PATH:=/data/oficina.db}"

# Se estiver usando volume e o DB ainda não existe, copia o seed (com dados) uma única vez.
if [ ! -f "$DB_PATH" ]; then
  if [ -f "/app/seed/oficina.db" ]; then
    mkdir -p "$(dirname "$DB_PATH")"
    cp "/app/seed/oficina.db" "$DB_PATH"
    echo "[OK] Banco seed copiado para $DB_PATH"
  fi
fi

# Inicia via wsgi.py para garantir init_db() na inicialização.
exec gunicorn -b 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120 wsgi:app
