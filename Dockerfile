FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY .env.example ./.env.example

# Create data directories
RUN mkdir -p /app/data/images /app/data/db

# Environment variables
ENV HOST=0.0.0.0
ENV PORT=5643
ENV IMAGES_DIR=/app/data/images
ENV DB_DIR=/app/data/db
ENV DATABASE_URL=sqlite+aiosqlite:///./data/db/picgate.db

# Expose port
EXPOSE 5643

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:5643/health').raise_for_status()" || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5643"]
