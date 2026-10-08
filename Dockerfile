# Use an official lightweight Python image.
FROM python:3.11-slim

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONUNBUFFERED True

# Set the working directory in the container
ENV APP_HOME /app
WORKDIR $APP_HOME

# Install system dependencies (needed for many Python packages)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy local code to the container image
COPY . .

# Run the web service on container startup. 
# We use gunicorn as the production-grade web server.
# Change 'guillermo.wsgi' to your actual project name if different.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 project_guillermo.wsgi:application