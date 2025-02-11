ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /src

ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid ${UID} \
    appuser

# Update and install system dependencies in separate steps
RUN apt-get update && apt-get install -y \
    libxcb-shm0 \
    libx11-xcb1 \
    libx11-6 \
    libxcb1 \
    libxext6 \
    libxrandr2 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxfixes3 \
    libxi6 \
    libatk1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libpango-1.0-0 \
    libglib2.0-0 \
    libgtk-3-dev \
    libasound2 \
    libfreetype6 \
    libfontconfig1 \
    libdbus-1-3 \
    redis-tools \
    curl \
    iputils-ping

RUN apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements/dev.txt /src/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -r requirements.txt

# Install Playwright and its dependencies
RUN python -m pip install playwright
RUN python -m playwright install-deps
RUN python -m playwright install

# Copy application code
COPY . .

EXPOSE 5001

CMD ["./boot.sh"]
