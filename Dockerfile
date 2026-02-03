FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# Guarda um seed do banco com dados (para primeiro deploy)
RUN mkdir -p /app/seed \
 && if [ -f data/oficina.db ]; then cp data/oficina.db /app/seed/oficina.db; fi \
 && chmod +x /app/docker-entrypoint.sh

# Padrões para Docker/Coolify
ENV PORT=5055
ENV DB_PATH=/data/oficina.db

VOLUME ["/data"]
EXPOSE 5055

CMD ["/app/docker-entrypoint.sh"]
