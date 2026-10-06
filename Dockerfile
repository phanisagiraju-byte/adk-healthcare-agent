# Use official lightweight Python 3.13 image
FROM python:3.13-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Create a non-root user for enterprise container security
RUN groupadd --system appgroup && useradd --system --gid appgroup --create-home appuser

# Install Python dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY observability.py tools.py agents.py workflow.py main.py server.py ./

# Drop privileges to non-root user
RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 8080

# Start FastAPI server for Cloud Run
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
