# Self-service Dex registration (T40, ADR 0035): a tiny stdlib HTTP server plus a
# generated gRPC client for Dex's own CreatePassword API. api_pb2*.py are generated
# here, from the vendored api.proto, never committed (they are Dex's own wire format,
# not this project's code).
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir grpcio==1.84.0 grpcio-tools==1.84.0 protobuf==7.36.2 bcrypt==5.0.0
COPY api.proto registration.py app.py ./
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. api.proto
USER nobody
EXPOSE 5559
CMD ["python", "app.py"]
