# -*- coding: utf-8 -*-
"""
Restaura um banco SQLite a partir de um dump .sql (gerado pelo /export/backup.sql).

Uso:
  python RESTORE_DB_FROM_SQL_DUMP.py caminho/para/fcar_backup.sql

Opcional:
  FCAR_DB_PATH=/data/oficina.db python RESTORE_DB_FROM_SQL_DUMP.py fcar_backup.sql
"""
import os, sys, sqlite3

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "oficina.db")
DB_PATH = os.getenv("FCAR_DB_PATH") or os.getenv("DB_PATH") or DEFAULT_DB_PATH

def main():
    if len(sys.argv) < 2:
        print("Uso: python RESTORE_DB_FROM_SQL_DUMP.py fcar_backup.sql")
        sys.exit(1)

    dump_path = sys.argv[1]
    if not os.path.exists(dump_path):
        print("Arquivo não encontrado:", dump_path)
        sys.exit(1)

    # garante pasta do DB
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)

    # se já existir, não sobrescreve sem avisar
    if os.path.exists(DB_PATH):
        print("ATENÇÃO: já existe um banco em:", DB_PATH)
        print("Se você quer restaurar por cima, apague/renomeie esse arquivo primeiro.")
        sys.exit(2)

    with open(dump_path, "r", encoding="utf-8", errors="ignore") as f:
        sql = f.read()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()

    print("✅ Banco restaurado em:", DB_PATH)

if __name__ == "__main__":
    main()
