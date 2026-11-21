ARG BUILD_FROM=docker.io/library/python:3.12-alpine3.20
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    INGRESS_PORT=8099 \
    LOCAL_UTC_OFFSET=7

WORKDIR /app
COPY app/ /app/

EXPOSE 8099
CMD ["python3", "-u", "/app/server.py"]
