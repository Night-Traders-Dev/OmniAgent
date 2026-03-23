FROM python:3.13-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tree grep git curl wget ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY src/ src/
COPY templates/ templates/
COPY omni_agent.py .
COPY gpu_worker.py .
COPY CHANGELOG.md .

# Create required directories
RUN mkdir -p uploads logs data /root/.omniagent/tools

# Expose ports
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/identify || exit 1

# Start server
CMD ["python", "omni_agent.py"]
