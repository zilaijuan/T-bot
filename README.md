# Telegram Bots

这个项目现在通过根目录 [app.py](app.py) 同时启动多个 Telegram bot 和后台 agent：

- `telegram_file_code_bot`：基于取件码的内容暂存与取回机器人
- `tg_msg_collector_bot`：群组消息采集与检索机器人
- `code_collector_bot`：Workflow Entry Bot，接收用户消息并写入任务表
- `backup_bot`：定时把本地 SQLite/其他文件备份到 Telegram 群组
- `code_router_agent`：后台领取并执行 `workflow_tasks` 的 Router/Worker Agent

`telegram_file_code_bot` 的详细设计见 [telegram_file_code_bot/DESIGN.md](telegram_file_code_bot/DESIGN.md)。

## 启动方式

根目录 `app.py` 是统一入口：

```bash
python app.py
```

它会按配置构建多个独立的 `python-telegram-bot` Application，并在同一个进程里启动多个 polling bot。

## 环境变量

创建 `.env`：

```env
# shared Telegram proxy. Leave empty to connect directly.
TELEGRAM_PROXY_URL=

# telegram_file_code_bot
TELEGRAM_FILE_CODE_BOT_ENABLED=true
TELEGRAM_FILE_CODE_BOT_TOKEN=123456:replace-with-your-file-code-bot-token
TELEGRAM_FILE_CODE_BOT_PROXY_URL=
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

# tg_msg_collector_bot
TG_MSG_COLLECTOR_BOT_ENABLED=true
TG_MSG_COLLECTOR_BOT_TOKEN=123456:replace-with-your-message-collector-bot-token
TG_MSG_COLLECTOR_BOT_ALLOWED_GROUP_IDS=-1001234567890,-1009876543210
TG_MSG_COLLECTOR_BOT_DATABASE_PATH=
TG_MSG_COLLECTOR_BOT_DATA_DIR=data
TG_MSG_COLLECTOR_BOT_LOG_PATH=data/tg_msg_collector_bot.log
TG_MSG_COLLECTOR_BOT_PROXY_URL=

# code_collector_bot
CODE_COLLECTOR_BOT_ENABLED=false
CODE_COLLECTOR_BOT_TOKEN=123456:replace-with-your-workflow-entry-bot-token
CODE_COLLECTOR_BOT_PROXY_URL=
CODE_COLLECTOR_BOT_DEFAULT_WORKER=pending
CODE_COLLECTOR_BOT_ADMIN_USER_IDS=
CODE_COLLECTOR_BOT_ALLOW_PUBLIC_SUBMIT=true

# code_router_agent
CODE_ROUTER_AGENT_ENABLED=false
CODE_ROUTER_AGENT_POLL_INTERVAL_SECONDS=2
CODE_ROUTER_AGENT_IDLE_SLEEP_SECONDS=5

# QQ coder driver
QQ_CODER_DRIVER_TARGET_BOT=
QQ_CODER_DRIVER_DRY_RUN=true
TELETHON_API_ID=
TELETHON_API_HASH=
TELETHON_SESSION=data/telethon_user.session
TELETHON_PROXY_URL=
TELETHON_TIMEOUT_SECONDS=30

# zyxfids driver
ZYXFIDS_DRIVER_TARGET_BOT=@zyxfids_bot
ZYXFIDS_DRIVER_DRY_RUN=true

# amumu jiema driver
AMUMU_JIEMA_DRIVER_TARGET_BOT=@amumujiemabot
AMUMU_JIEMA_DRIVER_DRY_RUN=true


# message_dispatch_bot
MESSAGE_DISPATCH_BOT_ENABLED=false
MESSAGE_DISPATCH_BOT_TOKEN=123456:replace-with-your-message-dispatch-bot-token
MESSAGE_DISPATCH_BOT_PROXY_URL=
MESSAGE_DISPATCH_INTERVAL_SECONDS=300
MESSAGE_DISPATCH_MAX_TASKS_PER_RUN=20
MESSAGE_DISPATCH_ADMIN_USER_IDS=

# backup_bot
BACKUP_BOT_ENABLED=false
BACKUP_BOT_TOKEN=123456:replace-with-your-backup-bot-token
BACKUP_BOT_PROXY_URL=
BACKUP_CHAT_ID=-1001234567890
BACKUP_INTERVAL_SECONDS=3600
BACKUP_PATHS=data/bots.db
BACKUP_STATE_PATH=data/backup_state.json
BACKUP_DELETE_OLD=true
BACKUP_CAPTION_PREFIX=SQLite backup
BACKUP_ADMIN_USER_IDS=
```

说明：

