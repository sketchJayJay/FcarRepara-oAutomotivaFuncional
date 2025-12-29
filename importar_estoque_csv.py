"""Importador simples de estoque para o FCAR.

✅ Melhorias desta versão:
- Se 'estoque.csv' não existir, o script tenta localizar automaticamente qualquer .csv na pasta.
- Aceita passar o arquivo por argumento:
    python importar_estoque_csv.py meu_estoque.csv
- Se não encontrar nenhum CSV, ele cria 'estoque.csv' a partir do 'estoque_modelo.csv'.

Como usar (recomendado):
1) Rode o FCAR pelo menos 1 vez (para criar o arquivo 'oficina.db').
2) Rode o criador de CSV (opcional): CRIAR_ESTOQUE_CSV.bat
3) Importar: IMPORTAR_ESTOQUE.bat   (ou: python importar_estoque_csv.py)

Formato do CSV:
- Separador: ';' (recomendado) ou ','
- Colunas esperadas (mínimo): sku, name, stock, cost_price, price
- Opcional: min_stock

Obs: Se o SKU já existir, o script cria um SKU alternativo (ex: ABC-2).
"""

import csv
import os
import re
import sqlite3
import sys
from glob import glob

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "oficina.db")
DEFAULT_CSV = os.path.join(BASE_DIR, "estoque.csv")
MODEL_CSV = os.path.join(BASE_DIR, "estoque_modelo.csv")


def to_float(v: str) -> float:
    if v is None:
        return 0.0
    v = str(v).strip()
    if not v:
        return 0.0

    # normaliza moeda BR
    v = v.replace("R$", "").replace(" ", "")
    v = v.replace(".", "").replace(",", ".")

    try:
        return float(v)
    except ValueError:
        # pega primeiro número que aparecer
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        return float(m.group(0)) if m else 0.0


def to_int(v: str) -> int:
    if v is None:
        return 0
    v = str(v).strip()
    if not v:
        return 0
    v = v.replace(".", "")
    m = re.search(r"-?\d+", v)
    return int(m.group(0)) if m else 0


def detect_delimiter(sample: str) -> str:
    # prefer ';'
    if sample.count(';') >= sample.count(','):
        return ';'
    return ','


def ensure_db_exists():
    if os.path.exists(DB_PATH):
        return
    raise SystemExit(
        "❌ Não achei o arquivo 'oficina.db'.\n"
        "Abra o FCAR pelo menos 1 vez para ele criar o banco, e depois rode a importação de novo."
    )


def unique_sku(cur, sku: str) -> str:
    base = (sku or "").strip() or "SKU"
    n = 2
    while True:
        cur.execute("SELECT 1 FROM inventory WHERE sku = ?", (base,))
        if not cur.fetchone():
            return base
        base = f"{base.split('-')[0]}-{n}"
        n += 1


