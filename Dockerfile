FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System libraries needed by computer-vision packages.
# Build tools are included for Python packages that compile native extensions.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY ["Source Code/Back End/requirements.txt", "/app/requirements.txt"]

# Install CPU-only PyTorch before the remaining dependencies.
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install -r requirements.txt

COPY ["Source Code/Back End/", "/app/"]
COPY ["Source Code/Front End/", "/app/Front End/"]

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
