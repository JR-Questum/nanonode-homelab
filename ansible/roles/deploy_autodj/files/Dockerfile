# Managed by Ansible - deploy_autodj.
FROM python:3.13-slim

# websockets is the only dependency: the stdlib has no WebSocket client
# and go-librespot's event feed is the AutoDJ's clock.
RUN pip install --no-cache-dir websockets==15.0.1

WORKDIR /app
COPY autodj.py /app/autodj.py

# -u so logs appear immediately rather than when the buffer flushes.
ENTRYPOINT ["python3", "-u", "/app/autodj.py"]