def pick_csv_path() -> str:
    # 1) argumento
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        p = sys.argv[1].strip().strip('"').strip("'")
        if not os.path.isabs(p):
            p = os.path.join(BASE_DIR, p)
        if os.path.exists(p) and p.lower().endswith(".csv"):
            return p
        raise SystemExit(f"❌ Arquivo não encontrado ou inválido: {p}")

    # 2) estoque.csv padrão
    if os.path.exists(DEFAULT_CSV):
        return DEFAULT_CSV

    # 3) tenta localizar algum csv na pasta
    csvs = [p for p in glob(os.path.join(BASE_DIR, "*.csv"))]
    csvs = [p for p in csvs if os.path.basename(p).lower() not in ("estoque_modelo.csv",)]
    if len(csvs) == 1:
        print(f"ℹ️ Não achei 'estoque.csv'. Vou usar automaticamente: {os.path.basename(csvs[0])}")
        return csvs[0]
    if len(csvs) > 1:
        # pega o mais recente, mas avisa
        csvs_sorted = sorted(csvs, key=lambda x: os.path.getmtime(x), reverse=True)
        chosen = csvs_sorted[0]
        print("⚠️ Encontrei mais de um CSV na pasta. Vou usar o mais recente:")
        for p in csvs_sorted:
            print(" -", os.path.basename(p))
        print("✅ Usando:", os.path.basename(chosen))
        print("Dica: se quiser escolher outro, rode assim:")
        print('python importar_estoque_csv.py "NOME_DO_ARQUIVO.csv"')
        return chosen

    # 4) nenhum csv: cria estoque.csv a partir do modelo (se existir)
    if os.path.exists(MODEL_CSV):
        try:
            with open(MODEL_CSV, "rb") as src, open(DEFAULT_CSV, "wb") as dst:
                dst.write(src.read())
            raise SystemExit(
                "❌ Não encontrei nenhum CSV preenchido.\n"
                "✅ Criei 'estoque.csv' a partir do 'estoque_modelo.csv'.\n"
                "Abra e preencha o estoque.csv e depois rode novamente a importação."
            )
        except Exception as e:
            raise SystemExit(f"❌ Falha ao criar 'estoque.csv' a partir do modelo: {e}")

    raise SystemExit("❌ Não achei nenhum CSV e também não existe 'estoque_modelo.csv' para gerar um modelo.")


def get(row: dict, *keys):
    # tenta buscar por várias chaves possíveis
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    # tenta por lower/strip
    lower_map = { (str(a).strip().lower()): b for a, b in row.items() }
    for k in keys:
        lk = str(k).strip().lower()
        if lk in lower_map and lower_map[lk] not in (None, ""):
            return lower_map[lk]
    return ""


def main():
    ensure_db_exists()
    csv_path = pick_csv_path()

    # lê um pedacinho para detectar separador
    with open(csv_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
        sample = f.read(2048)
        delim = detect_delimiter(sample)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    inserted = 0
    updated = 0

    with open(csv_path, 'r', encoding='utf-8-sig', errors='ignore', newline='') as f:
        reader = csv.DictReader(f, delimiter=delim)

        if not reader.fieldnames:
            raise SystemExit("❌ CSV sem cabeçalho. Use o estoque_modelo.csv como base.")

        for row in reader:
            sku = str(get(row, 'sku', 'código', 'codigo', 'cod', 'ref')).strip()
            name = str(get(row, 'name', 'descrição', 'descricao', 'produto', 'descrição do produto')).strip()
            stock = to_int(get(row, 'stock', 'qtd', 'quantidade'))
            cost_price = to_float(get(row, 'cost_price', 'custo', 'unit.(r$)', 'unit', 'unitario', 'unitário'))
            price = to_float(get(row, 'price', 'preço', 'preco', 'valor', 'vl. item(r$)', 'vl item'))

            min_stock = to_int(get(row, 'min_stock', 'estoque mínimo', 'estoque minimo', 'minimo', 'mínimo'))

            if price == 0 and cost_price != 0:
                price = cost_price

            if not name:
                name = f"Item {sku}" if sku else "Item"

            cur.execute("SELECT id FROM inventory WHERE sku = ?", ((sku or '').strip(),))
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """UPDATE inventory
                       SET name = ?, stock = ?, min_stock = ?, price = ?, cost_price = ?, is_labor = 0, repasse_value = 0
                       WHERE id = ?""",
                    (name.strip(), stock, min_stock, price, cost_price, existing['id'])
                )
                updated += 1
            else:
                sku_final = unique_sku(cur, sku)
                cur.execute(
                    """INSERT INTO inventory(name, sku, stock, min_stock, price, is_labor, cost_price, repasse_value)
                       VALUES(?,?,?,?,?,0,?,0)""",
                    (name.strip(), sku_final, stock, min_stock, price, cost_price)
                )
                inserted += 1

    con.commit()
    con.close()

    print(f"✅ Importação concluída! Inseridos: {inserted} | Atualizados: {updated}")
    print("Arquivo usado:", os.path.basename(csv_path))


if __name__ == '__main__':
    main()
