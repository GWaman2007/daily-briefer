FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Install the package
RUN pip install -e .

# Create data directory
RUN mkdir -p /app/data

# Set environment variables
ENV DB_PATH=/app/data/daily_briefer.db

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "from daily_briefer.config import load_config; c = load_config(); print('OK')" || exit 1

# Run the agent
CMD ["daily-briefer", "poll"]
