FROM python:3.13-slim
WORKDIR /app
# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends tree grep git curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Create dirs
RUN mkdir -p uploads && mkdir -p /root/.omniagent/tools
EXPOSE 8000
CMD ["uvicorn", "omni_agent:app", "--host", "0.0.0.0", "--port", "8000"]
