# Gunicorn entrypoint: gunicorn wsgi:app
from app import app, init_db

# Garante que o banco exista e tenha as tabelas/colunas necessárias.
with app.app_context():
    init_db()
