FROM python:3.11-slim

# Системные зависимости для WeasyPrint + Cyrillic-шрифты + Pillow (Gemini Vision)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libpangocairo-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-xlib-2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-dejavu \
        fonts-liberation \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/

# Создаём нужные директории
RUN mkdir -p bot/data bot/output

WORKDIR /app/bot

CMD ["python", "main.py"]
