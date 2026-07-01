FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY backup_bot /app/backup_bot
COPY code_collector_bot /app/code_collector_bot
COPY code_router_agent /app/code_router_agent
COPY message_dispatch_bot /app/message_dispatch_bot
COPY telegram_file_code_bot /app/telegram_file_code_bot
COPY tg_msg_collector_bot /app/tg_msg_collector_bot

RUN mkdir -p /app/data/uploads

CMD ["python", "app.py"]


