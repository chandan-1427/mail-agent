# Use Python 3.12-slim to match your pyproject.toml
FROM python:3.12-slim

# Install uv directly
RUN pip install --no-cache-dir uv

# Set the working directory inside the container
WORKDIR /app

# Copy your pyproject.toml and application code
COPY . .

# Use uv to install the dependencies (creates a managed virtual environment)
RUN uv sync

# Expose the port the app runs on
EXPOSE 8000

# Run the script exactly as you do locally
CMD ["uv", "run", "python", "-m", "main"]