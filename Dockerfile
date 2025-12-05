FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files needed for dependency installation including README.md
COPY pyproject.toml uv.lock README.md ./

RUN uv sync --no-dev

# Activate the virtual environment for subsequent commands
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy remaining files
COPY . .

# Command to run when container starts
CMD ["python", "-m", "stock_data_downloader.run_server", "--config", "/app/config.yaml"]