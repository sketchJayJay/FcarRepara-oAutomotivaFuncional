#!/usr/bin/env sh
set -e

: "${PORT:=5055}"
: "${DB_PATH:=/data/oficina.db}"
: "${FORCE_SEED:=0}"

copy_seed() {
  if [ -f "/app/seed/oficina.db" ]; then
    mkdir -p "$(dirname "$DB_PATH")"
    cp "/app/seed/oficina.db" "$DB_PATH"
    echo "[OK] Banco seed copiado para $DB_PATH"
  else
    echo "[WARN] Seed /app/seed/oficina.db não encontrado."
  fi
}

# Se quiser sobrescrever o banco do volume (use com cuidado), defina FORCE_SEED=1
if [ "$FORCE_SEED" = "1" ] || [ "$FORCE_SEED" = "true" ] || [ "$FORCE_SEED" = "TRUE" ]; then
  echo "[INFO] FORCE_SEED ativado: sobrescrevendo $DB_PATH com o seed."
  copy_seed
else
  # Se estiver usando volume e o DB ainda não existe, copia o seed (com dados) uma única vez.
  if [ ! -f "$DB_PATH" ]; then
    copy_seed
  fi
fi

# Inicia via wsgi.py para garantir init_db() na inicialização.
exec gunicorn -b 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120 wsgi:app
