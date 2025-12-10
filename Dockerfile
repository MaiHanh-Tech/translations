FROM mcr.microsoft.com/devcontainers/python:1-3.11-bullseye

WORKDIR /app

# Switch to root to install system dependencies
USER root

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Create streamlit user and group
RUN groupadd -r streamlit && \
    useradd -r -g streamlit streamlit && \
    chown -R streamlit:streamlit /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip3 install --user -r requirements.txt

# Copy the rest of the application
COPY . .
RUN chown -R streamlit:streamlit /app

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# Switch to streamlit user
USER streamlit

ENTRYPOINT ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"] 
