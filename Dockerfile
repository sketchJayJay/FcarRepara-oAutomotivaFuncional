FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN chmod +x start.sh

# Coolify/Render definem a variável PORT automaticamente.
EXPOSE 5055

CMD ["bash", "start.sh"]
