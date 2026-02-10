# -*- coding: utf-8 -*-
from __future__ import annotations
import os, sqlite3, datetime, io, socket, csv
import qrcode
from flask import Flask, g, render_template, request, redirect, url_for, flash, jsonify, send_file, session
import functools


try:
    import qrcode  # pip install qrcode[pil]
except Exception:
    qrcode = None
APP_TITLE = "FCAR Reparação Automotiva"
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "oficina.db")
DB_PATH = os.getenv("FCAR_DB_PATH") or os.getenv("DB_PATH") or DEFAULT_DB_PATH
app = Flask(__name__)
app.secret_key = "dev-2cp-mec"

def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        # garante pasta do banco (quando FCAR_DB_PATH aponta para um volume/disco)
        try:
            d = os.path.dirname(DB_PATH)
            if d:
                os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_db(_exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clients(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    cpf TEXT,
    address TEXT
);
CREATE TABLE IF NOT EXISTS vehicles(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    plate TEXT,
    model TEXT,
    year INTEGER,
    FOREIGN KEY(client_id) REFERENCES clients(id)
);
CREATE TABLE IF NOT EXISTS inventory(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sku TEXT UNIQUE,
    stock INTEGER NOT NULL DEFAULT 0,
    min_stock INTEGER NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    is_labor INTEGER NOT NULL DEFAULT 0,
    cost_price REAL NOT NULL DEFAULT 0,
    repasse_value REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mechanics(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    vehicle_id INTEGER,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Aberta',
    notes TEXT,
    labor REAL NOT NULL DEFAULT 0,
    mechanic_id INTEGER,
    pay_method TEXT,
    pay_status TEXT,
    fin_tx_id INTEGER,
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(vehicle_id) REFERENCES vehicles(id),
    FOREIGN KEY(mechanic_id) REFERENCES mechanics(id)
);
CREATE TABLE IF NOT EXISTS order_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    inventory_id INTEGER,
    description TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    is_labor INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(order_id) REFERENCES orders(id),
    FOREIGN KEY(inventory_id) REFERENCES inventory(id)
);


CREATE TABLE IF NOT EXISTS os_stock_applied(
    os_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    qty REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(os_id, inventory_id),
    FOREIGN KEY(os_id) REFERENCES orders(id),
    FOREIGN KEY(inventory_id) REFERENCES inventory(id)
);
CREATE TABLE IF NOT EXISTS agenda(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    vehicle_id INTEGER,
    mechanic_id INTEGER,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    whatsapp_sent INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(client_id) REFERENCES clients(id),
    FOREIGN KEY(vehicle_id) REFERENCES vehicles(id),
    FOREIGN KEY(mechanic_id) REFERENCES mechanics(id)
);

-- =========================
-- Financeiro (PRO)
-- =========================
CREATE TABLE IF NOT EXISTS fin_payment_methods(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS fin_categories(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'both' -- in/out/both
);

CREATE TABLE IF NOT EXISTS fin_transactions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ttype TEXT NOT NULL,                 -- IN/OUT
    description TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    date TEXT NOT NULL,                  -- YYYY-MM-DD
    due_date TEXT,                       -- YYYY-MM-DD
    status TEXT NOT NULL DEFAULT 'PENDENTE', -- PENDENTE/EFETIVADO/CANCELADO
    payment_method_id INTEGER,
    category_id INTEGER,
    ref_type TEXT,                       -- OS/PURCHASE/ADHOC
    ref_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY(payment_method_id) REFERENCES fin_payment_methods(id),
    FOREIGN KEY(category_id) REFERENCES fin_categories(id)
);

CREATE TABLE IF NOT EXISTS fin_transaction_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id INTEGER NOT NULL,
    flow TEXT NOT NULL DEFAULT 'money',   -- money/stock
    direction TEXT NOT NULL,             -- IN/OUT (para o flow)
    inventory_id INTEGER,
    description TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 1,
    unit_value REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(tx_id) REFERENCES fin_transactions(id),
    FOREIGN KEY(inventory_id) REFERENCES inventory(id)
);

-- =========================
-- Compras de estoque
-- =========================
CREATE TABLE IF NOT EXISTS purchase_orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier TEXT NOT NULL,
    doc_number TEXT,
    date TEXT NOT NULL,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'PENDENTE', -- PENDENTE/EFETIVADO/CANCELADO
    payment_method_id INTEGER,
    notes TEXT,
    total REAL NOT NULL DEFAULT 0,
    fin_tx_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY(payment_method_id) REFERENCES fin_payment_methods(id),
    FOREIGN KEY(fin_tx_id) REFERENCES fin_transactions(id)
);

CREATE TABLE IF NOT EXISTS purchase_items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id INTEGER NOT NULL,
    inventory_id INTEGER NOT NULL,
    qty REAL NOT NULL DEFAULT 1,
    unit_cost REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    FOREIGN KEY(purchase_id) REFERENCES purchase_orders(id),
    FOREIGN KEY(inventory_id) REFERENCES inventory(id)
);
"""

def seed_inventory(db):
    itens = [
        ("Óleo 5W30 Sintético 1L", "OIL-5W30-1L", 20, 5, 49.90),
        ("Filtro de Óleo Universal", "FILT-OLEO-U", 15, 4, 29.90),
        ("Filtro de Ar", "FILT-AR-U", 12, 3, 39.90),
        ("Filtro de Combustível", "FILT-COMB-U", 10, 2, 59.90),
        ("Fluido de Freio DOT4 500ml", "FLU-DOT4", 12, 3, 24.90),
        ("Pastilha de Freio Dianteira (Popular)", "PAST-FREIO-D", 8, 2, 129.90),
        ("Correia Dentada (Popular)", "COR-DENT", 6, 2, 89.90),
        ("Lâmpada H7 55W", "LAMP-H7", 18, 4, 19.90),
        ("Aditivo Radiador 1L", "ADI-RAD-1L", 14, 3, 34.90),
        ("Bateria 60Ah", "BAT-60AH", 5, 2, 499.00)
    ]
    db.executemany("""INSERT INTO inventory(name, sku, stock, min_stock, price) VALUES (?,?,?,?,?)""", itens)

def seed_mechanics(db):
    nomes = ["Carlos", "Pedro", "Mariana", "João"]
    db.executemany("INSERT INTO mechanics(name) VALUES (?)", [(n,) for n in nomes])

def init_db():
    db = get_db()
    db.executescript(SCHEMA_SQL)
    db.commit()

    # garante colunas novas no estoque mesmo em bancos antigos
    cols = [r["name"] for r in db.execute("PRAGMA table_info(inventory)").fetchall()]
    if "is_labor" not in cols:
        db.execute("ALTER TABLE inventory ADD COLUMN is_labor INTEGER NOT NULL DEFAULT 0")
    if "cost_price" not in cols:
        db.execute("ALTER TABLE inventory ADD COLUMN cost_price REAL NOT NULL DEFAULT 0")
    if "repasse_value" not in cols:
        db.execute("ALTER TABLE inventory ADD COLUMN repasse_value REAL NOT NULL DEFAULT 0")

    # garante colunas novas na OS (pagamento/financeiro)
    ocols = [r["name"] for r in db.execute("PRAGMA table_info(orders)").fetchall()]
    if "pay_method" not in ocols:
        db.execute("ALTER TABLE orders ADD COLUMN pay_method TEXT")
    if "pay_status" not in ocols:
        db.execute("ALTER TABLE orders ADD COLUMN pay_status TEXT")
    if "fin_tx_id" not in ocols:
        db.execute("ALTER TABLE orders ADD COLUMN fin_tx_id INTEGER")
    db.commit()

    # garante coluna is_labor em order_items (para serviços na tabela)
    icols = [r["name"] for r in db.execute("PRAGMA table_info(order_items)").fetchall()]
    if "is_labor" not in icols:
        db.execute("ALTER TABLE order_items ADD COLUMN is_labor INTEGER NOT NULL DEFAULT 0")
    db.commit()

    # seeds do financeiro (métodos e categorias)
    try:
        if db.execute("SELECT COUNT(*) c FROM fin_payment_methods").fetchone()["c"] == 0:
            for n in ["Dinheiro", "Pix", "Cartão Débito", "Cartão Crédito", "Boleto", "Transferência"]:
                db.execute("INSERT OR IGNORE INTO fin_payment_methods(name) VALUES (?)", (n,))
        if db.execute("SELECT COUNT(*) c FROM fin_categories").fetchone()["c"] == 0:
            cats = [
                ("Serviços / OS", "in"),
                ("Vendas avulsas", "in"),
                ("Compras de Estoque", "out"),
                ("Despesas Gerais", "out"),
            ]
            for (n,k) in cats:
                db.execute("INSERT OR IGNORE INTO fin_categories(name, kind) VALUES (?,?)", (n,k))
        db.commit()
    except Exception:
        # se for um banco muito antigo e ainda não tiver as tabelas, a própria SCHEMA_SQL já cria.
        pass

    db.commit()

    # cria usuário padrão se não existir
    if db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        db.execute("INSERT INTO users(username, password) VALUES (?, ?)", ("admin", "1234"))
    if db.execute("SELECT COUNT(*) c FROM inventory").fetchone()["c"] == 0:
        seed_inventory(db)
    if db.execute("SELECT COUNT(*) c FROM mechanics").fetchone()["c"] == 0:
        seed_mechanics(db)
    db.commit()



def _csv_response(filename: str, header: list[str], rows: list[tuple]):
    """
    Retorna CSV como download (bom pra salvar/abrir no Excel).
    """
    sio = io.StringIO()
    w = csv.writer(sio, delimiter=";")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    data = sio.getvalue().encode("utf-8-sig")  # BOM pra Excel abrir acentos ok
    return send_file(
        io.BytesIO(data),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )


def fmt_money(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

app.jinja_env.filters["money"] = fmt_money


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            # guarda a página que o usuário tentou acessar
            next_url = request.path
            return redirect(url_for("login", next=next_url))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user or user["password"] != password:
            error = "Usuário ou senha inválidos."
        else:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Login realizado com sucesso!", "ok")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))
    return render_template("login.html", error=error, title="Login")


@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu do sistema.", "ok")
    return redirect(url_for("login"))


@login_required
@login_required
@app.route("/")
def index():
    db = get_db()
    low = db.execute("SELECT * FROM inventory WHERE stock <= min_stock ORDER BY stock ASC").fetchall()
    open_os = db.execute("""
        SELECT o.id, o.created_at, c.name AS client_name, m.name AS mech, o.status
        FROM orders o
        JOIN clients c ON c.id = o.client_id
        LEFT JOIN mechanics m ON m.id = o.mechanic_id
        WHERE o.status IN ('Aberta','Em andamento')
        ORDER BY o.id DESC LIMIT 8
    """).fetchall()
    return render_template("index.html", title=APP_TITLE, low=low, open_os=open_os)

@login_required
@app.route("/clientes", methods=["GET","POST"])
def clientes():
    db = get_db()

    # Cadastro via POST
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        cpf = request.form.get("cpf", "").strip()
        address = request.form.get("address", "").strip()
        if not name:
            flash("Nome é obrigatório.", "error")
        else:
            db.execute(
                "INSERT INTO clients(name, phone, cpf, address) VALUES (?,?,?,?)",
                (name, phone, cpf, address)
            )
            db.commit()
            flash("Cliente cadastrado!", "ok")
        return redirect(url_for("clientes"))

    # Listagem / busca
    q = request.args.get("q", "").strip()
    if q:
        rows = db.execute(
            """
            SELECT * FROM clients
            WHERE name LIKE ? OR phone LIKE ? OR cpf LIKE ?
            ORDER BY name
            """,
            (f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM clients ORDER BY id DESC LIMIT 100"
        ).fetchall()

    # Modo JSON para busca da Nova OS
    if request.args.get("json") == "1":
        data = [
            {
                "id": r["id"],
                "name": r["name"],
                "phone": r["phone"],
                "cpf": r["cpf"],
                "address": r["address"],
            }
            for r in rows
        ]
        from flask import jsonify as _jsonify
        return _jsonify(data)

    # Modo normal (HTML)
    return render_template("clientes.html", rows=rows, q=q, title="Clientes")


@login_required
@app.route("/clientes/<int:cid>", methods=["GET","POST"])
def cliente_edit(cid):
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name","").strip()
        phone = request.form.get("phone","").strip()
        cpf = request.form.get("cpf","").strip()
        address = request.form.get("address","").strip()
        if not name:
            flash("Nome é obrigatório.", "error")
        else:
            db.execute("UPDATE clients SET name=?, phone=?, cpf=?, address=? WHERE id=?",
                       (name, phone, cpf, address, cid))
            db.commit()
            flash("Cliente atualizado!", "ok")
        return redirect(url_for("clientes"))
    c = db.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    if not c:
        flash("Cliente não encontrado.", "error")
        return redirect(url_for("clientes"))
    return render_template("cliente_edit.html", c=c, title="Editar Cliente")


@login_required
@app.route("/veiculos/<int:client_id>", methods=["GET","POST"])
def veiculos(client_id):
    db = get_db()
    if request.method == "POST":
        plate = request.form.get("plate","").strip().upper()
        model = request.form.get("model","").strip()
        year = int(request.form.get("year") or 0)
        db.execute("INSERT INTO vehicles(client_id, plate, model, year) VALUES (?,?,?,?)",
                   (client_id, plate, model, year))
        db.commit()
        flash("Veículo adicionado!", "ok")
        return redirect(url_for("veiculos", client_id=client_id))
    c = db.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    vs = db.execute("SELECT * FROM vehicles WHERE client_id=? ORDER BY id DESC", (client_id,)).fetchall()
    os_rows = db.execute(
        """
        SELECT o.id, o.created_at, o.status, v.plate, v.model,
               m.name AS mech
        FROM orders o
        LEFT JOIN vehicles v ON v.id=o.vehicle_id
        LEFT JOIN mechanics m ON m.id=o.mechanic_id
        WHERE o.client_id = ?
        ORDER BY o.id DESC
        """,
        (client_id,)
    ).fetchall()
    return render_template("veiculos.html", c=c, vs=vs, os_rows=os_rows, title="Veículos")

@login_required
@app.route("/veiculos/<int:client_id>/<int:vehicle_id>/delete", methods=["POST"])
def veiculo_delete(client_id, vehicle_id):
    """Exclui um veículo do cliente.
    As OS permanecem, apenas desvinculadas do veículo.
    """
    db = get_db()
    # remove vínculo do veículo nas OS
    db.execute("UPDATE orders SET vehicle_id = NULL WHERE vehicle_id = ?", (vehicle_id,))
    # remove o veículo do cliente
    db.execute("DELETE FROM vehicles WHERE id = ? AND client_id = ?", (vehicle_id, client_id))
    db.commit()
    flash("Veículo excluído. As OS foram mantidas sem vínculo com o veículo.", "ok")
    return redirect(url_for("veiculos", client_id=client_id))


@login_required
@app.route("/veiculos/<int:client_id>/<int:vehicle_id>/transferir", methods=["POST"])
def veiculo_transferir(client_id, vehicle_id):
    """Transfere um veículo para outro cliente e atualiza as OS desse veículo."""
    db = get_db()
    new_client_id = request.form.get("new_client_id", type=int)
    new_client_query = (request.form.get("new_client_query") or "").strip()

    if not new_client_id:
        if not new_client_query:
            flash("Informe o cliente de destino para transferir o veículo.", "error")
            return redirect(url_for("veiculos", client_id=client_id))
        like = f"%{new_client_query}%"
        row = db.execute(
            "SELECT id FROM clients WHERE name LIKE ? OR phone LIKE ? OR cpf LIKE ? ORDER BY id DESC LIMIT 1",
            (like, like, like),
        ).fetchone()
        if not row:
            flash("Cliente de destino não encontrado.", "error")
            return redirect(url_for("veiculos", client_id=client_id))
        new_client_id = row["id"]

    # garante que o veículo pertence ao cliente atual
    v = db.execute(
        "SELECT * FROM vehicles WHERE id = ? AND client_id = ?",
        (vehicle_id, client_id),
    ).fetchone()
    if not v:
        flash("Veículo não encontrado para este cliente.", "error")
        return redirect(url_for("veiculos", client_id=client_id))

    # transfere veículo
    db.execute(
        "UPDATE vehicles SET client_id = ? WHERE id = ?",
        (new_client_id, vehicle_id),
    )
    # atualiza as OS vinculadas a esse veículo
    db.execute(
        "UPDATE orders SET client_id = ? WHERE vehicle_id = ? AND client_id = ?",
        (new_client_id, vehicle_id, client_id),
    )

    db.commit()
    flash("Veículo transferido para outro cliente.", "ok")
    return redirect(url_for("veiculos", client_id=new_client_id))


@app.route("/api/clients_search")
def api_clients_search():
    """Endpoint de autocomplete de clientes para Nova OS e outras telas."""
    db = get_db()
    q = (request.args.get("q") or "").strip()
    try:
        limit = int(request.args.get("limit") or 20)
    except ValueError:
        limit = 20

    if not q:
        rows = db.execute(
            "SELECT id, name, phone, cpf FROM clients ORDER BY name LIMIT ?",
            (limit,)
        ).fetchall()
    else:
        like = f"%{q}%"
        rows = db.execute(
            """
            SELECT id, name, phone, cpf
            FROM clients
            WHERE name LIKE ? OR phone LIKE ? OR cpf LIKE ?
            ORDER BY name
            LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()

    data = []
    for r in rows:
        parts = [r["name"]]
        if r["phone"]:
            parts.append(r["phone"])
        if r["cpf"]:
            parts.append(r["cpf"])
        label = " - ".join(parts)
        data.append(
            {
                "id": r["id"],
                "name": r["name"],
                "phone": r["phone"],
                "cpf": r["cpf"],
                "label": label,
            }
        )
    return jsonify(data)



