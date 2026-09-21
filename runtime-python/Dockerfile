# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-openjiuwen-deps.txt requirements-openjiuwen-sdk.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-openjiuwen-deps.txt \
    && pip install --no-cache-dir --no-deps -r requirements-openjiuwen-sdk.txt
COPY app ./app
EXPOSE 9572
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9572"]
