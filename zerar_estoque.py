import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "oficina.db")

if not os.path.exists(DB_PATH):
    raise SystemExit("❌ Não achei o 'oficina.db'. Abra o FCAR pelo menos 1 vez pra ele criar o banco.")

con = sqlite3.connect(DB_PATH)
cur = con.cursor()
cur.execute("DELETE FROM inventory;")
con.commit()
con.close()

print("✅ Estoque zerado com sucesso!")
