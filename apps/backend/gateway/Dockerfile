FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/packages/shared/python

WORKDIR /app

COPY apps/backend/gateway/requirements.runtime.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY apps/backend/gateway /app/apps/backend/gateway
COPY packages/shared/python /app/packages/shared/python

WORKDIR /app/apps/backend/gateway

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
