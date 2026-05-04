# Telegram Bots

这个项目现在通过根目录 [app.py](app.py) 同时启动两个 Telegram bot：

- `telegram_file_code_bot`：基于取件码的内容暂存与取回机器人
- `tg_msg_collector`：群组消息采集与检索机器人

`telegram_file_code_bot` 的详细设计见 [telegram_file_code_bot/DESIGN.md](telegram_file_code_bot/DESIGN.md)。

## 启动方式

根目录 `app.py` 是统一入口：

```bash
python app.py
```

它会构建两个独立的 `python-telegram-bot` Application，并在同一个进程里启动两个 polling bot。

## 环境变量

创建 `.env`：

```env
# telegram_file_code_bot
TELEGRAM_FILE_CODE_BOT_TOKEN=123456:replace-with-your-file-code-bot-token
DATABASE_URL=sqlite:///data/bots.db

DEFAULT_EXPIRY=7d
CODE_RANDOM_LENGTH=8

MAX_ITEMS_PER_BUNDLE=
MAX_CODE_SUMMARY_LENGTH=
PAGINATED_REDEEM_ENABLED=false
REDEEM_PAGE_SIZE=10
CODE_LIST_DESCRIPTION_LENGTH=10

UPLOAD_MODE=telegram_file_id
UPLOAD_DIR=data/uploads

ADMIN_USER_IDS=123456789,987654321
ALLOW_PUBLIC_UPLOAD=true
ALLOW_PUBLIC_REDEEM=true

WEB_ENABLED=false
PUBLIC_BASE_URL=

# tg_msg_collector
TG_MSG_COLLECTOR_BOT_TOKEN=123456:replace-with-your-message-collector-bot-token
TG_MSG_COLLECTOR_ALLOWED_GROUP_IDS=-1001234567890,-1009876543210
TG_MSG_COLLECTOR_DATABASE_PATH=
TG_MSG_COLLECTOR_DATA_DIR=data
TG_MSG_COLLECTOR_LOG_PATH=data/tg_msg_collector.log
TG_MSG_COLLECTOR_PROXY_URL=
```

说明：

- 两个 bot 必须使用不同 token。
- `TELEGRAM_FILE_CODE_BOT_TOKEN` 是取件码 bot 的 token。
- `TG_MSG_COLLECTOR_BOT_TOKEN` 是消息采集 bot 的 token。
- 两个 bot 默认共用 `DATABASE_URL` 指向的 SQLite 文件。
- `TG_MSG_COLLECTOR_DATABASE_PATH` 留空时，采集 bot 会使用 `DATABASE_URL` 中的 SQLite 文件；只有需要单独数据库时才填写。
- `MAX_ITEMS_PER_BUNDLE` 和 `MAX_CODE_SUMMARY_LENGTH` 不配置、为空、`0` 或负数时都表示不限制。
- `PAGINATED_REDEEM_ENABLED` 控制取回内容时是否分页批量发送，默认关闭。
- `REDEEM_PAGE_SIZE` 是分页取回时每页发送多少条内容，默认 `10`。
- `CODE_LIST_DESCRIPTION_LENGTH` 是管理员取件码列表里的描述摘要长度，默认 `10` 个字符。
- `DEFAULT_EXPIRY` 是取件码默认有效期，支持 `30m`、`12h`、`7d`、`4w`、`forever`。
- `UPLOAD_MODE` 是取件码 bot 的内容存储模式。当前已实现的值只有 `telegram_file_id`。

分页取回配置：

```env
PAGINATED_REDEEM_ENABLED=true
REDEEM_PAGE_SIZE=10
```

打开后，如果某个取件码包含的内容数量超过 `REDEEM_PAGE_SIZE`，机器人会先发送第一页内容，再发送带按钮的分页导航。导航包含“上一页”“下一页”和当前页附近的页码，点击后发送对应页内容。

关闭时：

```env
PAGINATED_REDEEM_ENABLED=false
```

机器人保持原行为，一次性发送取件码对应的全部内容。

`UPLOAD_MODE` 可配置项：

```text
telegram_file_id  保存 Telegram file_id，取回时直接让 Telegram 重新发送文件。当前唯一已实现模式。
local             预留值，计划用于把文件下载到本地 UPLOAD_DIR 后再发送。当前未实现。
s3                预留值，计划用于对象存储。当前未实现。
```

当前版本请保持：

```env
UPLOAD_MODE=telegram_file_id
```

`DEFAULT_EXPIRY` 格式：

```text
m = 分钟
h = 小时
d = 天
w = 周
forever = 永久有效
```

示例：

```env
DEFAULT_EXPIRY=30m
DEFAULT_EXPIRY=12h
DEFAULT_EXPIRY=7d
DEFAULT_EXPIRY=4w
DEFAULT_EXPIRY=forever
```

## telegram_file_code_bot

功能：

- 自动草稿：直接发送文字、图片、视频或文件即可开始
- `/desc` 设置 Bundle 描述
- `/done` 生成取件码
- 取件码包含内容摘要，例如 `P3V1F2-K7M9Q2RA`
- 摘要数量显示真实值，不压缩、不截断
- 取回时会尽量使用 Telegram 媒体组发送连续的图片/视频、文件或音频
- SQLite 存储
- Telegram `file_id` 存储
- 管理员统计、查询、删除

常用命令：

```text
/start
/help
/new [expiry]
/desc 描述文字
/done
/cancel
/stats
/info CODE
/delete CODE
/setdesc CODE 描述文字
/recent [数量]
/codes [页码]
```

## tg_msg_collector

功能：

- 保存白名单群组中的文字和多媒体消息
- 列出最近保存内容
- 按关键词搜索
- 按 ID 回显单条消息
- 按 ID 回显相册/媒体组

常用命令：

```text
/start
/list [page]
/search 关键词 [page]
/get ID
/msg_group ID
```

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Docker

```bash
docker compose up -d --build
docker compose logs -f
docker compose down
```