- 各 Telegram bot 必须使用不同 token。
- `TELEGRAM_FILE_CODE_BOT_ENABLED=false` 时不会启动取件码 bot，默认启用。
- `TELEGRAM_FILE_CODE_BOT_TOKEN` 是取件码 bot 的 token。
- `TG_MSG_COLLECTOR_BOT_ENABLED=false` 时不会启动消息采集 bot，默认启用。
- `TG_MSG_COLLECTOR_BOT_TOKEN` 是消息采集 bot 的 token。
- `CODE_COLLECTOR_BOT_ENABLED=true` 时会启动 Workflow Entry Bot。
- `CODE_COLLECTOR_BOT_TOKEN` 是 Entry Bot 的 token。
- `CODE_COLLECTOR_BOT_DEFAULT_WORKER` 是 Entry Bot 写入任务时使用的初始占位值；Router Agent 会根据 driver 规则重新判断并回写真实 driver 名称。
- `CODE_COLLECTOR_BOT_ALLOW_PUBLIC_SUBMIT=false` 时，只有 `CODE_COLLECTOR_BOT_ADMIN_USER_IDS` 可以提交任务。
- `BACKUP_BOT_ENABLED=true` 时会启动备份 bot。
- `BACKUP_BOT_TOKEN` 是备份 bot 的 token。
- `BACKUP_CHAT_ID` 是接收备份文件的群组 ID。
- `BACKUP_PATHS` 是要备份的文件列表，多个文件用英文逗号分隔。
- `BACKUP_STATE_PATH` 用来记录每个文件上一次发送的 hash 和 Telegram message_id。
- `BACKUP_DELETE_OLD=true` 时，文件变化并发送新版前，会尝试删除该文件上一条备份消息。
- `BACKUP_ADMIN_USER_IDS` 配置后，只有这些用户可以使用 `/status` 和 `/backup_now`；留空则不限制。
- 相关 bot 和 agent 默认共用 `DATABASE_URL` 指向的 SQLite 文件。
- `TG_MSG_COLLECTOR_BOT_DATABASE_PATH` 留空时，采集 bot 会使用 `DATABASE_URL` 中的 SQLite 文件；只有需要单独数据库时才填写。
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

## tg_msg_collector_bot

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

## code_collector_bot

功能：

- 作为 Telegram Workflow Execution Engine 的 Entry Bot
- 接收用户文字、图片、视频、文件、音频等消息
- 将消息写入共享 SQLite 的 `workflow_tasks` 表
- 新任务默认状态为 `NEW`
- 写入 `target_worker`、`state_payload`、`next_run_at` 等调度字段
- 不直接执行第三方 Bot，只负责任务化


命令：

```text
/start
/stats
```

核心表：

```text
workflow_tasks
```

关键字段：

```text
task_id
user_id
message_content
status
target_worker
code
state_payload
next_run_at
created_at
updated_at
```

## code_router_agent

功能：

- 作为 Telegram Workflow Execution Engine 的后台 Router/Worker Agent
- 复用 `workflow_tasks` 表，从 `NEW`、`WAIT`、`RETRY` 状态中领取到期任务
- 从已启用 driver 中逐个执行 `matches()` 规则，命中后提取 matched code；如果已有相同 `code` 的 `DONE` 任务，则把当前任务标记为 `DUPLICATE` 并跳过发送，否则执行该 driver 的一个 step
- 根据 `ExecutionResult` 更新 `status`、`target_worker`、`code`、`state_payload` 和 `next_run_at`
- Agent 启动时会尝试给旧任务回填 `code`，让历史 `DONE` 任务也能参与重复判断
- Agent 本身不接收 Telegram 消息，也不是 Telegram Bot

配置：

```env
CODE_ROUTER_AGENT_ENABLED=true
CODE_ROUTER_AGENT_POLL_INTERVAL_SECONDS=2
CODE_ROUTER_AGENT_IDLE_SLEEP_SECONDS=5
CODE_ROUTER_AGENT_CHANNEL_LISTENER_ENABLED=false
CODE_ROUTER_AGENT_CHANNEL_LISTENER_CHANNEL=-1003948153894
CODE_ROUTER_AGENT_CHANNEL_LISTENER_TELETHON_SESSION=data/telethon_user_channel_listener.session
```

说明：

- Router Agent 启动时会自动加载 registry 中 `auto_register = True` 的 driver，并遍历这些 driver 的规则来判断任务归属。
- 当前已内置 `qq_coder`、`zyxfids`、`amumu_jiema` 和 `wenjianji` driver。`default` / `noop` 仅用于调试骨架，不会主动匹配任务；没有任何 driver 命中时任务会标记为 `FAILED`。
- 后续接入真实第三方 Telegram Bot 时，在 `code_router_agent/drivers` 里新增 driver，实现 `matches()` 和 `step()`，在 registry 中注册 driver 名称，并通过 driver 类上的 `auto_register` 硬编码开关控制是否自动启用。




