# FCAR Reparação Automotiva (Coolify)

Este projeto já vai com o **banco `oficina.db` preenchido** (clientes + OS) a partir dos PDFs que você mandou.

## 1) Subir para o GitHub

> Importante: o `.gitignore` foi ajustado para **versionar só o `oficina.db`**.
> Use **repositório privado** (tem dados de clientes).

1. Faça commit e push normalmente.

## 2) Criar o app no Coolify

1. **New Resource** → Application → **GitHub Repo**
2. Build: **Dockerfile** (já está no projeto)

## 3) Variáveis de ambiente

Defina estas variáveis no Coolify:

- `PORT` = `5055` (ou deixe o Coolify definir, mas 5055 é o padrão do projeto)
- `FCAR_DB_PATH` = `/data/oficina.db`
- `SECRET_KEY` = (coloque uma chave forte, ex: `fcar-<qualquer-coisa-grande>`)

## 4) Volume persistente (para não perder OS)

Crie um **volume** e monte em:

- **Mount Path**: `/data`

O `start.sh` faz isso automaticamente:

- Se existir `FCAR_DB_PATH=/data/oficina.db`
- E **ainda não existir** `/data/oficina.db`
- Ele copia o `oficina.db` do repositório para dentro do volume.

✅ Resultado: nas próximas atualizações, o banco fica no volume e você não perde nada.

## 5) Conferência rápida (no terminal do container)

No terminal do Coolify, rode:

```bash
ls -lah /data
python - <<'PY'
import sqlite3
db='/data/oficina.db'
con=sqlite3.connect(db)
cur=con.cursor()
print('clients:', cur.execute('select count(*) from clients').fetchone()[0])
print('orders:',  cur.execute('select count(*) from orders').fetchone()[0])
print('open:',    cur.execute("select count(*) from orders where status='Aberta'").fetchone()[0])
print('closed:',  cur.execute("select count(*) from orders where status='Fechada'").fetchone()[0])
PY
```

Se aparecer algo como `orders: 106`, está tudo certo.