@login_required
@app.route("/estoque", methods=["GET","POST"])
def estoque():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name","").strip()
        sku = request.form.get("sku","").strip().upper() or None
        stock = float(request.form.get("stock") or 0)
        min_stock = float(request.form.get("min_stock") or 0)
        price = float(request.form.get("price") or 0)
        cost_price = float(request.form.get("cost_price") or 0)
        repasse_value = float(request.form.get("repasse_value") or 0)
        is_labor = 1 if request.form.get("is_labor") == "1" else 0

        if not name:
            flash("Nome é obrigatório.", "error")
        else:
            db.execute(
                """INSERT INTO inventory(name, sku, stock, min_stock, price, is_labor, cost_price, repasse_value)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (name, sku, stock, min_stock, price, is_labor, cost_price, repasse_value),
            )
            db.commit()
            flash("Item adicionado ao estoque!", "ok")
        return redirect(url_for("estoque"))

    q = request.args.get("q","").strip()
    if q:
        rows = db.execute(
            """
            SELECT * FROM inventory
            WHERE name LIKE ? OR sku LIKE ?
            ORDER BY name
            """,
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM inventory ORDER BY id DESC LIMIT 200").fetchall()

    return render_template("estoque.html", rows=rows, q=q, title="Estoque")


@login_required
@app.route("/estoque/<int:item_id>/editar", methods=["GET","POST"])
def estoque_editar(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM inventory WHERE id = ?", (item_id,)).fetchone()
    if not item:
        flash("Item não encontrado.", "error")
        return redirect(url_for("estoque"))

    if request.method == "POST":
        name = request.form.get("name","").strip()
        sku = request.form.get("sku","").strip().upper() or None
        stock = float(request.form.get("stock") or 0)
        min_stock = float(request.form.get("min_stock") or 0)
        price = float(request.form.get("price") or 0)
        cost_price = float(request.form.get("cost_price") or 0)
        repasse_value = float(request.form.get("repasse_value") or 0)
        is_labor = 1 if request.form.get("is_labor") == "1" else 0

        if not name:
            flash("Nome é obrigatório.", "error")
            return redirect(request.url)

        db.execute(
            """UPDATE inventory
               SET name = ?, sku = ?, stock = ?, min_stock = ?, price = ?, is_labor = ?, cost_price = ?, repasse_value = ?
               WHERE id = ?""",
            (name, sku, stock, min_stock, price, is_labor, cost_price, repasse_value, item_id),
        )
        db.commit()
        flash("Item atualizado!", "ok")
        return redirect(url_for("estoque"))

    return render_template("estoque_editar.html", item=item, title="Editar item de estoque")




@login_required
@app.route("/api/inventory_search")
def inventory_search():
    db = get_db()
    q = request.args.get("q","").strip()
    limit = int(request.args.get("limit") or 20)
    if not q:
        items = db.execute("SELECT id, name, price, stock FROM inventory ORDER BY name LIMIT ?", (limit,)).fetchall()
    else:
        items = db.execute("""
            SELECT id, name, price, stock FROM inventory
            WHERE name LIKE ? OR sku LIKE ?
            ORDER BY name LIMIT ?
        """, (f"%{q}%", f"%{q}%", limit)).fetchall()
    data = [dict(id=i["id"], name=i["name"], price=i["price"], stock=i["stock"]) for i in items]
    return jsonify(data)


@login_required
@app.route("/os")
def os_list():
    db = get_db()
    status = request.args.get("status", "").strip()
    mech_id = request.args.get("mechanic_id", "").strip()
    d_start = request.args.get("start", "").strip()
    d_end = request.args.get("end", "").strip()
    q = request.args.get("q", "").strip()

    where = []
    params = []

    if status:
        where.append("o.status = ?")
        params.append(status)
    if mech_id:
        try:
            mech_int = int(mech_id)
            where.append("o.mechanic_id = ?")
            params.append(mech_int)
        except ValueError:
            mech_id = ""

    if d_start:
        try:
            ds = datetime.datetime.strptime(d_start, "%Y-%m-%d")
            where.append("o.created_at >= ?")
            params.append(ds.strftime("%Y-%m-%d 00:00:00"))
        except ValueError:
            d_start = ""
    if d_end:
        try:
            de = datetime.datetime.strptime(d_end, "%Y-%m-%d")
            where.append("o.created_at <= ?")
            params.append(de.strftime("%Y-%m-%d 23:59:59"))
        except ValueError:
            d_end = ""

    if q:
        where.append("(c.name LIKE ? OR v.plate LIKE ? OR CAST(o.id AS TEXT) LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    sql = """
        SELECT o.id, o.created_at, o.status, o.labor,
               c.name AS client_name, v.plate, m.name AS mech,
               COALESCE(SUM(oi.total),0) AS total_itens,
               COALESCE(SUM(oi.total),0) + COALESCE(o.labor,0) AS total_geral
        FROM orders o
        JOIN clients c ON c.id=o.client_id
        LEFT JOIN vehicles v ON v.id=o.vehicle_id
        LEFT JOIN mechanics m ON m.id=o.mechanic_id
        LEFT JOIN order_items oi ON oi.order_id=o.id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY o.id ORDER BY o.id DESC LIMIT 200"

    rows = db.execute(sql, params).fetchall()
    mechs = db.execute("SELECT id, name FROM mechanics ORDER BY name").fetchall()

    return render_template(
        "os_list.html",
        rows=rows,
        mechs=mechs,
        status=status,
        mech_id=mech_id,
        q=q,
        start=d_start,
        end=d_end,
        title="Ordens de Serviço"
    )
# =========================
# Exportações (backup rápido)
# =========================

@login_required
@app.route("/export/os.csv")
def export_os_csv():
    """
    Exporta lista de OS (com filtros iguais da tela /os) em CSV.
    Ideal para guardar e imprimir depois.
    """
    db = get_db()
    status = request.args.get("status", "").strip()
    mech_id = request.args.get("mechanic_id", "").strip()
    d_start = request.args.get("start", "").strip()
    d_end = request.args.get("end", "").strip()
    q = request.args.get("q", "").strip()

    where = []
    params = []

    if status:
        where.append("o.status = ?")
        params.append(status)
    if mech_id:
        try:
            mech_int = int(mech_id)
            where.append("o.mechanic_id = ?")
            params.append(mech_int)
        except ValueError:
            mech_id = ""

    if d_start:
        try:
            ds = datetime.datetime.strptime(d_start, "%Y-%m-%d")
            where.append("o.created_at >= ?")
            params.append(ds.strftime("%Y-%m-%d 00:00:00"))
        except ValueError:
            d_start = ""
    if d_end:
        try:
            de = datetime.datetime.strptime(d_end, "%Y-%m-%d")
            where.append("o.created_at <= ?")
            params.append(de.strftime("%Y-%m-%d 23:59:59"))
        except ValueError:
            d_end = ""

    if q:
        where.append("(c.name LIKE ? OR v.plate LIKE ? OR CAST(o.id AS TEXT) LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    sql = """
        SELECT o.id, o.created_at, o.status, o.labor, o.pay_method, o.pay_status,
               c.name AS client_name,
               v.plate, v.model,
               m.name AS mech,
               COALESCE(SUM(oi.total),0) AS total_itens,
               COALESCE(SUM(oi.total),0) + COALESCE(o.labor,0) AS total_geral
        FROM orders o
        JOIN clients c ON c.id=o.client_id
        LEFT JOIN vehicles v ON v.id=o.vehicle_id
        LEFT JOIN mechanics m ON m.id=o.mechanic_id
        LEFT JOIN order_items oi ON oi.order_id=o.id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY o.id ORDER BY o.id DESC"

    rows = db.execute(sql, params).fetchall()

    out = []
    for r in rows:
        out.append((
            r["id"],
            (r["created_at"] or "")[:19],
            r["client_name"],
            r["plate"] or "",
            r["model"] or "",
            r["mech"] or "",
            r["status"] or "",
            float(r["labor"] or 0),
            float(r["total_itens"] or 0),
            float(r["total_geral"] or 0),
            r["pay_method"] or "",
            r["pay_status"] or "",
        ))

    return _csv_response(
        "fcar_os.csv",
        ["ID","Data","Cliente","Placa","Modelo","Mecânico","Status","Mão de obra","Total peças","Total OS","Forma pagto","Status pagto"],
        out
    )

@login_required
@app.route("/export/os_itens.csv")
def export_os_itens_csv():
    """
    Exporta itens das OS (uma linha por item).
    Ótimo como "backup detalhado" (peças/serviços).
    """
    db = get_db()

    # usa os mesmos filtros da tela /os
    status = request.args.get("status", "").strip()
    mech_id = request.args.get("mechanic_id", "").strip()
    d_start = request.args.get("start", "").strip()
    d_end = request.args.get("end", "").strip()
    q = request.args.get("q", "").strip()

    where = []
    params = []

    if status:
        where.append("o.status = ?")
        params.append(status)
    if mech_id:
        try:
            mech_int = int(mech_id)
            where.append("o.mechanic_id = ?")
            params.append(mech_int)
        except ValueError:
            mech_id = ""

    if d_start:
        try:
            ds = datetime.datetime.strptime(d_start, "%Y-%m-%d")
            where.append("o.created_at >= ?")
            params.append(ds.strftime("%Y-%m-%d 00:00:00"))
        except ValueError:
            d_start = ""
    if d_end:
        try:
            de = datetime.datetime.strptime(d_end, "%Y-%m-%d")
            where.append("o.created_at <= ?")
            params.append(de.strftime("%Y-%m-%d 23:59:59"))
        except ValueError:
            d_end = ""

    if q:
        where.append("(c.name LIKE ? OR v.plate LIKE ? OR CAST(o.id AS TEXT) LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    sql = """
        SELECT o.id AS os_id, o.created_at, o.status,
               c.name AS client_name,
               v.plate, v.model,
               m.name AS mech,
               oi.description, oi.qty, oi.unit_price, oi.total, oi.is_labor
        FROM orders o
        JOIN clients c ON c.id=o.client_id
        LEFT JOIN vehicles v ON v.id=o.vehicle_id
        LEFT JOIN mechanics m ON m.id=o.mechanic_id
        LEFT JOIN order_items oi ON oi.order_id=o.id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY o.id DESC, oi.id ASC"

    rows = db.execute(sql, params).fetchall()

    out = []
    for r in rows:
        out.append((
            r["os_id"],
            (r["created_at"] or "")[:19],
            r["client_name"],
            r["plate"] or "",
            r["model"] or "",
            r["mech"] or "",
            r["status"] or "",
            r["description"] or "",
            float(r["qty"] or 0),
            float(r["unit_price"] or 0),
            float(r["total"] or 0),
            int(r["is_labor"] or 0),
        ))

    return _csv_response(
        "fcar_os_itens.csv",
        ["OS_ID","Data","Cliente","Placa","Modelo","Mecânico","Status","Item/Serviço","Qtd","Unitário","Total","is_labor"],
        out
    )




@login_required
@app.route("/print/os")
def print_os():
    """
    Página enxuta para imprimir/salvar PDF com Ctrl+P.
    Usa os mesmos filtros da tela /os.
    """
    db = get_db()
    status = request.args.get("status", "").strip()
    mech_id = request.args.get("mechanic_id", "").strip()
    d_start = request.args.get("start", "").strip()
    d_end = request.args.get("end", "").strip()
    q = request.args.get("q", "").strip()

    where = []
    params = []

    if status:
        where.append("o.status = ?")
        params.append(status)
    if mech_id:
        try:
            mech_int = int(mech_id)
            where.append("o.mechanic_id = ?")
            params.append(mech_int)
        except ValueError:
            mech_id = ""

    if d_start:
        try:
            ds = datetime.datetime.strptime(d_start, "%Y-%m-%d")
            where.append("o.created_at >= ?")
            params.append(ds.strftime("%Y-%m-%d 00:00:00"))
        except ValueError:
            d_start = ""
    if d_end:
        try:
            de = datetime.datetime.strptime(d_end, "%Y-%m-%d")
            where.append("o.created_at <= ?")
            params.append(de.strftime("%Y-%m-%d 23:59:59"))
        except ValueError:
            d_end = ""

    if q:
        where.append("(c.name LIKE ? OR v.plate LIKE ? OR CAST(o.id AS TEXT) LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    sql = """
        SELECT o.id, o.created_at, o.status, o.labor, o.pay_method, o.pay_status,
               c.name AS client_name,
               v.plate, v.model,
               m.name AS mech,
               COALESCE(SUM(oi.total),0) AS total_itens,
               COALESCE(SUM(oi.total),0) + COALESCE(o.labor,0) AS total_geral
        FROM orders o
        JOIN clients c ON c.id=o.client_id
        LEFT JOIN vehicles v ON v.id=o.vehicle_id
        LEFT JOIN mechanics m ON m.id=o.mechanic_id
        LEFT JOIN order_items oi ON oi.order_id=o.id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY o.id ORDER BY o.id DESC"

    rows = db.execute(sql, params).fetchall()
    return render_template("print_os.html", rows=rows, title="Impressão de OS")


@login_required
@app.route("/export/clientes.csv")
def export_clientes_csv():
    """
    Exporta lista de clientes em CSV.
    """
    db = get_db()
    q = request.args.get("q", "").strip()
    if q:
        rows = db.execute(
            """
            SELECT id, name, phone, cpf, address
            FROM clients
            WHERE name LIKE ? OR phone LIKE ? OR cpf LIKE ?
            ORDER BY name
            """,
            (f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        rows = db.execute("SELECT id, name, phone, cpf, address FROM clients ORDER BY name").fetchall()

    out = []
    for r in rows:
        out.append((r["id"], r["name"], r["phone"] or "", r["cpf"] or "", r["address"] or ""))

    return _csv_response(
        "fcar_clientes.csv",
        ["ID","Nome","Telefone","CPF","Endereço"],
        out
    )


@login_required
@app.route("/print/clientes")
def print_clientes():
    """
    Página enxuta para imprimir/salvar PDF com Ctrl+P (clientes).
    """
    db = get_db()
    q = request.args.get("q", "").strip()
    if q:
        rows = db.execute(
            """
            SELECT id, name, phone, cpf, address
            FROM clients
            WHERE name LIKE ? OR phone LIKE ? OR cpf LIKE ?
            ORDER BY name
            """,
            (f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        rows = db.execute("SELECT id, name, phone, cpf, address FROM clients ORDER BY name").fetchall()

    return render_template("print_clientes.html", rows=rows, q=q, title="Impressão de Clientes")





@login_required
@app.route("/export/backup.sql")
def export_backup_sql():
    """
    Dump completo do banco SQLite em SQL (backup real).
    Atenção: contém dados sensíveis. Guarde bem.
    """
    # abre uma conexão separada pra usar iterdump com segurança
    conn = sqlite3.connect(DB_PATH)
    try:
        sio = io.StringIO()
        for line in conn.iterdump():
            sio.write(line + "\n")
        data = sio.getvalue().encode("utf-8")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return send_file(
        io.BytesIO(data),
        mimetype="application/sql",
        as_attachment=True,
        download_name="fcar_backup.sql"
    )




@login_required
@app.route("/os/nova", methods=["GET","POST"])
def os_new():
    db = get_db()
    if request.method == "POST":
        client_id = int(request.form.get("client_id") or 0)

        # Veículo pode ser um existente (vehicle_id) ou um novo digitado no formulário
        vehicle_id_raw = request.form.get("vehicle_id")
        vehicle_id = int(vehicle_id_raw) if vehicle_id_raw else None

        vehicle_plate = (request.form.get("vehicle_plate") or "").strip().upper()
        vehicle_text = (request.form.get("vehicle_text") or "").strip()

        notes = request.form.get("notes", "").strip()
        base_labor = float(request.form.get("labor") or 0)
        mechanic_id = int(request.form.get("mechanic_id") or 0) or None
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not client_id:
            flash("Selecione um cliente.", "error")
            return redirect(url_for("os_new"))

        # Se não veio vehicle_id mas temos dados digitados, cria ou reaproveita veículo
        if client_id and not vehicle_id and (vehicle_plate or vehicle_text):
            existing = None
            if vehicle_plate:
                existing = db.execute(
                    "SELECT id FROM vehicles WHERE client_id=? AND plate=?",
                    (client_id, vehicle_plate),
                ).fetchone()
            if existing:
                vehicle_id = existing["id"]
            else:
                model_text = vehicle_text or None
                cur_v = db.execute(
                    "INSERT INTO vehicles(client_id, plate, model, year) VALUES (?,?,?,?)",
                    (client_id, vehicle_plate or None, model_text, None),
                )
                vehicle_id = cur_v.lastrowid

        labor = base_labor
        items = []        # peças e serviços (itens da OS)
        labor_descs = []  # textos de serviços (pra observação)

        for i in range(1, 51):
            desc = request.form.get(f"item_desc_{i}")
            if not desc:
                continue

            qty = float(request.form.get(f"item_qty_{i}") or 1)
            price = float(request.form.get(f"item_price_{i}") or 0)
            inv_id = request.form.get(f"item_inv_{i}")
            inv_id = int(inv_id) if inv_id else None
            is_labor = request.form.get(f"item_is_labor_{i}") == "1"
            total = qty * price

            if is_labor:
                labor_descs.append(f"{desc.strip()} (R$ {total:.2f})")
                items.append({"inventory_id": None, "description": desc.strip(), "qty": qty, "unit_price": price, "total": total, "is_labor": 1})
            else:
                items.append({"inventory_id": inv_id, "description": desc.strip(), "qty": qty, "unit_price": price, "total": total, "is_labor": 0})

        if labor_descs:
            extra = "Serviços:\n- " + "\n- ".join(labor_descs)
            notes = f"{notes}\n\n{extra}" if notes else extra

        cur = db.execute(
            """INSERT INTO orders(client_id, vehicle_id, created_at, status, notes, labor, mechanic_id, pay_method, pay_status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (client_id, vehicle_id, created_at, "Aberta", notes, base_labor, mechanic_id, "Dinheiro", "Pendente")
        )
        os_id = cur.lastrowid

        if items:
            db.executemany(
                """INSERT INTO order_items(order_id, inventory_id, description, qty, unit_price, total, is_labor)
                    VALUES (?,?,?,?,?,?,?)""",
                [
                    (os_id, it["inventory_id"], it["description"], it["qty"], it["unit_price"], it["total"], it["is_labor"])
                    for it in items
                ]
            )

        # --- sync financeiro (OS -> lançamento PENDENTE/EFETIVADO/CANCELADO)
        try:
            rcn = db.execute("SELECT name FROM clients WHERE id=?", (client_id,)).fetchone()
            client_name = rcn["name"] if rcn else None
            sync_os_to_finance(db, os_id, client_name, "Aberta", "Dinheiro", "Pendente", base_labor, items)
        except Exception as e:
            print("ERRO sync_os_to_finance (os_new):", e)

        db.commit()
        flash(f"OS #{os_id} criada!", "ok")
        return redirect(url_for("os_view", os_id=os_id))

    clients = db.execute("SELECT id, name FROM clients ORDER BY name").fetchall()
    vehicles = db.execute(
        """SELECT v.id, v.plate, v.model, c.name AS client_name
           FROM vehicles v JOIN clients c ON c.id=v.client_id
           ORDER BY v.id DESC"""
    ).fetchall()
    mechs = db.execute("SELECT id, name FROM mechanics ORDER BY name").fetchall()
    return render_template("os_new.html", clients=clients, vehicles=vehicles, mechs=mechs, title="Nova OS")

@app.route("/os/<int:os_id>")
def os_view(os_id):
    db = get_db()
    o = db.execute("""
        SELECT o.*, c.name AS client_name, v.plate, v.model, m.name AS mech
        FROM orders o
        JOIN clients c ON c.id=o.client_id
        LEFT JOIN vehicles v ON v.id=o.vehicle_id
        LEFT JOIN mechanics m ON m.id=o.mechanic_id
        WHERE o.id=?
    """, (os_id,)).fetchone()
    if not o:
        flash("OS não encontrada.", "error")
        return redirect(url_for("os_list"))

    its = db.execute("""
        SELECT i.*, inv.name AS inv_name
        FROM order_items i
        LEFT JOIN inventory inv ON inv.id=i.inventory_id
        WHERE i.order_id=?
        ORDER BY i.id
    """, (os_id,)).fetchall()
    its = [dict(r) for r in its]  # garante .get() nos itens (sqlite3.Row -> dict)

    pecas = [r for r in its if int(r.get("is_labor") or 0) == 0]
    servicos_itens = [r for r in its if int(r.get("is_labor") or 0) == 1]

    pecas_total = sum(float(r["total"] or 0) for r in pecas) if pecas else 0.0
    servicos_itens_total = sum(float(r["total"] or 0) for r in servicos_itens) if servicos_itens else 0.0
    mao_obra = float(o["labor"] or 0)
    servicos_total = mao_obra + servicos_itens_total
    total = pecas_total + servicos_total

    return render_template(
        "os_view.html",
        o=o,
        its=its,
        pecas=pecas,
        servicos_itens=servicos_itens,
        pecas_total=pecas_total,
        servicos_itens_total=servicos_itens_total,
        mao_obra=mao_obra,
        servicos_total=servicos_total,
        total=total,
        title=f"OS #{os_id}",
        auto_print=('print' in request.args),
    )

@app.route("/os/<int:os_id>/qr")

def qr_os(os_id):
    """Gera QR Code da OS."""
    url = url_for("os_view", os_id=os_id, _external=True)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@login_required
@app.route("/mecanicos", methods=["GET","POST"])
def mecanicos():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name","").strip()
        if not name:
            flash("Nome do mecânico é obrigatório.", "error")
        else:
            existing = db.execute("SELECT id FROM mechanics WHERE UPPER(name)=UPPER(?)", (name,)).fetchone()
            if existing:
                flash("Já existe um mecânico com esse nome.", "error")
            else:
                db.execute("INSERT INTO mechanics(name) VALUES (?)", (name,))
                db.commit()
                flash("Mecânico cadastrado!", "ok")
        return redirect(url_for("mecanicos"))
    rows = db.execute("SELECT * FROM mechanics ORDER BY name").fetchall()
    return render_template("mecanicos.html", rows=rows, title="Mecânicos")


@login_required
@app.route("/mecanicos/<int:mech_id>/excluir", methods=["POST"])
def mecanico_excluir(mech_id):
    db = get_db()
    used = db.execute("SELECT COUNT(*) c FROM orders WHERE mechanic_id=?", (mech_id,)).fetchone()["c"]
    if used:
        flash("Não é possível excluir: existem OS vinculadas a este mecânico.", "error")
    else:
        db.execute("DELETE FROM mechanics WHERE id=?", (mech_id,))
        db.commit()
        flash("Mecânico removido.", "ok")
    return redirect(url_for("mecanicos"))


@login_required
@app.route("/relatorio/mecanicos")
def relatorio_mecanicos():
    db = get_db()

    # Período (padrão: últimos 7 dias)
    today = datetime.date.today()
    d_end = request.args.get("end") or ""
    d_start = request.args.get("start") or ""

    try:
        end = datetime.datetime.strptime(d_end, "%Y-%m-%d").date() if d_end else today
    except ValueError:
        end = today

    try:
        start = datetime.datetime.strptime(d_start, "%Y-%m-%d").date() if d_start else (end - datetime.timedelta(days=6))
    except ValueError:
        start = end - datetime.timedelta(days=6)

    start_ts = datetime.datetime.combine(start, datetime.time.min).strftime("%Y-%m-%d %H:%M:%S")
    end_ts = datetime.datetime.combine(end, datetime.time.max).strftime("%Y-%m-%d %H:%M:%S")

    # Percentual de repasse vindo da tela (?repasse=50, por exemplo)
    repasse_str = request.args.get("repasse") or "50"
    try:
        repasse_percent = float(repasse_str)
    except ValueError:
        repasse_percent = 50.0
    if repasse_percent < 0:
        repasse_percent = 0.0
    if repasse_percent > 100:
        repasse_percent = 100.0
    REPASSE_PERCENT = repasse_percent / 100.0

    # Agregado por mecânico
    raw_rows = db.execute(
        """
        WITH os AS (
            SELECT id, mechanic_id, labor, created_at
            FROM orders
            WHERE created_at BETWEEN ? AND ?
        ),
        agg AS (
            SELECT mechanic_id,
                   COUNT(DISTINCT id) AS qtd_os,
                   COALESCE(SUM(labor), 0) AS base_labor
            FROM os
            GROUP BY mechanic_id
        ),
        itens AS (
            SELECT o.mechanic_id AS mechanic_id,
                   COALESCE(SUM(CASE WHEN oi.is_labor = 1 THEN oi.total ELSE 0 END), 0) AS itens_mao_obra,
                   COALESCE(SUM(CASE WHEN oi.is_labor = 0 THEN oi.total ELSE 0 END), 0) AS itens_pecas
            FROM os o
            LEFT JOIN order_items oi ON oi.order_id = o.id
            GROUP BY o.mechanic_id
        )
        SELECT m.id AS mech_id,
               m.name AS mechanic,
               COALESCE(a.qtd_os, 0) AS qtd_os,
               (COALESCE(a.base_labor, 0) + COALESCE(i.itens_mao_obra, 0)) AS soma_mao_obra,
               COALESCE(i.itens_pecas, 0) AS soma_pecas,
               (COALESCE(a.base_labor, 0) + COALESCE(i.itens_mao_obra, 0) + COALESCE(i.itens_pecas, 0)) AS total
        FROM mechanics m
        LEFT JOIN agg a ON a.mechanic_id = m.id
        LEFT JOIN itens i ON i.mechanic_id = m.id
        ORDER BY total DESC
        """,
        (start_ts, end_ts),
    ).fetchall()

    rows = []
    total_os = 0
    total_labor = 0.0
    total_parts = 0.0
    total_geral = 0.0
    top_faturamento = None
    top_os = None

    for r in raw_rows:
        qtd = r["qtd_os"] or 0
        mao = float(r["soma_mao_obra"] or 0)
        pec = float(r["soma_pecas"] or 0)
        tot = float(r["total"] or 0)

        ticket = tot / qtd if qtd else 0
        perc_mao = (mao / tot * 100) if tot > 0 else 0
        repasse_valor = tot * REPASSE_PERCENT

        total_os += qtd
        total_labor += mao
        total_parts += pec
        total_geral += tot

        rows.append(
            {
                "mech_id": r["mech_id"],
                "mechanic": r["mechanic"],
                "qtd_os": qtd,
                "soma_mao_obra": mao,
                "soma_pecas": pec,
                "total": tot,
                "ticket_medio": ticket,
                "perc_mao_obra": perc_mao,
                "repasse_valor": repasse_valor,
            }
        )

        if tot > 0:
            if not top_faturamento or tot > top_faturamento["total"]:
                top_faturamento = {"mechanic": r["mechanic"], "total": tot}
            if qtd > 0 and (not top_os or qtd > top_os["qtd_os"]):
                top_os = {"mechanic": r["mechanic"], "qtd_os": qtd}

    summary = {
        "total_os": total_os,
        "total_labor": total_labor,
        "total_parts": total_parts,
        "total_geral": total_geral,
        "repasse_percent": repasse_percent,
        "top_faturamento": top_faturamento,
        "top_os": top_os,
    }

    # Detalhamento por OS no período (para tabela analítica)
    os_rows = db.execute(
        """
        SELECT
            o.id,
            o.mechanic_id,
            m.name AS mechanic,
            o.created_at,
            c.name AS client_name,
            v.plate,
            COALESCE(o.labor, 0) AS labor,
            COALESCE(SUM(oi.total), 0) AS soma_pecas,
            COALESCE(SUM(oi.total), 0) + COALESCE(o.labor, 0) AS total_os
        FROM orders o
        JOIN mechanics m ON m.id = o.mechanic_id
        JOIN clients c ON c.id = o.client_id
        LEFT JOIN vehicles v ON v.id = o.vehicle_id
        LEFT JOIN order_items oi ON oi.order_id = o.id
        WHERE o.created_at BETWEEN ? AND ?
        GROUP BY o.id
        ORDER BY m.name, o.id DESC
        """,
        (start_ts, end_ts),
    ).fetchall()

    return render_template(
        "relatorio_mecanicos.html",
        rows=rows,
        os_rows=os_rows,
        summary=summary,
        start=start,
        end=end,
        title="Relatório por Mecânico",
    )


@login_required
@app.route("/agenda", methods=["GET", "POST"])
def agenda():
    db = get_db()
    # --- CADASTRAR NOVO AGENDAMENTO ---
    if request.method == "POST":
        client_id = int(request.form.get("client_id") or 0)
        vehicle_id = request.form.get("vehicle_id")
        vehicle_id = int(vehicle_id) if vehicle_id else None
        mechanic_id = request.form.get("mechanic_id")
        mechanic_id = int(mechanic_id) if mechanic_id else None
        date = request.form.get("date")
        time_h = request.form.get("time")
        notes = request.form.get("notes", "").strip()

        if not client_id or not date or not time_h:
            flash("Selecione o cliente, data e horário!", "error")
            return redirect(url_for("agenda"))

        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        db.execute(
            """INSERT INTO agenda(client_id, vehicle_id, mechanic_id, date, time, notes, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (client_id, vehicle_id, mechanic_id, date, time_h, notes, created_at)
        )
        db.commit()
        flash("Agendamento criado!", "ok")
        # volta para a agenda no dia do agendamento
        return redirect(url_for("agenda", view="dia", date=date))

    # --- VISUAL DIA / SEMANA ---
    view = request.args.get("view") or "dia"
    if view not in ("dia", "semana"):
        view = "dia"

    today = datetime.date.today()
    date_str = request.args.get("date")
    if date_str:
        try:
            ref_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            ref_date = today
    else:
        ref_date = today

    if view == "semana":
        # segunda a domingo da semana da data de referência
        start = ref_date - datetime.timedelta(days=ref_date.weekday())
        end = start + datetime.timedelta(days=6)
    else:
        start = ref_date
        end = ref_date

    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    rows = db.execute(
        """SELECT a.*, c.name AS client_name, v.plate, v.model, m.name AS mech
           FROM agenda a
           JOIN clients c ON c.id = a.client_id
           LEFT JOIN vehicles v ON v.id = a.vehicle_id
           LEFT JOIN mechanics m ON m.id = a.mechanic_id
           WHERE a.date BETWEEN ? AND ?
           ORDER BY a.date, a.time""",
        (start_s, end_s)
    ).fetchall()

    clients = db.execute("SELECT id, name FROM clients ORDER BY name").fetchall()
    vehicles = db.execute(
        """SELECT v.id, v.plate, v.model, c.name AS client_name
           FROM vehicles v
           JOIN clients c ON c.id = v.client_id
           ORDER BY v.id DESC"""
    ).fetchall()
    mechs = db.execute("SELECT id, name FROM mechanics ORDER BY name").fetchall()

    # montar lista de dias (para o modo semana)
    days = []
    d = start
    while d <= end:
        days.append({
            "date": d,
            "iso": d.strftime("%Y-%m-%d"),
            "label": d.strftime("%d/%m")
        })
        d += datetime.timedelta(days=1)

    return render_template(
        "agenda.html",
        rows=rows,
        clients=clients,
        vehicles=vehicles,
        mechs=mechs,
        view=view,
        ref_date=ref_date,
        start=start,
        end=end,
        days=days,
        title="Agenda"
    )


@login_required
@app.route("/agenda/<int:aid>/whatsapp")
def enviar_whatsapp_agenda(aid):
    db = get_db()
    ag = db.execute(
        """SELECT a.*, c.phone, c.name AS client_name, v.plate
           FROM agenda a
           JOIN clients c ON c.id = a.client_id
           LEFT JOIN vehicles v ON v.id = a.vehicle_id
           WHERE a.id = ?""",
        (aid,)
    ).fetchone()

    if not ag:
        flash("Agendamento não encontrado.", "error")
        return redirect(url_for("agenda"))

    phone = (ag["phone"] or "").strip()
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        flash("Cliente sem telefone cadastrado para WhatsApp.", "error")
        return redirect(url_for("agenda"))

    if digits.startswith("55"):
        full_phone = digits
    else:
        full_phone = "55" + digits

    msg = (
        "Olá {nome}, seu agendamento está marcado para {data} às {hora}"
        " para o veículo {carro}. Por favor, não se atrase! *FCAR Reparação Automotiva*"
    )
    msg = msg.format(
        nome=ag["client_name"],
        data=ag["date"],
        hora=ag["time"],
        carro=ag["plate"] or "seu veículo"
    )

    from urllib.parse import quote_plus
    wa_url = f"https://wa.me/{full_phone}?text=" + quote_plus(msg)

    db.execute("UPDATE agenda SET whatsapp_sent = 1 WHERE id = ?", (aid,))
    db.commit()

    return redirect(wa_url)



@login_required
@app.route("/os/<int:os_id>/editar", methods=["GET","POST"])
def os_edit(os_id):
    db = get_db()
    # Carrega OS com dados do cliente e veículo
    o = db.execute("""
        SELECT o.*, c.name AS client_name, v.plate, v.model
        FROM orders o
        JOIN clients c ON c.id = o.client_id
        LEFT JOIN vehicles v ON v.id = o.vehicle_id
        WHERE o.id = ?
    """, (os_id,)).fetchone()

    if not o:
        flash("OS não encontrada.", "error")
        return redirect(url_for("os_list"))

    if request.method == "POST":
        # Cliente da OS não muda aqui
        client_id = o["client_id"]
        vehicle_id = o["vehicle_id"]

        status = request.form.get("status") or (o["status"] or "Aberta")
        pay_method = (request.form.get("pay_method") or (o["pay_method"] or "Dinheiro")).strip()
        pay_status = (request.form.get("pay_status") or (o["pay_status"] or "Pendente")).strip()

        notes = (request.form.get("notes") or "").strip()
        base_labor = float(request.form.get("labor") or 0)

        mechanic_raw = request.form.get("mechanic_id")
        mechanic_id = int(mechanic_raw) if mechanic_raw else None

        vehicle_plate = (request.form.get("vehicle_plate") or "").strip().upper()
        vehicle_text = (request.form.get("vehicle_text") or "").strip()

        # Atualiza ou cria veículo se veio informação
        if client_id and (vehicle_plate or vehicle_text):
            if vehicle_id:
                # Atualiza o veículo já vinculado
                db.execute(
                    "UPDATE vehicles SET plate = ?, model = ? WHERE id = ?",
                    (vehicle_plate or None, vehicle_text or None, vehicle_id),
                )
            else:
                # Não havia veículo vinculado, tenta reaproveitar ou cria um novo
                existing = None
                if vehicle_plate:
                    existing = db.execute(
                        "SELECT id FROM vehicles WHERE client_id = ? AND plate = ?",
                        (client_id, vehicle_plate),
                    ).fetchone()
                if existing:
                    vehicle_id = existing["id"]
                else:
                    cur_v = db.execute(
                        "INSERT INTO vehicles(client_id, plate, model, year) VALUES (?,?,?,?)",
                        (client_id, vehicle_plate or None, vehicle_text or None, None),
                    )
                    vehicle_id = cur_v.lastrowid

        # 1) Remove itens antigos
        db.execute("DELETE FROM order_items WHERE order_id = ?", (os_id,))

        # 3) Lê itens do formulário e recalcula
        items = []  # lista de dicts com is_labor=0/1
        labor_descs = []

        for i in range(1, 51):
            desc = request.form.get(f"item_desc_{i}")
            if not desc:
                continue

            qty = float(request.form.get(f"item_qty_{i}") or 1)
            price = float(request.form.get(f"item_price_{i}") or 0)
            inv_id_raw = request.form.get(f"item_inv_{i}")
            inv_id = int(inv_id_raw) if inv_id_raw else None
            is_labor = request.form.get(f"item_is_labor_{i}") == "1"
            total = qty * price

            if is_labor:
                # serviços extras ficam guardados como item (sem mexer em estoque)
                labor_descs.append(f"{desc.strip()} (R$ {total:.2f})")
                items.append({
                    "inventory_id": None,
                    "description": desc.strip(),
                    "qty": qty,
                    "unit_price": price,
                    "total": total,
                    "is_labor": 1,
                })
            else:
                items.append({
                    "inventory_id": inv_id,
                    "description": desc.strip(),
                    "qty": qty,
                    "unit_price": price,
                    "total": total,
                    "is_labor": 0,
                })

        # Opcional: anexa descrição dos serviços nas observações (pra ficar legível)
        if labor_descs:
            extra = "Serviços:\n- " + "\n- ".join(labor_descs)
            notes = f"{notes}\n\n{extra}" if notes else extra

        
        # --- estoque automático: baixa apenas quando a OS estiver FECHADA ---
        # Se faltar peça para a diferença (delta), não deixa fechar para não estourar o estoque
        if _is_os_closed(status):
            applied_map = _get_os_applied_parts(db, os_id)
            desired_map = _desired_parts_from_items(items)
            delta_plus = {}
            for inv_id in set(desired_map) | set(applied_map):
                dlt = float(desired_map.get(inv_id, 0.0) - applied_map.get(inv_id, 0.0))
                if dlt > 0:
                    delta_plus[int(inv_id)] = dlt
            faltas = _check_stock_for_delta(db, delta_plus)
            if faltas:
                msg = "Estoque insuficiente para fechar a OS. Ajuste as quantidades: " + "; ".join(
                    [f"{f['name']} (tem {int(f['have'])}, precisa +{f['need']:.2f})" for f in faltas]
                )
                flash(msg, "error")
                mechs = db.execute("SELECT id, name FROM mechanics ORDER BY name").fetchall()
                o2 = dict(o)
                o2.update({
                    "status": status,
                    "pay_method": pay_method,
                    "pay_status": pay_status,
                    "notes": notes,
                    "labor": base_labor,
                    "mechanic_id": mechanic_id,
                    "vehicle_id": vehicle_id,
                })
                return render_template(
                    "os_edit.html",
                    o=o2,
                    its=items,
                    mechs=mechs,
                    title=f"Editar OS #{os_id}",
                )

# 4) Atualiza a OS (mantém created_at)
        db.execute(
            """
            UPDATE orders
               SET vehicle_id = ?,
                   status = ?,
                   notes = ?,
                   labor = ?,
                   mechanic_id = ?,
                   pay_method = ?,
                   pay_status = ?
             WHERE id = ?
            """,
            (vehicle_id, status, notes, base_labor, mechanic_id, pay_method, pay_status, os_id),
        )

        # 5) Reinsere itens (peças e serviços extras)
        if items:
            db.executemany(
                """
                INSERT INTO order_items(order_id, inventory_id, description, qty, unit_price, total, is_labor)
                VALUES (?,?,?,?,?,?,?)
                """,
                [
                    (os_id, it["inventory_id"], it["description"], it["qty"], it["unit_price"], it["total"], it["is_labor"])
                    for it in items
                ],
            )

        # --- sync financeiro (OS -> lançamento + detalhamento)
        try:
            sync_os_to_finance(db, os_id, o.get("client_name"), status, pay_method, pay_status, base_labor, items)
        except Exception:
            pass

        
        # aplica (ou desfaz) estoque conforme status (FECHADA baixa; caso contrário devolve)
        try:
            reconcile_os_stock(db, os_id, status, items)
        except Exception:
            pass
        db.commit()
        flash("OS atualizada com sucesso!", "ok")
        return redirect(url_for("os_view", os_id=os_id))

    # GET: carrega itens e mecânicos para montar o formulário completo
    mechs = db.execute("SELECT id, name FROM mechanics ORDER BY name").fetchall()
    its = db.execute(
        """
        SELECT i.*, inv.name AS inv_name
        FROM order_items i
        LEFT JOIN inventory inv ON inv.id = i.inventory_id
        WHERE i.order_id = ?
        ORDER BY i.id
        """,
        (os_id,),
    ).fetchall()

    return render_template(
        "os_edit.html",
        o=o,
        its=its,
        mechs=mechs,
        title=f"Editar OS #{os_id}",
    )


@login_required
@app.route("/os/<int:os_id>/excluir", methods=["POST"])
def os_delete(os_id):
    db = get_db()
    # devolver estoque se essa OS já teve baixa aplicada
    applied = db.execute(
        "SELECT inventory_id, qty FROM os_stock_applied WHERE os_id=?",
        (os_id,),
    ).fetchall()
    for it in applied:
        db.execute("UPDATE inventory SET stock = stock + ? WHERE id=?", (it["qty"], it["inventory_id"]))
    db.execute("DELETE FROM os_stock_applied WHERE os_id=?", (os_id,))

    db.execute("DELETE FROM order_items WHERE order_id=?", (os_id,))
    db.execute("DELETE FROM orders WHERE id=?", (os_id,))
    db.commit()
    flash(f"OS #{os_id} excluída.", "ok")
    next_url = request.form.get("next") or url_for("os_list")
    return redirect(next_url)



@app.cli.command("init")
def _cli_init():
    init_db()
    print("Banco inicializado.")


# --- Context processor: flags for templates ---
@app.context_processor
def inject_flags():
    try:
        from flask import current_app
        has_acesso = ("acesso" in current_app.view_functions)
    except Exception:
        has_acesso = False
    username = session.get("username")
    return dict(has_acesso=has_acesso, username=username)
# --- end context processor ---



# ==========================================================
# Financeiro PRO + Compras de Estoque (Parte 1/2/3)
# ==========================================================

def _today_iso():
    return datetime.date.today().isoformat()

def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")

def _parse_date(s: str|None, default: str) -> str:
    if not s:
        return default
    s = s.strip()
    # aceita dd/mm/aaaa ou aaaa-mm-dd
    if "/" in s:
        try:
            d, m, y = s.split("/")
            return datetime.date(int(y), int(m), int(d)).isoformat()
        except Exception:
            return default
    return s

def _get_method_id(db, name: str) -> int|None:
    if not name:
        return None
    row = db.execute("SELECT id FROM fin_payment_methods WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    db.execute("INSERT OR IGNORE INTO fin_payment_methods(name) VALUES (?)", (name,))
    db.commit()
    row = db.execute("SELECT id FROM fin_payment_methods WHERE name = ?", (name,)).fetchone()
    return int(row["id"]) if row else None

def _get_category_id(db, name: str) -> int|None:
    if not name:
        return None
    row = db.execute("SELECT id FROM fin_categories WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    db.execute("INSERT OR IGNORE INTO fin_categories(name, kind) VALUES (?, 'both')", (name,))
    db.commit()
    row = db.execute("SELECT id FROM fin_categories WHERE name = ?", (name,)).fetchone()
    return int(row["id"]) if row else None

def _tx_status_from_pay(pay_status: str, os_status: str|None=None) -> str:
    s = (pay_status or "").strip().lower()
    if os_status and os_status.strip().lower() == "cancelada":
        return "CANCELADO"
    if s in ["efetivado", "pago", "paga", "feito", "recebido", "recebida"]:
        return "EFETIVADO"
    if s in ["cancelado", "cancelada"]:
        return "CANCELADO"
    return "PENDENTE"

def _rebuild_fin_tx_items(db, tx_id: int, rows: list[tuple]):
    """
    Recria os itens detalhados do lançamento.
    rows: lista de tuplas no formato:
      (flow, direction, inventory_id, description, qty, unit_value, total)
    """
    db.execute("DELETE FROM fin_transaction_items WHERE tx_id=?", (tx_id,))
    if not rows:
        return
    now = _now_iso()
    db.executemany(
        """
        INSERT INTO fin_transaction_items(tx_id, flow, direction, inventory_id, description, qty, unit_value, total, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        [(tx_id, flow, direction, inv_id, desc, qty, unit_v, total, now) for (flow, direction, inv_id, desc, qty, unit_v, total) in rows],
    )




def _is_os_closed(status: str | None) -> bool:
    s = (status or "").strip().lower()
    return s in ("fechada", "fechado", "finalizada", "finalizado", "concluida", "concluída", "concluido", "concluído")

def _get_os_applied_parts(db, os_id: int) -> dict[int, float]:
    rows = db.execute(
        "SELECT inventory_id, qty FROM os_stock_applied WHERE os_id = ?",
        (os_id,),
    ).fetchall()
    out: dict[int, float] = {}
    for r in rows:
        out[int(r["inventory_id"])] = float(r["qty"] or 0)
    return out

def _set_os_applied_parts(db, os_id: int, desired: dict[int, float]) -> None:
    db.execute("DELETE FROM os_stock_applied WHERE os_id = ?", (os_id,))
    now = _now_iso()
    for inv_id, qty in desired.items():
        if qty and qty > 0:
            db.execute(
                "INSERT INTO os_stock_applied(os_id, inventory_id, qty, updated_at) VALUES (?,?,?,?)",
                (os_id, int(inv_id), float(qty), now),
            )

def _desired_parts_from_items(items: list) -> dict[int, float]:
    desired: dict[int, float] = {}
    for it in items or []:
        inv_id = it.get("inventory_id")
        is_labor = int(it.get("is_labor") or 0)
        if inv_id and is_labor == 0:
            desired[int(inv_id)] = desired.get(int(inv_id), 0.0) + float(it.get("qty") or 0)
    return desired

def _check_stock_for_delta(db, delta_needed: dict[int, float]) -> list[dict]:
    """Retorna lista de faltas: [{name, have, need, inv_id}]"""
    faltas = []
    for inv_id, delta in delta_needed.items():
        if delta <= 0:
            continue
        row = db.execute("SELECT name, stock FROM inventory WHERE id = ?", (inv_id,)).fetchone()
        if not row:
            continue
        have = float(row["stock"] or 0)
        if have + 1e-9 < float(delta):
            faltas.append({
                "inv_id": int(inv_id),
                "name": row["name"],
                "have": have,
                "need": float(delta),
            })
    return faltas

def reconcile_os_stock(db, os_id: int, os_status: str, items: list) -> tuple[bool, list[dict]]:
    """Aplica (ou desfaz) a baixa de estoque da OS com base no status.
    - Se FECHADA: aplica delta entre 'desired' e 'applied'
    - Caso contrário: desfaz tudo que já estava aplicado
    """
    applied = _get_os_applied_parts(db, os_id)
    desired = _desired_parts_from_items(items) if _is_os_closed(os_status) else {}

    # calcula delta positivo (o que precisa BAIXAR a mais)
    delta_plus: dict[int, float] = {}
    keys = set(desired) | set(applied)
    for inv_id in keys:
        d = float(desired.get(inv_id, 0.0) - applied.get(inv_id, 0.0))
        if d > 0:
            delta_plus[inv_id] = d

    faltas = _check_stock_for_delta(db, delta_plus)
    if faltas:
        return False, faltas

    # aplica deltas (pode ser negativo = devolver)
    for inv_id in keys:
        d = float(desired.get(inv_id, 0.0) - applied.get(inv_id, 0.0))
        if d > 0:
            db.execute("UPDATE inventory SET stock = stock - ? WHERE id = ?", (d, inv_id))
        elif d < 0:
            db.execute("UPDATE inventory SET stock = stock + ? WHERE id = ?", (-d, inv_id))

    _set_os_applied_parts(db, os_id, desired)
    return True, []
def sync_os_to_finance(
    db,
    os_id: int,
    client_name: str | None,
    os_status: str,
    pay_method: str,
    pay_status: str,
    base_labor: float,
    items: list,
):
    closed = _is_os_closed(os_status)
    """Cria/atualiza lançamento do financeiro baseado na OS + detalhamento (serviços/peças e estoque)."""
    os_st = (os_status or "").strip().lower()
    ps = (pay_status or "").strip().lower()

    # Sempre sincroniza a OS com o Financeiro:
    # - Aberta/Em andamento -> PENDENTE
    # - Fechada + Efetivado -> EFETIVADO
    # - Cancelada/Cancelado -> CANCELADO
    items_total = sum(float(it.get("total") or 0) for it in (items or []))
    total = float(base_labor or 0) + float(items_total or 0)

    cn = (client_name or "").strip()
    desc = f"OS #{os_id}" + (f" - {cn}" if cn else "")

    method_id = _get_method_id(db, pay_method or "Dinheiro")
    cat_id = _get_category_id(db, "Serviços / OS")

    tx_status = _tx_status_from_pay(pay_status, os_status)
    tx_date = _today_iso()

    existing = db.execute(
        "SELECT id FROM fin_transactions WHERE ref_type='OS' AND ref_id=?",
        (os_id,),
    ).fetchone()

    if existing:
        db.execute(
            """
            UPDATE fin_transactions
               SET description=?,
                   amount=?,
                   date=?,
                   due_date=?,
                   status=?,
                   payment_method_id=?,
                   category_id=?,
                   updated_at=?
             WHERE id=?
            """,
            (desc, total, tx_date, tx_date, tx_status, method_id, cat_id, _now_iso(), existing["id"]),
        )
        fin_tx_id = int(existing["id"])
    else:
        cur = db.execute(
            """
            INSERT INTO fin_transactions(ttype, description, amount, date, due_date, status, payment_method_id, category_id, ref_type, ref_id, created_at)
            VALUES ('IN',?,?,?,?,?,?,?,?,?,?)
            """,
            (desc, total, tx_date, tx_date, tx_status, method_id, cat_id, "OS", os_id, _now_iso()),
        )
        fin_tx_id = int(cur.lastrowid)

    # detalhamento: o que entrou (serviços/peças) e o que saiu (estoque)
    rows = []
    if float(base_labor or 0) > 0:
        rows.append(("money", "IN", None, "Mão de obra", 1, float(base_labor), float(base_labor)))

    for it in (items or []):
        is_labor = int(it.get("is_labor") or 0) == 1
        inv_id = it.get("inventory_id")
        d = (it.get("description") or "").strip()
        qty = float(it.get("qty") or 1)
        unit = float(it.get("unit_price") or 0)
        tot = float(it.get("total") or 0)

        # financeiro: entrada
        rows.append(("money", "IN", int(inv_id) if inv_id else None, d, qty, unit, tot))

        # estoque: saída (somente para peças vinculadas ao estoque)
        if closed and (not is_labor) and inv_id:
            rows.append(("stock", "OUT", int(inv_id), d, qty, 0.0, 0.0))

    _rebuild_fin_tx_items(db, fin_tx_id, rows)

    try:
        db.execute("UPDATE orders SET fin_tx_id=? WHERE id=?", (fin_tx_id, os_id))
    except Exception:
        pass


@login_required
@app.route("/financeiro")
def financeiro_dashboard():
    db = get_db()
    today = _today_iso()
    ym = datetime.date.today().replace(day=1).isoformat()
    start = _parse_date(request.args.get("start"), ym)
    end = _parse_date(request.args.get("end"), today)

    def _sum(where_sql, params):
        r = db.execute(f"SELECT COALESCE(SUM(amount),0) s FROM fin_transactions WHERE {where_sql}", params).fetchone()
        return float(r["s"] or 0)

    receitas = _sum("ttype='IN' AND status='EFETIVADO' AND date BETWEEN ? AND ?", (start, end))
    despesas = _sum("ttype='OUT' AND status='EFETIVADO' AND date BETWEEN ? AND ?", (start, end))
    saldo = receitas - despesas
    pend_receber = _sum("ttype='IN' AND status='PENDENTE' AND date BETWEEN ? AND ?", (start, end))
    pend_pagar = _sum("ttype='OUT' AND status='PENDENTE' AND date BETWEEN ? AND ?", (start, end))

    methods = db.execute("SELECT id, name FROM fin_payment_methods ORDER BY name").fetchall()
    by_method = {}
    for m in methods:
        r = db.execute(
            """
            SELECT COALESCE(SUM(amount),0) s
              FROM fin_transactions
             WHERE ttype='IN' AND status='EFETIVADO'
               AND payment_method_id=?
               AND date BETWEEN ? AND ?
            """,
            (m["id"], start, end),
        ).fetchone()
        by_method[m["name"]] = float(r["s"] or 0)
    # Gráfico: Receitas x Despesas por mês
    # Por padrão, mostra os últimos 12 meses (ancorado no "Fim" do filtro).
    try:
        d_start = datetime.date.fromisoformat(start)
        d_end = datetime.date.fromisoformat(end)
    except Exception:
        d_start = datetime.date.today().replace(day=1)
        d_end = datetime.date.today()

    span_days = (d_end - d_start).days
    if span_days < 60:
        chart_end = d_end
        y, mo = chart_end.year, chart_end.month
        for _ in range(11):
            mo -= 1
            if mo == 0:
                mo = 12
                y -= 1
        chart_start = datetime.date(y, mo, 1)
    else:
        chart_start = datetime.date(d_start.year, d_start.month, 1)
        chart_end = d_end

    chart_start_iso = chart_start.isoformat()
    chart_end_iso = chart_end.isoformat()

    rows_m = db.execute(
        """
        SELECT strftime('%Y-%m', date) ym,
               COALESCE(SUM(CASE WHEN ttype='IN'  THEN amount ELSE 0 END),0) receitas,
               COALESCE(SUM(CASE WHEN ttype='OUT' THEN amount ELSE 0 END),0) despesas
          FROM fin_transactions
         WHERE status='EFETIVADO'
           AND date BETWEEN ? AND ?
         GROUP BY ym
         ORDER BY ym
        """,
        (chart_start_iso, chart_end_iso),
    ).fetchall()

    mdata = {r["ym"]: (float(r["receitas"] or 0), float(r["despesas"] or 0)) for r in rows_m}

    def _iter_months(a: datetime.date, b: datetime.date):
        y, mo = a.year, a.month
        end_y, end_mo = b.year, b.month
        while (y < end_y) or (y == end_y and mo <= end_mo):
            yield y, mo
            mo += 1
            if mo == 13:
                mo = 1
                y += 1

    monthly_labels = []
    monthly_receitas = []
    monthly_despesas = []
    for y, mo in _iter_months(chart_start, chart_end):
        key = f"{y:04d}-{mo:02d}"
        monthly_labels.append(f"{mo:02d}/{y:04d}")
        rin, rout = mdata.get(key, (0.0, 0.0))
        monthly_receitas.append(rin)
        monthly_despesas.append(rout)



    last = db.execute(
        """
        SELECT t.*, pm.name AS pm_name, c.name AS cat_name
          FROM fin_transactions t
          LEFT JOIN fin_payment_methods pm ON pm.id=t.payment_method_id
          LEFT JOIN fin_categories c ON c.id=t.category_id
         ORDER BY t.date DESC, t.id DESC
         LIMIT 15
        """
    ).fetchall()

    return render_template(
        "financeiro_dashboard.html",
        title="Financeiro",
        start=start,
        end=end,
        receitas=receitas,
        despesas=despesas,
        saldo=saldo,
        pend_receber=pend_receber,
        pend_pagar=pend_pagar,
        by_method=by_method,
        chart_start=chart_start_iso,
        chart_end=chart_end_iso,
        monthly_labels=monthly_labels,
        monthly_receitas=monthly_receitas,
        monthly_despesas=monthly_despesas,
        last=last,
    )


@login_required
@app.route("/financeiro/lancamentos")
def financeiro_lancamentos():
    db = get_db()
    today = _today_iso()
    ym = datetime.date.today().replace(day=1).isoformat()
    start = _parse_date(request.args.get("start"), ym)
    end = _parse_date(request.args.get("end"), today)
    ttype = (request.args.get("ttype") or "").strip()
    status = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()

    where = ["date BETWEEN ? AND ?"]
    params = [start, end]
    if ttype in ["IN", "OUT"]:
        where.append("ttype=?")
        params.append(ttype)
    if status in ["PENDENTE", "EFETIVADO", "CANCELADO"]:
        where.append("status=?")
        params.append(status)
    if q:
        where.append("(description LIKE ?)")
        params.append(f"%{q}%")

    rows = db.execute(
        f"""
        SELECT t.*, pm.name AS pm_name, c.name AS cat_name
          FROM fin_transactions t
          LEFT JOIN fin_payment_methods pm ON pm.id=t.payment_method_id
          LEFT JOIN fin_categories c ON c.id=t.category_id
         WHERE {' AND '.join(where)}
         ORDER BY t.date DESC, t.id DESC
        """,
        params,
    ).fetchall()

    return render_template(
        "financeiro_lancamentos.html",
        title="Lançamentos",
        rows=rows,
        start=start,
        end=end,
        ttype=ttype,
        status=status,
        q=q,
    )





@login_required
@app.route("/financeiro/estoque")
def financeiro_estoque():
    db = get_db()
    today = _today_iso()
    ym = datetime.date.today().replace(day=1).isoformat()
    start = _parse_date(request.args.get("start"), ym)
    end = _parse_date(request.args.get("end"), today)

    direction = (request.args.get("dir") or "").strip().upper()
    ref_type = (request.args.get("ref_type") or "").strip().upper()
    item_id = (request.args.get("item_id") or "").strip()
    q = (request.args.get("q") or "").strip()

    where = ["ft.date BETWEEN ? AND ?", "it.flow='stock'"]
    params = [start, end]

    if direction in ("IN", "OUT"):
        where.append("it.direction=?")
        params.append(direction)
    if ref_type in ("OS", "PURCHASE", "ADHOC"):
        where.append("ft.ref_type=?")
        params.append(ref_type)
    if item_id.isdigit():
        where.append("it.inventory_id=?")
        params.append(int(item_id))
    if q:
        where.append("(COALESCE(inv.name,'') LIKE ? OR COALESCE(it.description,'') LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    rows = db.execute(
        f"""
        SELECT
            it.id AS item_row_id,
            it.tx_id,
            it.direction,
            it.inventory_id,
            it.description AS item_desc,
            it.qty,
            it.unit_value,
            it.total,
            ft.date,
            ft.status,
            ft.ref_type,
            ft.ref_id,
            ft.description AS tx_desc,
            inv.name AS inv_name,
            inv.sku AS inv_sku,
            inv.stock AS inv_stock
        FROM fin_transaction_items it
        JOIN fin_transactions ft ON ft.id=it.tx_id
        LEFT JOIN inventory inv ON inv.id=it.inventory_id
        WHERE {' AND '.join(where)}
        ORDER BY ft.date DESC, ft.id DESC, it.id DESC
        """,
        params,
    ).fetchall()

    def fnum(x):
        try:
            return float(x or 0)
        except Exception:
            return 0.0

    qty_in = sum(fnum(r["qty"]) for r in rows if (r["direction"] or "").upper() == "IN")
    qty_out = sum(fnum(r["qty"]) for r in rows if (r["direction"] or "").upper() == "OUT")
    val_in = sum(fnum(r["total"]) for r in rows if (r["direction"] or "").upper() == "IN")
    val_out = sum(fnum(r["total"]) for r in rows if (r["direction"] or "").upper() == "OUT")

    # Agrupado por peça
    by_item = {}
    for r in rows:
        inv_id = r["inventory_id"]
        name = r["inv_name"] or r["item_desc"] or (f"Item #{inv_id}" if inv_id else "Item")
        if inv_id not in by_item:
            by_item[inv_id] = {
                "inventory_id": inv_id,
                "name": name,
                "sku": r["inv_sku"],
                "in_qty": 0.0,
                "out_qty": 0.0,
                "in_val": 0.0,
                "out_val": 0.0,
                "current_stock": fnum(r["inv_stock"]),
            }
        d = (r["direction"] or "").upper()
        if d == "IN":
            by_item[inv_id]["in_qty"] += fnum(r["qty"])
            by_item[inv_id]["in_val"] += fnum(r["total"])
        else:
            by_item[inv_id]["out_qty"] += fnum(r["qty"])
            by_item[inv_id]["out_val"] += fnum(r["total"])

    by_item_rows = list(by_item.values())
    by_item_rows.sort(key=lambda x: (-(x["in_qty"] + x["out_qty"]), (x["name"] or "")))

    # Agrupado por documento (OS/Compra)
    by_ref = {}
    for r in rows:
        key = (r["ref_type"] or "", int(r["ref_id"] or 0))
        if key not in by_ref:
            by_ref[key] = {
                "ref_type": r["ref_type"],
                "ref_id": r["ref_id"],
                "date": r["date"],
                "in_qty": 0.0,
                "out_qty": 0.0,
                "items": [],
            }
        d = (r["direction"] or "").upper()
        if d == "IN":
            by_ref[key]["in_qty"] += fnum(r["qty"])
        else:
            by_ref[key]["out_qty"] += fnum(r["qty"])
        nm = r["inv_name"] or r["item_desc"]
        if nm:
            by_ref[key]["items"].append(str(nm))

    by_ref_rows = list(by_ref.values())
    for rr in by_ref_rows:
        # reduz lista (mantém únicas na ordem)
        seen=set()
        uniq=[]
        for itn in rr["items"]:
            if itn not in seen:
                seen.add(itn)
                uniq.append(itn)
        rr["items_preview"] = ", ".join(uniq[:6]) + ("…" if len(uniq) > 6 else "")
        rr["items_count"] = len(uniq)
    by_ref_rows.sort(key=lambda x: (x["date"] or "", x["ref_type"] or "", int(x["ref_id"] or 0)), reverse=True)

    inventory_options = db.execute(
        "SELECT id, name, sku FROM inventory ORDER BY name"
    ).fetchall()

    return render_template(
        "financeiro_estoque.html",
        title="Extrato de Estoque",
        rows=rows,
        start=start,
        end=end,
        direction=direction,
        ref_type=ref_type,
        item_id=item_id,
        q=q,
        qty_in=qty_in,
        qty_out=qty_out,
        val_in=val_in,
        val_out=val_out,
        by_item_rows=by_item_rows,
        by_ref_rows=by_ref_rows,
        inventory_options=inventory_options,
    )


@login_required
@app.route("/financeiro/lancamentos/<int:tx_id>")
def financeiro_ver(tx_id):
    db = get_db()
    tx = db.execute(
        """
        SELECT t.*, pm.name AS pm_name, c.name AS cat_name
          FROM fin_transactions t
          LEFT JOIN fin_payment_methods pm ON pm.id=t.payment_method_id
          LEFT JOIN fin_categories c ON c.id=t.category_id
         WHERE t.id=?
        """,
        (tx_id,),
    ).fetchone()

    if not tx:
        flash("Lançamento não encontrado.", "error")
        return redirect(url_for("financeiro_lancamentos"))

    items = db.execute(
        """
        SELECT it.*, inv.name AS inv_name, inv.sku AS inv_sku
          FROM fin_transaction_items it
          LEFT JOIN inventory inv ON inv.id=it.inventory_id
         WHERE it.tx_id=?
         ORDER BY it.flow, it.direction, it.id
        """,
        (tx_id,),
    ).fetchall()

    money_in  = [r for r in items if (r["flow"] == "money" and r["direction"] == "IN")]
    money_out = [r for r in items if (r["flow"] == "money" and r["direction"] == "OUT")]
    stock_in  = [r for r in items if (r["flow"] == "stock" and r["direction"] == "IN")]
    stock_out = [r for r in items if (r["flow"] == "stock" and r["direction"] == "OUT")]

    sum_money_in = sum([r["total"] for r in money_in]) if money_in else 0
    sum_money_out = sum([r["total"] for r in money_out]) if money_out else 0

    return render_template(
        "financeiro_tx_view.html",
        title=f"Detalhes do lançamento #{tx_id}",
        tx=tx,
        money_in=money_in,
        money_out=money_out,
        stock_in=stock_in,
        stock_out=stock_out,
        sum_money_in=sum_money_in,
        sum_money_out=sum_money_out,
    )


@login_required
@app.route("/financeiro/lancamentos/novo", methods=["GET","POST"])
def financeiro_novo():
    db = get_db()
    methods = db.execute("SELECT id, name FROM fin_payment_methods ORDER BY name").fetchall()
    cats = db.execute("SELECT id, name FROM fin_categories ORDER BY name").fetchall()

    if request.method == "POST":
        ttype = request.form.get("ttype") or "IN"
        description = (request.form.get("description") or "").strip()
        amount = float(request.form.get("amount") or 0)
        date = _parse_date(request.form.get("date"), _today_iso())
        due_date = _parse_date(request.form.get("due_date"), date)
        status = (request.form.get("status") or "PENDENTE").strip().upper()
        pm_id = request.form.get("payment_method_id") or None
        cat_id = request.form.get("category_id") or None

        if not description:
            flash("Descrição é obrigatória.", "error")
        else:
            db.execute(
                """
                INSERT INTO fin_transactions(ttype, description, amount, date, due_date, status, payment_method_id, category_id, ref_type, ref_id, created_at)
                VALUES (?,?,?,?,?,?,?,?,NULL,NULL,?)
                """,
                (ttype, description, amount, date, due_date, status, pm_id, cat_id, _now_iso()),
            )
            db.commit()
            flash("Lançamento criado.", "ok")
            return redirect(url_for("financeiro_lancamentos"))

    return render_template("financeiro_form.html", title="Novo lançamento", methods=methods, cats=cats, row=None)


@login_required
@app.route("/financeiro/lancamentos/<int:tx_id>/editar", methods=["GET","POST"])
def financeiro_editar(tx_id):
    db = get_db()
    row = db.execute("SELECT * FROM fin_transactions WHERE id=?", (tx_id,)).fetchone()
    if not row:
        flash("Lançamento não encontrado.", "error")
        return redirect(url_for("financeiro_lancamentos"))

    methods = db.execute("SELECT id, name FROM fin_payment_methods ORDER BY name").fetchall()
    cats = db.execute("SELECT id, name FROM fin_categories ORDER BY name").fetchall()

    if request.method == "POST":
        locked = (row["ref_type"] in ["OS", "PURCHASE"])
        if locked:
            status = (request.form.get("status") or row["status"]).strip().upper()
            pm_id = request.form.get("payment_method_id") or row["payment_method_id"]
            db.execute(
                "UPDATE fin_transactions SET status=?, payment_method_id=?, updated_at=? WHERE id=?",
                (status, pm_id, _now_iso(), tx_id),
            )
        else:
            ttype = request.form.get("ttype") or row["ttype"]
            description = (request.form.get("description") or "").strip()
            amount = float(request.form.get("amount") or 0)
            date = _parse_date(request.form.get("date"), row["date"])
            due_date = _parse_date(request.form.get("due_date"), row["due_date"] or date)
            status = (request.form.get("status") or "PENDENTE").strip().upper()
            pm_id = request.form.get("payment_method_id") or None
            cat_id = request.form.get("category_id") or None

            db.execute(
                """
                UPDATE fin_transactions
                   SET ttype=?, description=?, amount=?, date=?, due_date=?, status=?,
                       payment_method_id=?, category_id=?, updated_at=?
                 WHERE id=?
                """,
                (ttype, description, amount, date, due_date, status, pm_id, cat_id, _now_iso(), tx_id),
            )

        db.commit()
        flash("Lançamento atualizado.", "ok")
        return redirect(url_for("financeiro_lancamentos"))

    return render_template("financeiro_form.html", title=f"Editar lançamento #{tx_id}", methods=methods, cats=cats, row=row)


@login_required
@app.route("/financeiro/lancamentos/<int:tx_id>/cancelar", methods=["POST"])
def financeiro_cancelar(tx_id):
    db = get_db()
    db.execute("UPDATE fin_transactions SET status='CANCELADO', updated_at=? WHERE id=?", (_now_iso(), tx_id))
    db.commit()
    flash("Lançamento cancelado.", "ok")
    return redirect(url_for("financeiro_lancamentos"))


# --------------------------
# Serviços avulsos (rápido)
# --------------------------
@login_required
@app.route("/financeiro/servico_avulso", methods=["GET","POST"])
def servico_avulso():
    db = get_db()
    methods = db.execute("SELECT id, name FROM fin_payment_methods ORDER BY name").fetchall()
    cat_id = _get_category_id(db, "Vendas avulsas")

    if request.method == "POST":
        description = (request.form.get("description") or "").strip()
        amount = float(request.form.get("amount") or 0)
        date = _parse_date(request.form.get("date"), _today_iso())
        status = (request.form.get("status") or "EFETIVADO").strip().upper()
        pm_id = request.form.get("payment_method_id") or None

        if not description:
            flash("Descrição é obrigatória.", "error")
        else:
            db.execute(
                """
                INSERT INTO fin_transactions(ttype, description, amount, date, due_date, status, payment_method_id, category_id, ref_type, ref_id, created_at)
                VALUES ('IN',?,?,?,?,?,?,?,?,?,?)
                """,
                (description, amount, date, date, status, pm_id, cat_id, "ADHOC", None, _now_iso()),
            )
            db.commit()
            flash("Serviço avulso lançado.", "ok")
            return redirect(url_for("financeiro_dashboard"))

    return render_template("servico_avulso_form.html", title="Serviço avulso", methods=methods)


# --------------------------
# Compras de estoque
# --------------------------
def _purchase_stock_adjust(db, old_items, new_items, old_eff: bool, new_eff: bool):
    """Ajusta estoque por delta considerando status antigo/novo (Efetivado aplica)."""
    def agg(items):
        d={}
        for it in items:
            inv=int(it["inventory_id"])
            d[inv]=d.get(inv,0.0)+float(it["qty"])
        return d

    old_map = agg(old_items) if old_eff else {}
    new_map = agg(new_items) if new_eff else {}
    all_ids = set(old_map.keys()) | set(new_map.keys())

    for inv_id in all_ids:
        delta = float(new_map.get(inv_id,0.0) - old_map.get(inv_id,0.0))
        if abs(delta) < 1e-9:
            continue
        if delta > 0:
            row = db.execute("SELECT stock, cost_price FROM inventory WHERE id=?", (inv_id,)).fetchone()
            if row:
                cur_stock = float(row["stock"] or 0)
                cur_cost = float(row["cost_price"] or 0)
                unit_cost = None
                for it in new_items:
                    if int(it["inventory_id"]) == inv_id:
                        unit_cost = float(it["unit_cost"] or 0)
                        break
                if unit_cost is None:
                    unit_cost = cur_cost
                if cur_stock + delta > 0:
                    new_cost = ((cur_stock*cur_cost) + (delta*unit_cost)) / (cur_stock + delta)
                    db.execute("UPDATE inventory SET cost_price=? WHERE id=?", (new_cost, inv_id))
        db.execute("UPDATE inventory SET stock = stock + ? WHERE id=?", (delta, inv_id))


def _upsert_purchase_fin_tx(db, purchase_id: int, supplier: str, total: float, date: str, due_date: str|None, status: str, payment_method_id, items: list):
    cat_id = _get_category_id(db, "Compras de Estoque")
    tx_status = (status or "PENDENTE").strip().upper()
    desc = f"Compra #{purchase_id} - {supplier}".strip()

    existing = db.execute(
        "SELECT id FROM fin_transactions WHERE ref_type='PURCHASE' AND ref_id=?",
        (purchase_id,),
    ).fetchone()

    if existing:
        db.execute(
            """
            UPDATE fin_transactions
               SET description=?, amount=?, date=?, due_date=?, status=?,
                   payment_method_id=?, category_id=?, updated_at=?
             WHERE id=?
            """,
            (desc, total, date, due_date, tx_status, payment_method_id, cat_id, _now_iso(), existing["id"]),
        )
        fin_tx_id = int(existing["id"])
    else:
        cur = db.execute(
            """
            INSERT INTO fin_transactions(ttype, description, amount, date, due_date, status, payment_method_id, category_id, ref_type, ref_id, created_at)
            VALUES ('OUT',?,?,?,?,?,?,?,?,?,?)
            """,
            (desc, total, date, due_date, tx_status, payment_method_id, cat_id, "PURCHASE", purchase_id, _now_iso()),
        )
        fin_tx_id = int(cur.lastrowid)

    # detalhamento: dinheiro (saída) e estoque (entrada)
    rows = []
    inv_ids = [int(it.get("inventory_id")) for it in (items or []) if it.get("inventory_id")]
    inv_map = {}
    if inv_ids:
        qmarks = ",".join(["?"] * len(set(inv_ids)))
        for r in db.execute(f"SELECT id, name FROM inventory WHERE id IN ({qmarks})", tuple(set(inv_ids))).fetchall():
            inv_map[int(r["id"])] = r["name"]

    for it in (items or []):
        inv_id = int(it.get("inventory_id"))
        qty = float(it.get("qty") or 0)
        unit_cost = float(it.get("unit_cost") or 0)
        tot = float(it.get("total") or (qty * unit_cost))
        desc_item = inv_map.get(inv_id) or f"Item #{inv_id}"
        rows.append(("money", "OUT", inv_id, desc_item, qty, unit_cost, tot))
        if (status or "").strip().upper() == "EFETIVADO":
            rows.append(("stock", "IN", inv_id, desc_item, qty, unit_cost, tot))

    _rebuild_fin_tx_items(db, fin_tx_id, rows)
    return fin_tx_id


@login_required
@app.route("/financeiro/compras")
def compras_list():
    db = get_db()
    rows = db.execute(
        """
        SELECT p.*, pm.name AS pm_name
          FROM purchase_orders p
          LEFT JOIN fin_payment_methods pm ON pm.id=p.payment_method_id
         ORDER BY p.date DESC, p.id DESC
        """
    ).fetchall()
    return render_template("compras_list.html", title="Compras", rows=rows)


@login_required
@app.route("/financeiro/compras/nova", methods=["GET","POST"])
def compras_nova():
    return _compras_form(None)


@login_required
@app.route("/financeiro/compras/<int:purchase_id>/editar", methods=["GET","POST"])
def compras_editar(purchase_id):
    return _compras_form(purchase_id)


def _compras_form(purchase_id: int|None):
    db = get_db()
    methods = db.execute("SELECT id, name FROM fin_payment_methods ORDER BY name").fetchall()
    inv = db.execute("SELECT id, name, sku, stock, cost_price FROM inventory ORDER BY name").fetchall()

    row = None
    items = []
    if purchase_id:
        row = db.execute("SELECT * FROM purchase_orders WHERE id=?", (purchase_id,)).fetchone()
        if not row:
            flash("Compra não encontrada.", "error")
            return redirect(url_for("compras_list"))
        items = db.execute(
            """
            SELECT pi.*, i.name AS inv_name, i.sku AS inv_sku
              FROM purchase_items pi
              JOIN inventory i ON i.id=pi.inventory_id
             WHERE pi.purchase_id=?
            """,
            (purchase_id,),
        ).fetchall()

    if request.method == "POST":
        supplier = (request.form.get("supplier") or "").strip()
        doc_number = (request.form.get("doc_number") or "").strip()
        date = _parse_date(request.form.get("date"), _today_iso())
        due_date = _parse_date(request.form.get("due_date"), date) if request.form.get("due_date") else None
        status = (request.form.get("status") or "PENDENTE").strip().upper()
        pm_id = request.form.get("payment_method_id") or None
        notes = (request.form.get("notes") or "").strip()

        new_items=[]
        total=0.0
        for i in range(1, 61):
            inv_id = request.form.get(f"item_inv_{i}")
            qty = request.form.get(f"item_qty_{i}")
            unit = request.form.get(f"item_cost_{i}")
            if not inv_id or not qty:
                continue
            inv_id = int(inv_id)
            qty = float(qty)
            unit_cost = float(unit or 0)
            if qty <= 0:
                continue
            line_total = qty * unit_cost
            total += line_total
            new_items.append({"inventory_id": inv_id, "qty": qty, "unit_cost": unit_cost, "total": line_total})

        if not supplier:
            flash("Fornecedor é obrigatório.", "error")
        elif not new_items:
            flash("Adicione pelo menos 1 item.", "error")
        else:
            old_status = None
            old_items = []
            if purchase_id:
                old_status = (row["status"] or "PENDENTE").strip().upper()
                old_items = db.execute("SELECT inventory_id, qty, unit_cost, total FROM purchase_items WHERE purchase_id=?", (purchase_id,)).fetchall()

            if purchase_id:
                db.execute(
                    """
                    UPDATE purchase_orders
                       SET supplier=?, doc_number=?, date=?, due_date=?, status=?, payment_method_id=?, notes=?, total=?, updated_at=?
                     WHERE id=?
                    """,
                    (supplier, doc_number, date, due_date, status, pm_id, notes, total, _now_iso(), purchase_id),
                )
                db.execute("DELETE FROM purchase_items WHERE purchase_id=?", (purchase_id,))
                db.executemany(
                    "INSERT INTO purchase_items(purchase_id, inventory_id, qty, unit_cost, total) VALUES (?,?,?,?,?)",
                    [(purchase_id, it["inventory_id"], it["qty"], it["unit_cost"], it["total"]) for it in new_items],
                )
            else:
                cur = db.execute(
                    """
                    INSERT INTO purchase_orders(supplier, doc_number, date, due_date, status, payment_method_id, notes, total, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (supplier, doc_number, date, due_date, status, pm_id, notes, total, _now_iso()),
                )
                purchase_id = int(cur.lastrowid)
                db.executemany(
                    "INSERT INTO purchase_items(purchase_id, inventory_id, qty, unit_cost, total) VALUES (?,?,?,?,?)",
                    [(purchase_id, it["inventory_id"], it["qty"], it["unit_cost"], it["total"]) for it in new_items],
                )

            old_eff = (old_status == "EFETIVADO") if old_status is not None else False
            new_eff = (status == "EFETIVADO")
            _purchase_stock_adjust(db, old_items, new_items, old_eff, new_eff)

            fin_tx_id = _upsert_purchase_fin_tx(db, purchase_id, supplier, total, date, due_date, status, pm_id, new_items)
            try:
                db.execute("UPDATE purchase_orders SET fin_tx_id=? WHERE id=?", (fin_tx_id, purchase_id))
            except Exception:
                pass

            db.commit()
            flash("Compra salva com sucesso!", "ok")
            return redirect(url_for("compras_list"))

    return render_template(
        "compra_form.html",
        title=("Editar compra" if purchase_id else "Nova compra"),
        row=row,
        items=items,
        methods=methods,
        inv=inv,
    )


if __name__ == "__main__":
    first_time = not os.path.exists(DB_PATH)
    with app.app_context():
        init_db()
    if first_time:
        print("Banco criado em", DB_PATH)
    print(f"================== {APP_TITLE} ==================")
    print("Acesse: http://127.0.0.1:5055/")
    app.run(host="0.0.0.0", port=5055, debug=True)


def _qr_image(data: str):
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@login_required
@app.route("/acesso")
def acesso():
    # URL base para os mecânicos acessarem (mesma rede)
    ip = get_local_ip()
    url = f"http://{ip}:5055/"
    return render_template("acesso.html", url=url, title="Acesso para Mecânicos")

@app.route("/qr")
def qr_generic():
    data = request.args.get("data") or request.host_url
    return _qr_image(data)

@app.route("/qr/os/<int:os_id>")
def qr_os_alt(os_id):
    url = url_for("os_view", os_id=os_id, _external=True)
    return _qr_image(url)


def get_local_ip(default_host: str = "127.0.0.1"):
    """Descobre o IP da rede local para uso nos QRCodes (ex: 10.x, 192.x)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return default_host