Channel 监听任务：

- `CODE_ROUTER_AGENT_CHANNEL_LISTENER_ENABLED=true` 时，`code_router_agent` 会额外启动一个 Telethon 监听任务。
- `CODE_ROUTER_AGENT_CHANNEL_LISTENER_CHANNEL` 是要监听的 channel 用户名或 id，默认 `a260621`。
- 收到的新消息会保存到 SQLite 新表 `channel_messages`。
- `channel_messages` 使用 `(channel_id, message_id)` 唯一约束，重启或重复事件不会重复写入。

`channel_messages` 核心字段：

```text
id
channel_id
channel_username
message_id
sender_id
message_date
text
raw_message_json
created_at
```

### QQ coder driver

用途：

- Driver 名称：`qq_coder`
- 匹配消息中的 QQ coder 代码，例如 `QQn8zw_bot:qqcode12936a8660_79V`
- 一条消息里有多个代码时，会去重后逐条处理
- `QQ_CODER_DRIVER_DRY_RUN=true` 时只记录匹配结果，不真实发送
- `QQ_CODER_DRIVER_DRY_RUN=false` 时使用 Telethon 用户账号把原始消息文本发送给 `QQ_CODER_DRIVER_TARGET_BOT`

配置示例：

```env
CODE_COLLECTOR_BOT_DEFAULT_WORKER=pending
CODE_ROUTER_AGENT_ENABLED=true

QQ_CODER_DRIVER_TARGET_BOT=target_bot_username
QQ_CODER_DRIVER_DRY_RUN=true
TELETHON_API_ID=
TELETHON_API_HASH=
TELETHON_SESSION=data/telethon_user.session
TELETHON_PROXY_URL=
TELETHON_TIMEOUT_SECONDS=30
```

真实发送前需要先完成 Telethon session 登录；未登录时 driver 会把任务转为 `RETRY`，并在 `state_payload.last_execution.result.error` 里记录原因。

Telethon 代理：`TELETHON_PROXY_URL` 会覆盖全局 `TELEGRAM_PROXY_URL`；如果留空，则复用 `TELEGRAM_PROXY_URL`，最后兼容 `PROXY_URL`。支持 `socks5://127.0.0.1:1080`、`socks5h://127.0.0.1:1080`、`socks4://...` 和 `http://127.0.0.1:7890`。`TELETHON_TIMEOUT_SECONDS` 控制真实发送时的连接和发送超时，默认 30 秒。


### zyxfids driver

用途：

- Driver 名称：`zyxfids`
- 匹配 40 位 hex 代码，例如 `d6a9d8f8edd6dd915e8df42f5526e5b0885ebaba`
- 匹配 32 到 96 位字母数字 token，例如 `YzWTAnBkqUZhnbZEvpvt34eT3kCN1IOCUTqoMql9`
- 文本中包含 `zyxfids_bot` 时也会匹配；如果没有单独代码，会把整段文本发送给目标 bot
- `ZYXFIDS_DRIVER_DRY_RUN=true` 时只记录匹配结果，不真实发送
- `ZYXFIDS_DRIVER_DRY_RUN=false` 时使用 Telethon 用户账号把原始消息文本发送给 `ZYXFIDS_DRIVER_TARGET_BOT`

配置示例：

```env
ZYXFIDS_DRIVER_TARGET_BOT=@zyxfids_bot
ZYXFIDS_DRIVER_DRY_RUN=true
```


### amumu jiema driver

用途：

- Driver 名称：`amumu_jiema`
- 匹配 `amumujiemabot_` 开头、后面跟字母数字的代码，例如 `amumujiemabot_i9med9nbz4`
- 一条消息里有多个代码时，会去重后逐条处理
- `AMUMU_JIEMA_DRIVER_DRY_RUN=true` 时只记录匹配结果，不真实发送
- `AMUMU_JIEMA_DRIVER_DRY_RUN=false` 时使用 Telethon 用户账号把原始消息文本发送给 `AMUMU_JIEMA_DRIVER_TARGET_BOT`

配置示例：

```env
AMUMU_JIEMA_DRIVER_TARGET_BOT=@amumujiemabot
AMUMU_JIEMA_DRIVER_DRY_RUN=true
```

### WenJianJi driver

用途：

