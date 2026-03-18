FROM python:3.14-slim

# Prevents Python from buffering stdout/stderr
# Critical for Azure container logs — output appears immediately
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install gcc for packages that compile C extensions (pyiceberg, pyroaring)
# Clean up apt cache after to keep image size down
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# No port binding — pure background process
# ACI injects DISCORD_TOKEN, OWNER_ID, SUPABASE_URL, SUPABASE_KEY
# as secure environment variables at runtime
CMD ["python", "-u", "main.py"]