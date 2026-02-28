# ==============================================================================
# Stage 1: Build dependencies (including llama-cpp-python from source)
# ==============================================================================
FROM python:3.11-slim AS builder

# Install build tools required for llama-cpp-python compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy requirements and install into a virtual environment
COPY requirements.txt .

# Force CPU-only build of llama-cpp-python (no CUDA, no Metal, no OpenCL)
ENV CMAKE_ARGS="-DGGML_CUDA=OFF -DGGML_METAL=OFF -DGGML_OPENCL=OFF"
ENV FORCE_CMAKE=1

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# ==============================================================================
# Stage 2: Production runtime
# ==============================================================================
FROM python:3.11-slim AS runtime

# Install only runtime shared libraries needed by llama-cpp-python
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY app/ ./app/

# Create directory for models and keys
RUN mkdir -p /app/models && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose the FastAPI port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/health'); r.raise_for_status()" || exit 1

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
