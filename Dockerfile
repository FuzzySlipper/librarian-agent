FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/
COPY config.yaml .
COPY persona/ persona/
COPY writing-styles/ writing-styles/

# Copy built frontend
COPY --from=frontend /frontend/dist static/

EXPOSE 8005

CMD ["python", "-m", "uvicorn", "src.web.server:app", "--host", "0.0.0.0", "--port", "8005"]
