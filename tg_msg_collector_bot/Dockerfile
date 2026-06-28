FROM python:3.11-alpine

WORKDIR /app

# 安装时区数据支持，确保日志时间准确
RUN apk add --no-cache tzdata

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# 创建数据库存储目录
RUN mkdir -p /app/data

# 默认时区设置为上海
ENV TZ=Asia/Shanghai

CMD ["python", "main.py"]