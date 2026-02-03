# FCAR no Coolify (com banco persistente)

Este projeto já vem com **Dockerfile** e um **seed do banco** (clientes, estoque e OS importadas dos PDFs).

## Deploy rápido

1) No Coolify, crie um novo App a partir do seu repositório (GitHub).

2) Selecione **Dockerfile** como método de build.

3) Em **Environment Variables**, configure:

- `PORT` = `5055` (ou deixe o padrão)
- `DB_PATH` = `/data/oficina.db`

4) Em **Persistent Storage / Volumes**, crie um volume apontando para:

- **Path**: `/data`

5) Deploy.

✅ Na primeira subida, o `docker-entrypoint.sh` copia o banco seed para `/data/oficina.db`. Depois disso, o volume mantém tudo persistente entre updates.

## Atualizar sem perder dados

- Faça commit/push das mudanças no GitHub
- No Coolify, clique em **Redeploy**
- Como o banco está em `/data`, ele não é sobrescrito.

## Importar novos PDFs no futuro

Se você tiver outro pacote de PDFs, você pode:

- Colocar os PDFs no servidor (ou dentro do container) e rodar:

```bash
python import_migracao_pdfs.py --db /data/oficina.db --pdfdir "/caminho/da/pasta"
```

