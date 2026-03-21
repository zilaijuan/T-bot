# Telegram File Code Bot

一个最小可运行的 Telegram 机器人：

- 用户发送 `图片`、`视频`、`文件`
- 机器人生成一个随机取件码并返回
- 任何人把这个取件码发给机器人，机器人都会把原文件重新发回去

## 功能说明

- 支持 `photo`、`video`、`document`
- 使用 Telegram 的 `file_id` 复用文件，不把文件下载到本地
- 使用 SQLite 保存 `取件码 -> 文件信息` 映射
- 支持普通文本取件，也支持 `https://t.me/<bot_username>?start=<code>` 深链取件

## 目录

```text
.
├─ app.py
├─ requirements.txt
├─ .env.example
└─ telegram_file_code_bot
   ├─ __init__.py
   ├─ config.py
   ├─ database.py
   └─ main.py
```

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env`，然后填写：

```env
BOT_TOKEN=你的 Telegram Bot Token
DATABASE_PATH=data/bot.db
CODE_LENGTH=8
```

## 运行

```bash
python app.py
```

## 使用方式

1. 给机器人发送一张图片、一个视频或一个文件
2. 机器人返回一串随机码，例如 `8G4KQ2RM`
3. 任何用户把这串码发给机器人，机器人就会把文件重新发回去

也可以直接分享深链：

```text
https://t.me/你的机器人用户名?start=8G4KQ2RM
```

## 当前限制

- 一条消息只处理一个媒体对象
- 目前不处理相册媒体组
- 文件永久有效，未做过期删除
- 未加频率限制和管理后台

如果你后面要加：

- 取件码过期
- 一码多文件
- 管理员统计
- MongoDB / PostgreSQL
- Web 上传页

这个项目结构可以继续扩展。
