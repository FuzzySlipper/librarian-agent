FROM node:22-slim AS frontend
WORKDIR /frontend
COPY dev/frontend/package.json dev/frontend/package-lock.json ./
RUN npm ci
COPY dev/frontend/ .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

# Install dependencies first for layer caching
COPY dev/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/
COPY dev/config.yaml.default build/config.yaml
COPY dev/defaults/ dev/defaults/

# Copy built frontend
COPY --from=frontend /frontend/dist static/

# Run setup to populate build/ with defaults
COPY dev/setup.sh dev/setup.sh
COPY dev/VERSION dev/VERSION
RUN bash dev/setup.sh

EXPOSE 8005

ENV CONFIG_PATH=/app/build/config.yaml
ENV DOTENV_PATH=/app/build/.env

CMD ["python", "-m", "uvicorn", "src.web.server:app", "--host", "0.0.0.0", "--port", "8005"]
