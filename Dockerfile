FROM python:3.11-slim

WORKDIR /app

# Install pip and project dependencies
COPY pyproject.toml /app/
RUN pip install --no-cache-dir -e .

# Copy the application source code
COPY . /app/

# Create data directory
RUN mkdir -p /app/data

# Command to run when container starts
CMD ["python", "-m", "stock_data_downloader.main"]