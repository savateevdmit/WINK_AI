# ---------- Base image ----------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    TZ=UTC

WORKDIR /app

# Системные зависимости для сборки C-расширений (pycairo, llama-cpp-python)
# и для рендеринга PDF/HTML (WeasyPrint/cairo/pango/gdk-pixbuf)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # компилятор и инструменты сборки \
    build-essential \
    pkg-config \
    cmake \
    # cairo + dev для сборки pycairo
    libcairo2 \
    libcairo2-dev \
    # pango, gdk-pixbuf — runtime для WeasyPrint
    libpango-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    # полезные dev-библиотеки
    libffi-dev \
    libjpeg62-turbo-dev \
    libpng-dev \
    # прочее
    curl \
    shared-mime-info \
    fonts-dejavu \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# ---------- Python deps ----------
COPY back/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ---------- App ----------
COPY back /app

# Папка для данных (хранилище)
RUN mkdir -p "$DATA_DIR"

EXPOSE 8000

# Продовый запуск (без --reload)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]