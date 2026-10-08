FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace
WORKDIR /workspace
COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock
COPY backend /workspace/backend
COPY database /workspace/database
COPY ai /workspace/ai
COPY tests /workspace/tests
RUN useradd --create-home --uid 10001 pamati
USER pamati
WORKDIR /workspace/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
