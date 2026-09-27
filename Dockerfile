FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY vinted_tracker ./vinted_tracker
RUN pip install --no-cache-dir . && python -m playwright install --with-deps chromium
COPY config.yaml ./
CMD ["python", "-m", "vinted_tracker", "run"]
