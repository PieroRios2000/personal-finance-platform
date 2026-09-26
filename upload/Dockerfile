# Upload portal (T44, ADR 0040). Built from the repository root (compose `context: ..`)
# because it reuses two files: ingestion/unlock.py (unlocking a PDF; pure pikepdf) and
# dex-register/api.proto (Dex's gRPC API, compiled to a client here, never committed).
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir flask==3.1.2 gunicorn==23.0.0 authlib==1.8.0 requests==2.32.5 \
    pikepdf==10.13.0.post1 grpcio==1.84.0 grpcio-tools==1.84.0 protobuf==7.36.2
COPY dex-register/api.proto ./
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. api.proto
COPY ingestion/unlock.py ingestion/submissions.py ingestion/__init__.py ./ingestion/
# The alerting's email channel (Phase 7, stdlib only): the same ALERT_* variables.
COPY alerting/__init__.py alerting/channels.py ./alerting/
COPY upload/portal.py upload/server.py ./
USER nobody
EXPOSE 5560
# Behind Cloudflare/cloudflared: trust X-Forwarded-Proto so the OAuth callback is https.
CMD ["gunicorn", "--bind", "0.0.0.0:5560", "--workers", "2", "--forwarded-allow-ips", "*", "server:app"]
