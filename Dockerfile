FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY telegram_file_code_bot /app/telegram_file_code_bot
COPY tg_msg_collector /app/tg_msg_collector

RUN mkdir -p /app/data/uploads

CMD ["python", "app.py"]
