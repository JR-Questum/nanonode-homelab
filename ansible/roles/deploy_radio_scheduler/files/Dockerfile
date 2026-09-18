# Managed by Ansible - deploy_radio_scheduler.
FROM python:3.13-slim

RUN pip install --no-cache-dir piper-tts

WORKDIR /app
COPY scheduler.py /app/scheduler.py

ENTRYPOINT ["python3", "-u", "/app/scheduler.py"]