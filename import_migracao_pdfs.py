# -*- coding: utf-8 -*-
"""
Importador de PDFs do FCAR (Clientes.pdf, Estoque.pdf e OS #.pdf) para o banco SQLite.
Feito para acelerar a migração (sem digitar tudo na mão).

Uso:
  python import_migracao_pdfs.py --db data/oficina.db --pdfdir "/caminho/para/Nova pasta"

Observação:
- Para evitar "baixa dupla" de estoque nas OS antigas, este importador marca
  os itens vinculados no os_stock_applied (sem alterar o estoque atual).
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple

import fitz  # PyMuPDF

RE_OS_FILE = re.compile(r"OS\s*#\s*(\d+)\.pdf$", re.IGNORECASE)
RE_BRL = re.compile(r"[-+]?\d+(?:\.\d+)?(?:,\d+)?")

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def brl_to_float(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0
    s = s.replace("R$", "").strip()
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def parse_int(s: str) -> int:
    s = (s or "").strip()
    try:
        return int(float(s.replace(",", ".")))
    except Exception:
        return 0

def pdf_lines(path: str) -> List[str]:
    doc = fitz.open(path)
    lines: List[str] = []
    for page in doc:
        t = page.get_text("text")
        for ln in t.splitlines():
            ln = ln.rstrip()
            if ln.strip() == "":
                continue
            lines.append(ln.strip())
    doc.close()
    return lines

def join_hyphen_breaks(parts: List[str]) -> List[str]:
    """Junta tokens quebrados tipo '+55 32 99984-' + '1701'."""
    out: List[str] = []
    for ln in parts:
        if out and out[-1].endswith("-") and re.fullmatch(r"\d{2,}", ln):
            out[-1] = out[-1] + ln
        else:
            out.append(ln)
    return out

@dataclass
class ClientRow:
    name: str
    phone: str
    cpf: str

def parse_clients_pdf(path: str) -> List[ClientRow]:
    lines = pdf_lines(path)
    # A tabela vem depois de "Ações"
    try:
        start = lines.index("Ações") + 1
    except ValueError:
        # fallback: procurar por "Nome" e "Telefone"
        start = 0
    data = lines[start:]

    rec: List[str] = []
    out: List[ClientRow] = []

    def flush(rec_lines: List[str]):
        rec_lines = [r for r in rec_lines if r not in ("Abrir", "painel", "Editar")]
        rec_lines = join_hyphen_breaks(rec_lines)
        if not rec_lines:
            return
        # Esperado: name, phone, cpf (às vezes phone/cpf "-")
        name = rec_lines[0]
        phone = rec_lines[1] if len(rec_lines) > 1 else ""
        cpf = rec_lines[2] if len(rec_lines) > 2 else ""
        phone = "" if phone == "-" else phone
        cpf = "" if cpf == "-" else cpf
        out.append(ClientRow(norm_space(name), norm_space(phone), norm_space(cpf)))

    for ln in data:
        # cada registro termina em Editar
        if ln == "Editar":
            flush(rec)
            rec = []
            continue
        # ignora cabeçalhos repetidos
        if ln in ("Clientes", "Buscar por nome/telefone", "Buscar", "Novo Cliente", "Nome completo", "Telefone", "CPF", "Endereço", "Salvar", "Nome"):
            continue
        if ln in ("Telefone", "CPF"):
            continue
        rec.append(ln)

    # flush final (se sobrar)
    flush(rec)

    # remove duplicatas (mesmo nome + telefone)
    seen = set()
    uniq: List[ClientRow] = []
    for r in out:
        key = (r.name.lower(), r.phone)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq

@dataclass
class InventoryRow:
    name: str
    sku: str
    stock: int
    min_stock: int
    price: float

def looks_like_sku(token: str) -> bool:
    token = token.strip()
    if " " in token:
        return False
    return bool(re.fullmatch(r"[A-Z0-9_]{3,25}", token, re.IGNORECASE))

def parse_inventory_pdf(path: str) -> List[InventoryRow]:
    lines = pdf_lines(path)

    # começar após o cabeçalho da lista
    start = 0
    for i, ln in enumerate(lines):
        if ln == "Venda":
            start = i + 1
            break
    data = lines[start:]

    out: List[InventoryRow] = []
    i = 0
    while i < len(data):
        # pula lixos
        if data[i] in ("Itens cadastrados",) or data[i].endswith("itens listados"):
            i += 1
            continue

        # captura nome até achar sku com padrão e contexto numérico (stock/min/R$)
        name_parts: List[str] = []
        while i < len(data):
            tok = data[i]
            # pulo de colunas repetidas
            if tok in ("Nome", "SKU", "Estoque", "Mín.", "Mín", "Venda"):
                i += 1
                continue
            if looks_like_sku(tok):
                # validar contexto
                if i + 3 < len(data) and re.fullmatch(r"\d+(?:,\d+)?", data[i+1]) and re.fullmatch(r"\d+(?:,\d+)?", data[i+2]) and (data[i+3] == "R$" or data[i+3].startswith("R$")):
                    break
            name_parts.append(tok)
            i += 1

        if i >= len(data):
            break
        sku = data[i].strip()
        i += 1
        if i >= len(data):
            break
        stock = parse_int(data[i]); i += 1
        if i >= len(data):
            break
        min_stock = parse_int(data[i]); i += 1
        if i >= len(data):
            break

        # preço
        price = 0.0
        if data[i] == "R$":
            i += 1
            if i < len(data):
                price = brl_to_float(data[i]); i += 1
        else:
            # às vezes vem "R$ 10,00"
            price = brl_to_float(data[i]); i += 1

        name = norm_space(" ".join(name_parts))
        if name and sku:
            out.append(InventoryRow(name=name, sku=sku, stock=stock, min_stock=min_stock, price=price))

    # dedup por SKU
    uniq: Dict[str, InventoryRow] = {}
    for r in out:
        uniq[r.sku.upper()] = r
    return list(uniq.values())

@dataclass
class OSItem:
    description: str
    qty: float
    unit_price: float
    total: float
    is_labor: int
    inventory_id: Optional[int] = None

@dataclass
class OSRow:
    os_id: int
    client_name: str
    created_at: str
    plate: str
    model: str
    mechanic: str
    status: str
    pay_method: str
    pay_status: str
    notes: str
    base_labor: float
    items: List[OSItem]

def parse_os_pdf(path: str) -> OSRow:
    # usa o texto da primeira página (normalmente tem tudo)
    doc = fitz.open(path)
    text = "\n".join([p.get_text("text") for p in doc])
    doc.close()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # os_id
    m = re.search(r"OS\s*#\s*(\d+)", text)
    if not m:
        raise ValueError(f"Não achei o número da OS em {path}")
    os_id = int(m.group(1))

    # cliente: linha "OS #N — ..."
    client_name = ""
    for ln in lines:
        if "OS #" in ln and "—" in ln:
            # pode haver repetição, pega a primeira que parece completa
            part = ln.split("—", 1)[1]
            client_name = norm_space(part)
            break
    if not client_name:
        # fallback: "OS #N - cliente"
        for ln in lines:
            if ln.lower().startswith(f"os #{os_id}".lower()):
                client_name = norm_space(re.sub(r"^OS\s*#\s*\d+\s*[-—]\s*", "", ln, flags=re.I))
                break

    # data
    created_at = ""
    m = re.search(r"Data:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})", text)
    if m:
        created_at = m.group(1).strip()

    # veículo
    plate = ""
    model = ""
    # exemplo: "Veículo: GYX1512 Chevrolet\nMontana"
    for i, ln in enumerate(lines):
        if ln.startswith("Veículo:"):
            rest = norm_space(ln.replace("Veículo:", ""))
            # placa costuma ser a primeira palavra sem espaços
            parts = rest.split(" ")
            plate = parts[0].strip().upper() if parts else ""
            model = norm_space(" ".join(parts[1:])) if len(parts) > 1 else ""
            # se modelo quebrar linha, junta mais uma
            if i + 1 < len(lines) and lines[i+1] not in ("Mecânico:", "Status:", "Pagamento:", "Observações:"):
                # só junta se não for um label
                if not re.match(r"^(Mecânico|Status|Pagamento|Observações)\s*:", lines[i+1]):
                    model = norm_space((model + " " + lines[i+1]).strip())
            break

    # mecânico
    mechanic = ""
    m = re.search(r"Mecânico:\s*(.+)", text)
    if m:
        mechanic = norm_space(m.group(1))

    # status
    status = ""
    m = re.search(r"Status:\s*(.+)", text)
    if m:
        status = norm_space(m.group(1))

    # pagamento: pode quebrar linha "Pagamento: Dinheiro /\nEfetivado"
    pay_method = "Dinheiro"
    pay_status = "Pendente"
    # tenta pegar o bloco após "Pagamento:"
    pidx = None
    for i, ln in enumerate(lines):
        if ln.startswith("Pagamento:"):
            pidx = i
            break
    if pidx is not None:
        raw = norm_space(lines[pidx].replace("Pagamento:", ""))
        if pidx + 1 < len(lines) and "/" in raw and raw.endswith("/"):
            raw = norm_space(raw + " " + lines[pidx+1])
        if "/" in raw:
            a, b = raw.split("/", 1)
            pay_method = norm_space(a)
            pay_status = norm_space(b)
        else:
            pay_method = raw or pay_method

    # observações
    notes = ""
    m = re.search(r"Observações:\s*(.+)", text)
    if m:
        notes = norm_space(m.group(1))

    # tabelas: usar os blocos do texto
    # partes: entre "Peças utilizadas" e "Subtotal peças"
    items: List[OSItem] = []
    base_labor = 0.0

    def parse_table(section_start: str, section_end: str) -> List[Tuple[str, float, float, float]]:
        """Retorna lista (desc, qty, unit, total)."""
        try:
            si = lines.index(section_start)
        except ValueError:
            return []
        # pular cabeçalho 'Peça Qtd Unit Total' ou similar
        j = si + 1
        # avançar até achar linha que seja 'Peça'/'Serviço'
        while j < len(lines) and lines[j] not in ("Peça", "Serviço"):
            j += 1
        # pular linhas de cabeçalho (Peça/Serviço, Qtd, Unit, Total)
        while j < len(lines) and lines[j] in ("Peça", "Serviço", "Qtd", "Unit", "Total", "QTD", "UNIT", "TOTAL"):
            j += 1
        # agora, lê linhas até achar section_end
        rows = []
        buf = []
        while j < len(lines):
            if lines[j].startswith(section_end):
                break
            if lines[j] == section_end:
                break
            if section_end in lines[j]:
                break
            buf.append(lines[j])
            j += 1

        # varre tokens: descrição (pode ter várias linhas) + qty numérica + unit + total
        k = 0
        while k < len(buf):
            desc_parts = []
            while k < len(buf) and not re.fullmatch(r"\d+(?:\.\d+)?", buf[k]):
                desc_parts.append(buf[k])
                k += 1
            if k >= len(buf):
                break
            qty = float(buf[k]); k += 1

            unit_tok = ""
            if k < len(buf):
                unit_tok = buf[k]; k += 1
                if unit_tok == "R$" and k < len(buf):
                    unit_tok = "R$ " + buf[k]; k += 1

            tot_tok = ""
            if k < len(buf):
                tot_tok = buf[k]; k += 1
                if tot_tok == "R$" and k < len(buf):
                    tot_tok = "R$ " + buf[k]; k += 1

            desc = norm_space(" ".join(desc_parts))
            if not desc:
                continue
            rows.append((desc, qty, brl_to_float(unit_tok), brl_to_float(tot_tok)))
        return rows

    pecas_rows = parse_table("Peças utilizadas (saída do estoque)", "Subtotal peças")
    for desc, qty, unit, tot in pecas_rows:
        items.append(OSItem(description=desc, qty=qty, unit_price=unit, total=tot, is_labor=0))

    serv_rows = parse_table("Serviços (entrada)", "Subtotal serviços")
    for desc, qty, unit, tot in serv_rows:
        if desc.strip().lower() in ("mão de obra", "mao de obra"):
            base_labor = tot if tot else unit * qty
        else:
            items.append(OSItem(description=desc, qty=qty, unit_price=unit, total=tot, is_labor=1))

    return OSRow(
        os_id=os_id,
        client_name=client_name or f"Cliente OS {os_id}",
        created_at=created_at or "",
        plate=plate or "",
        model=model or "",
        mechanic=mechanic or "",
        status=status or "Fechada",
        pay_method=pay_method or "Dinheiro",
        pay_status=pay_status or "Pendente",
        notes=notes or "",
        base_labor=float(base_labor or 0),
        items=items,
    )

def ensure_schema(db: sqlite3.Connection):
    # Tabelas mínimas já existem no projeto, mas garante colunas
    # (Se o usuário estiver migrando de um banco antigo sem cpf/endereço)
    try:
        cols = [r[1] for r in db.execute("PRAGMA table_info(clients)").fetchall()]
        if "cpf" not in cols:
            db.execute("ALTER TABLE clients ADD COLUMN cpf TEXT")
        if "address" not in cols:
            db.execute("ALTER TABLE clients ADD COLUMN address TEXT")
    except Exception:
        pass

def get_or_create_client(db: sqlite3.Connection, name: str, phone: str = "", cpf: str = "") -> int:
    name = norm_space(name)
    phone = norm_space(phone)
    cpf = norm_space(cpf)
    row = db.execute("SELECT id, phone, cpf FROM clients WHERE LOWER(name)=LOWER(?) LIMIT 1", (name,)).fetchone()
    if row:
        cid = int(row[0])
        # atualiza se estiver faltando
        if (not row[1] and phone) or (not row[2] and cpf):
            db.execute("UPDATE clients SET phone=COALESCE(NULLIF(phone,''),?), cpf=COALESCE(NULLIF(cpf,''),?) WHERE id=?",
                       (phone, cpf, cid))
        return cid
    cur = db.execute("INSERT INTO clients(name, phone, cpf, address) VALUES (?,?,?,?)", (name, phone, cpf, ""))
    return int(cur.lastrowid)

def get_or_create_vehicle(db: sqlite3.Connection, client_id: int, plate: str, model: str) -> Optional[int]:
    plate = norm_space(plate).upper()
    model = norm_space(model)
    if not plate and not model:
        return None
    if plate:
        row = db.execute("SELECT id FROM vehicles WHERE client_id=? AND plate=? LIMIT 1", (client_id, plate)).fetchone()
        if row:
            return int(row[0])
    cur = db.execute("INSERT INTO vehicles(client_id, plate, model, year) VALUES (?,?,?,?)",
                     (client_id, plate or None, model or None, None))
    return int(cur.lastrowid)

def get_or_create_mechanic(db: sqlite3.Connection, name: str) -> Optional[int]:
    name = norm_space(name)
    if not name:
        return None
    row = db.execute("SELECT id FROM mechanics WHERE LOWER(name)=LOWER(?) LIMIT 1", (name,)).fetchone()
    if row:
        return int(row[0])
    cur = db.execute("INSERT INTO mechanics(name) VALUES (?)", (name,))
    return int(cur.lastrowid)

def find_inventory_id_by_name(db: sqlite3.Connection, desc: str) -> Optional[int]:
    d = norm_space(desc)
    if not d:
        return None
    row = db.execute("SELECT id FROM inventory WHERE LOWER(name)=LOWER(?) LIMIT 1", (d,)).fetchone()
    if row:
        return int(row[0])
    # fallback: contém (bem simples)
    row = db.execute("SELECT id FROM inventory WHERE LOWER(name) LIKE LOWER(?) LIMIT 1", (f"%{d}%",)).fetchone()
    if row:
        return int(row[0])
    return None

def upsert_inventory(db: sqlite3.Connection, row: InventoryRow):
    sku = row.sku.strip().upper()
    # sku é UNIQUE
    db.execute(
        "INSERT OR IGNORE INTO inventory(name, sku, stock, min_stock, price, is_labor, cost_price, repasse_value) VALUES (?,?,?,?,?,?,?,?)",
        (row.name, sku, int(row.stock), int(row.min_stock), float(row.price), 0, 0.0, 0.0),
    )
    db.execute(
        "UPDATE inventory SET name=?, stock=?, min_stock=?, price=? WHERE sku=?",
        (row.name, int(row.stock), int(row.min_stock), float(row.price), sku),
    )

def ensure_fin_seed(db: sqlite3.Connection):
    # métodos
    methods = ["Dinheiro", "Pix", "Cartão", "Cartao", "Boleto"]
    for m in methods:
        try:
            db.execute("INSERT OR IGNORE INTO fin_payment_methods(name) VALUES (?)", (m,))
        except Exception:
            pass
    # categoria
    try:
        db.execute("INSERT OR IGNORE INTO fin_categories(name, kind) VALUES (?,?)", ("Serviços / OS", "in"))
    except Exception:
        pass

def get_method_id(db: sqlite3.Connection, name: str) -> Optional[int]:
    name = norm_space(name) or "Dinheiro"
    row = db.execute("SELECT id FROM fin_payment_methods WHERE LOWER(name)=LOWER(?) LIMIT 1", (name,)).fetchone()
    if row:
        return int(row[0])
    cur = db.execute("INSERT INTO fin_payment_methods(name) VALUES (?)", (name,))
    return int(cur.lastrowid)

def get_category_id(db: sqlite3.Connection, name: str) -> Optional[int]:
    name = norm_space(name) or "Serviços / OS"
    row = db.execute("SELECT id FROM fin_categories WHERE LOWER(name)=LOWER(?) LIMIT 1", (name,)).fetchone()
    if row:
        return int(row[0])
    cur = db.execute("INSERT INTO fin_categories(name, kind) VALUES (?,?)", (name, "in"))
    return int(cur.lastrowid)

def tx_status_from_pay(pay_status: str, os_status: str) -> str:
    ps = (pay_status or "").strip().lower()
    st = (os_status or "").strip().lower()
    if st in ("cancelada", "cancelado"):
        return "CANCELADO"
    if ps in ("efetivado", "pago", "paga", "quitado"):
        return "EFETIVADO"
    return "PENDENTE"

def is_consuming_status(os_status: str) -> bool:
    s = (os_status or "").strip().lower()
    if s in ("em andamento", "andamento", "em execução", "em execucao", "executando"):
        return True
    return s in ("fechada","fechado","finalizada","finalizado","concluida","concluída","concluido","concluído")

def rebuild_fin_items(db: sqlite3.Connection, tx_id: int, items: List[Tuple[str,str,Optional[int],str,float,float,float]]):
    db.execute("DELETE FROM fin_transaction_items WHERE tx_id=?", (tx_id,))
    now = "import"
    db.executemany(
        "INSERT INTO fin_transaction_items(tx_id, flow, direction, inventory_id, description, qty, unit_value, total, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        [(tx_id, flow, direction, inv_id, desc, qty, unit, total, now) for (flow, direction, inv_id, desc, qty, unit, total) in items],
    )

def upsert_fin_from_os(db: sqlite3.Connection, osr: OSRow, client_name: str):
    # total
    items_total = sum(float(it.total or 0) for it in osr.items)
    total = float(osr.base_labor or 0) + float(items_total or 0)

    desc = f"OS #{osr.os_id}" + (f" - {client_name}" if client_name else "")
    tx_date = (osr.created_at.split(" ")[0] if osr.created_at else "")
    if not tx_date:
        tx_date = "2026-01-01"  # fallback neutro

    method_id = get_method_id(db, osr.pay_method or "Dinheiro")
    cat_id = get_category_id(db, "Serviços / OS")
    tx_status = tx_status_from_pay(osr.pay_status, osr.status)

    row = db.execute("SELECT id FROM fin_transactions WHERE ref_type='OS' AND ref_id=? LIMIT 1", (osr.os_id,)).fetchone()
    if row:
        tx_id = int(row[0])
        db.execute(
            "UPDATE fin_transactions SET description=?, amount=?, date=?, due_date=?, status=?, payment_method_id=?, category_id=?, updated_at=? WHERE id=?",
            (desc, total, tx_date, tx_date, tx_status, method_id, cat_id, "import", tx_id),
        )
    else:
        cur = db.execute(
            "INSERT INTO fin_transactions(ttype, description, amount, date, due_date, status, payment_method_id, category_id, ref_type, ref_id, created_at) VALUES ('IN',?,?,?,?,?,?,?,?,?,?)",
            (desc, total, tx_date, tx_date, tx_status, method_id, cat_id, "OS", osr.os_id, "import"),
        )
        tx_id = int(cur.lastrowid)

    # itens
    fin_items: List[Tuple[str,str,Optional[int],str,float,float,float]] = []
    if osr.base_labor:
        fin_items.append(("money","IN",None,"Mão de obra",1.0,float(osr.base_labor),float(osr.base_labor)))
    for it in osr.items:
        fin_items.append(("money","IN",it.inventory_id, it.description, float(it.qty or 1), float(it.unit_price or 0), float(it.total or 0)))
        if is_consuming_status(osr.status) and it.inventory_id and it.is_labor == 0:
            fin_items.append(("stock","OUT",it.inventory_id, it.description, float(it.qty or 1), 0.0, 0.0))
    rebuild_fin_items(db, tx_id, fin_items)

    # vincula na OS
    try:
        db.execute("UPDATE orders SET fin_tx_id=? WHERE id=?", (tx_id, osr.os_id))
    except Exception:
        pass

def upsert_os(db: sqlite3.Connection, osr: OSRow, client_id: int, vehicle_id: Optional[int], mech_id: Optional[int]):
    # inserir/atualizar OS com id fixo
    row = db.execute("SELECT id FROM orders WHERE id=? LIMIT 1", (osr.os_id,)).fetchone()
    if row:
        db.execute(
            "UPDATE orders SET client_id=?, vehicle_id=?, created_at=?, status=?, notes=?, labor=?, mechanic_id=?, pay_method=?, pay_status=? WHERE id=?",
            (client_id, vehicle_id, osr.created_at, osr.status, osr.notes, float(osr.base_labor), mech_id, osr.pay_method, osr.pay_status, osr.os_id),
        )
        db.execute("DELETE FROM order_items WHERE order_id=?", (osr.os_id,))
    else:
        db.execute(
            "INSERT INTO orders(id, client_id, vehicle_id, created_at, status, notes, labor, mechanic_id, pay_method, pay_status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (osr.os_id, client_id, vehicle_id, osr.created_at, osr.status, osr.notes, float(osr.base_labor), mech_id, osr.pay_method, osr.pay_status),
        )

    # insere itens
    for it in osr.items:
        db.execute(
            "INSERT INTO order_items(order_id, inventory_id, description, qty, unit_price, total, is_labor) VALUES (?,?,?,?,?,?,?)",
            (osr.os_id, it.inventory_id, it.description, float(it.qty), float(it.unit_price), float(it.total), int(it.is_labor)),
        )

def set_os_stock_applied(db: sqlite3.Connection, os_id: int, items: List[OSItem], status: str):
    if not is_consuming_status(status):
        return
    desired: Dict[int, float] = {}
    for it in items:
        if it.inventory_id and it.is_labor == 0:
            desired[int(it.inventory_id)] = desired.get(int(it.inventory_id), 0.0) + float(it.qty or 0)

    # marca aplicado sem mexer no estoque
    db.execute("DELETE FROM os_stock_applied WHERE os_id=?", (os_id,))
    for inv_id, qty in desired.items():
        db.execute("INSERT INTO os_stock_applied(os_id, inventory_id, qty, updated_at) VALUES (?,?,?,?)", (os_id, inv_id, qty, "import"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Caminho do banco (SQLite)")
    ap.add_argument("--pdfdir", required=True, help="Pasta com Clientes.pdf / Estoque.pdf / OS #.pdf")
    args = ap.parse_args()

    db_path = args.db
    pdfdir = args.pdfdir

    if not os.path.exists(db_path):
        raise SystemExit(f"Banco não encontrado: {db_path}")

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=ON")
    ensure_schema(con)

    # inventário
    inv_pdf = os.path.join(pdfdir, "Estoque.pdf")
    if os.path.exists(inv_pdf):
        inv_rows = parse_inventory_pdf(inv_pdf)
        for r in inv_rows:
            upsert_inventory(con, r)
        print(f"[OK] Estoque importado/atualizado: {len(inv_rows)} itens")
    else:
        print("[WARN] Estoque.pdf não encontrado, pulando...")

    # clientes
    cl_pdf = os.path.join(pdfdir, "Clientes.pdf")
    clients: List[ClientRow] = []
    if os.path.exists(cl_pdf):
        clients = parse_clients_pdf(cl_pdf)
        for c in clients:
            get_or_create_client(con, c.name, c.phone, c.cpf)
        print(f"[OK] Clientes importados/atualizados: {len(clients)}")
    else:
        print("[WARN] Clientes.pdf não encontrado, pulando...")

    # financeiro seeds
    ensure_fin_seed(con)

    # OS
    os_files = []
    for fn in os.listdir(pdfdir):
        m = RE_OS_FILE.search(fn)
        if m:
            os_files.append((int(m.group(1)), os.path.join(pdfdir, fn)))
    os_files.sort(key=lambda x: x[0])

    imported = 0
    for os_num, path in os_files:
        try:
            osr = parse_os_pdf(path)
        except Exception as e:
            print("[ERRO] parse", os_num, "->", e)
            continue

        # cliente
        cid = get_or_create_client(con, osr.client_name)
        vid = get_or_create_vehicle(con, cid, osr.plate, osr.model)
        mid = get_or_create_mechanic(con, osr.mechanic)

        # vincula peças ao estoque (match simples)
        for it in osr.items:
            if it.is_labor == 0:
                it.inventory_id = find_inventory_id_by_name(con, it.description)

        upsert_os(con, osr, cid, vid, mid)
        set_os_stock_applied(con, osr.os_id, osr.items, osr.status)

        # financeiro por OS
        cname = con.execute("SELECT name FROM clients WHERE id=?", (cid,)).fetchone()
        cname = cname[0] if cname else osr.client_name
        upsert_fin_from_os(con, osr, cname)

        imported += 1

    con.commit()
    con.close()
    print(f"[OK] OS importadas/atualizadas: {imported}")

if __name__ == "__main__":
    main()
