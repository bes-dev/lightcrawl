# Playwright Service Dockerfile
# Based on Microsoft's Playwright image for proper browser support

FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/

# Environment defaults
ENV PORT=3000
ENV MAX_CONCURRENT_PAGES=10
ENV TIMEOUT=30000
ENV BLOCK_MEDIA=true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}

CMD ["python", "-m", "src.main"]
