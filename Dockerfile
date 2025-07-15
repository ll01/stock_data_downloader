FROM python:3.11-slim

WORKDIR /app

# Install pip and project dependencies
COPY . .

RUN pip install --no-cache-dir -e .

# Command to run when container starts
CMD ["python", "-m", "stock_data_downloader.run_server", "--config", "/app/config.yaml"]