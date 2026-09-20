FROM python:3.10-slim

WORKDIR /app

# Install system dependencies for audio processing and C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files and models
COPY . .

ENV PORT=8000
EXPOSE 8000

CMD ["python", "main.py"]