- Driver 名称：`wenjianji`
- 匹配 `wenjianjibot_` 开头、后面跟字母数字或下划线的代码，例如 `wenjianjibot_4v_50p_1d_6kcRYUDTG8VH11Xp`
- `WENJIANJI_DRIVER_DRY_RUN=true` 时只记录匹配结果，不真实发送
- `WENJIANJI_DRIVER_DRY_RUN=false` 时使用 Telethon 用户账号把原始消息文本发送给 `WENJIANJI_DRIVER_TARGET_BOT`
- 发送后会读取 bot 返回的分页消息，自动点击包含 `获取下一组` 的按钮，直到到达最后一组、按钮消失、等待超时或达到最大页数；如果等待超时或达到最大页数，会记录 `stop_reason` 并让任务进入 `RETRY`，不会误标记为 `DONE`

配置示例：

```env
WENJIANJI_DRIVER_TARGET_BOT=@WenJianJibot
WENJIANJI_DRIVER_DRY_RUN=true
WENJIANJI_DRIVER_PAGE_WAIT_SECONDS=60
WENJIANJI_DRIVER_POLL_INTERVAL_SECONDS=2
WENJIANJI_DRIVER_MAX_PAGES=50
```

## message_dispatch_bot

???

- ???? `/start` ???? `message_dispatch_subscribers`???? `ACTIVE`?
- ???? `/stop` ? `/unsubscribe` ????? `INACTIVE`?
- ?? `MESSAGE_DISPATCH_INTERVAL_SECONDS` ??? `driver_output_tasks` ???? `NEW` ????
- ?? `task_id` ?? `workflow_tasks.message_content` ? `driver_output_messages.content`?
- ???? `ACTIVE` ??????????????? driver ?????
- ?????? `driver_output_tasks.status` ?? `DONE`?????????? `NEW`?
- ?????? bot?????????? `BLOCKED`?

???

```env
MESSAGE_DISPATCH_BOT_ENABLED=true
MESSAGE_DISPATCH_BOT_TOKEN=123456:replace-with-your-message-dispatch-bot-token
MESSAGE_DISPATCH_INTERVAL_SECONDS=300
MESSAGE_DISPATCH_MAX_TASKS_PER_RUN=20
MESSAGE_DISPATCH_ADMIN_USER_IDS=
```

?????

```text
/start
/stop
/unsubscribe
/status
```

????

```text
message_dispatch_subscribers
driver_output_tasks
driver_output_messages
workflow_tasks
```

## backup_bot

功能：

- 定时检查一个或多个本地文件
- 计算 SHA256，只有文件内容变化时才发送
- 每个文件独立记录上一次的 `message_id` 和 hash
- 发送新版本前尝试删除该文件对应的旧备份消息
- 不依赖群组里的最后一条消息

常用配置：

```env
BACKUP_BOT_ENABLED=true
BACKUP_BOT_TOKEN=123456:replace-with-your-backup-bot-token
BACKUP_BOT_PROXY_URL=
BACKUP_CHAT_ID=-1001234567890
BACKUP_INTERVAL_SECONDS=3600
BACKUP_PATHS=data/bots.db
BACKUP_STATE_PATH=data/backup_state.json
BACKUP_DELETE_OLD=true
```

备份多个文件：

```env
BACKUP_PATHS=data/bots.db,data/bots.db-wal,data/bots.db-shm
```

命令：

```text
/start
/status
/backup_now
```

注意：

- 备份 bot 需要被加入 `BACKUP_CHAT_ID` 对应的群组。
- 如果要删除旧备份消息，备份 bot 需要有删除消息权限。
- Telegram 对删除消息有时间限制，旧消息过久可能删除失败；删除失败不会阻止新备份发送。

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

## Proxy

如果 Telegram 连接超时，可以在 `.env` 里配置代理：

```env
TELEGRAM_PROXY_URL=http://127.0.0.1:7890
```

也可以给单个 bot 单独配置代理，单 bot 配置会覆盖全局配置：

```env
TELEGRAM_FILE_CODE_BOT_PROXY_URL=http://127.0.0.1:7890
TG_MSG_COLLECTOR_BOT_PROXY_URL=http://127.0.0.1:7890
CODE_COLLECTOR_BOT_PROXY_URL=http://127.0.0.1:7890
BACKUP_BOT_PROXY_URL=http://127.0.0.1:7890
```

Bot API 代理优先级是：`*_PROXY_URL` > `TELEGRAM_PROXY_URL` > 兼容旧配置 `PROXY_URL`。HTTP 和 SOCKS 地址都可以按 `python-telegram-bot` 支持的格式填写，例如 `http://127.0.0.1:7890` 或 `socks5://127.0.0.1:1080`。Telethon 用户账号代理优先级是：`TELETHON_PROXY_URL` > `TELEGRAM_PROXY_URL` > `PROXY_URL`。
