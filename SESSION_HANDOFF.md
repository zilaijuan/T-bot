# T-bot Session Handoff

本文档记录当前会话的关键上下文，方便后续在新会话里继续开发。本文不记录真实 bot token、api hash、手机号等敏感信息。

## 工作目录

- 项目根目录：`D:\project\python\T-bot`
- 当前重点开发目录：
  - `code_collector_bot`
  - `code_router_agent`
  - `backup_bot`
  - `telegram_file_code_bot`
  - `tg_msg_collector_bot`
- 用户要求：后续文件操作使用 UTF-8 编码。

## 运行环境

- Windows PowerShell。
- 普通 `python.exe` 在本机可能不可用；当前可用的是 conda 环境：
  - `D:\developer\anaconda3\envs\proxy\python.exe`
- 常用验证命令：

```powershell
D:\developer\anaconda3\envs\proxy\python.exe -m compileall code_router_agent
```

如果只想避免生成 `__pycache__`，可以用内联 `compile()` 或设置：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
```

## 总体架构

根目录 `app.py` 负责按开关启动多个 bot / agent。各模块通过 `.env` 配置启停。

当前主要组件：

- `telegram_file_code_bot`：取件码机器人，负责把文字、图片、视频、文件等内容打包成取件码，并支持后续取回。
- `tg_msg_collector_bot`：群组消息采集机器人。
- `backup_bot`：定时备份本地文件到 Telegram 群组或 channel。
- `code_collector_bot`：Workflow Entry Bot，接收用户提交的消息并写入任务表。
- `code_router_agent`：后台 agent，从任务表领取任务，用 driver 规则判断任务类型，并把消息发送给对应第三方 bot。

## 数据库

- 当前使用 SQLite。
- `.env` 中通过 `DATABASE_URL` 配置，例如：

```env
DATABASE_URL=sqlite:///data/bot.db
```

- `code_collector_bot` 和 `code_router_agent` 复用同一个 SQLite 文件。
- Workflow 任务表：`workflow_tasks`。
- 由于 SQLite WAL 模式，实际运行时可能同时出现：
  - `data/bot.db`
  - `data/bot.db-wal`
  - `data/bot.db-shm`
- 如果只复制 `bot.db`，可能看不到 WAL 中尚未 checkpoint 的最新表结构或数据；需要一起复制 `-wal` 和 `-shm`，或先触发 checkpoint。

## code_collector_bot

用途：作为 workflow entry bot。

行为：

- 用户向 entry bot 发送文本、图片、视频、文件等消息。
- bot 将消息写入 `workflow_tasks`。
- 新任务初始状态为 `NEW`。
- `target_worker` 只是初始占位值，默认可配置为 `pending`。
- 真正使用哪个 driver，不依赖数据库里的 `target_worker` 初始值，而是由 `code_router_agent` 遍历所有自动注册 driver 的 `matches()` 规则决定。

关键配置：

```env
CODE_COLLECTOR_BOT_ENABLED=true
CODE_COLLECTOR_BOT_TOKEN=
CODE_COLLECTOR_BOT_DEFAULT_WORKER=pending
CODE_COLLECTOR_BOT_ADMIN_USER_IDS=
CODE_COLLECTOR_BOT_ALLOW_PUBLIC_SUBMIT=true
CODE_COLLECTOR_BOT_PROXY_URL=
```

## code_router_agent

用途：后台领取并执行 workflow task。

行为：

- 从 `workflow_tasks` 领取到期任务。
- 支持状态大致包括 `NEW`、`WAIT`、`RETRY` 等。
- 启动时通过 registry 自动加载 `auto_register = True` 的 driver。
- 对每个任务，按 driver 顺序调用 `matches(task, settings)`。
- 第一个命中的 driver 会先提取 matched code；如果已有相同 `code` 的 `DONE` 任务，当前任务会标记为 `DUPLICATE` 并跳过发送，否则执行 `step(task, settings)`。
- 执行后更新任务状态、真实 `target_worker`、`code`、`state_payload`、`next_run_at` 等。
- Agent 启动时会尝试给旧任务回填 `code`，让历史 `DONE` 任务也能参与重复判断。
- 如果没有 driver 命中，任务会标记为 `FAILED`，`target_worker` 为 `unmatched`。

关键配置：

```env
CODE_ROUTER_AGENT_ENABLED=true
CODE_ROUTER_AGENT_POLL_INTERVAL_SECONDS=2
CODE_ROUTER_AGENT_IDLE_SLEEP_SECONDS=5
```

注意：

- 已废弃 `CODE_ROUTER_AGENT_DRIVERS` 这类手动 driver 列表配置。
- 新增 driver 时，在 driver 类上用硬编码 `auto_register = True/False` 控制是否自动注册。
- 需要在 `code_router_agent/drivers/registry.py` 注册 driver factory。

## Telethon 用户账号发送

某些 driver 需要用 Telegram 用户账号向第三方 bot 发送消息，因此使用 Telethon。

关键配置：

```env
TELETHON_API_ID=
TELETHON_API_HASH=
TELETHON_SESSION=data/telethon_user.session
TELETHON_PROXY_URL=
TELETHON_TIMEOUT_SECONDS=30
```

代理优先级：

1. `TELETHON_PROXY_URL`
2. `TELEGRAM_PROXY_URL`
3. `PROXY_URL`

依赖：

```text
telethon>=1.36,<2
PySocks>=1.7,<2
python-socks[asyncio]>=2.4,<3
```

曾经遇到的问题：

- 没有安装 `python-socks[asyncio]` 时，Telethon 代理没有正常工作。
- 安装后，使用用户账号向 `@QQld90_bot` 发送消息已经验证成功。
- 该第三方 bot 回复过类似需要 VIP 的信息，这是第三方 bot 业务限制，不是本项目发送失败。

## 当前已实现的 code_router_agent drivers

Driver 文件位于：

```text
code_router_agent/drivers/
```

当前内置：

- `qq_coder`
- `zyxfids`
- `amumu_jiema`

`default` / `noop` 仅用于调试骨架，不主动匹配任务。

### wenjianji driver

文件：

```text
code_router_agent/drivers/wenjianji.py
```

匹配示例：

```text
wenjianjibot_4v_50p_1d_6kcRYUDTG8VH11Xp
wenjianjibot_5v_MVYuGKVfIAGladtZ
wenjianjibot_5v_3p_EOmybJpzCt3jOI1s
```

关键配置：

```env
WENJIANJI_DRIVER_TARGET_BOT=@WenJianJibot
WENJIANJI_DRIVER_DRY_RUN=true
WENJIANJI_DRIVER_PAGE_WAIT_SECONDS=60
WENJIANJI_DRIVER_POLL_INTERVAL_SECONDS=2
WENJIANJI_DRIVER_MAX_PAGES=50
```

真实发送时会自动点击分页消息中的 `获取下一组` 按钮，直到最后一组或达到保护上限；未等到下一页时会记录 `no_page_update_after_click` 并进入 `RETRY`。

### 所有 driver 的统一发送规则

最新约定：

- `matches()` 仍然使用各 driver 自己的解析规则判断是否命中。
- `step()` 给第三方 bot 发送消息时，不发送解析出来的码值，而是发送用户提交的原始文本：

```python
message_to_send = task.message_content.strip()
messages_to_send = (message_to_send,)
```

也就是说，如果用户发：

```text
prefix amumujiemabot_i9med9nbz4 suffix
```

第三方 bot 收到的是整段文本，而不是单独的 `amumujiemabot_i9med9nbz4`。

### qq_coder driver

文件：

```text
code_router_agent/drivers/qq_coder.py
```

匹配示例：

```text
QQn8zw_bot:qqcode12936a8660_79V
QQld90_bot:qqcode12be967910_23P_7V
```

关键配置：

```env
QQ_CODER_DRIVER_TARGET_BOT=@QQld90_bot
QQ_CODER_DRIVER_DRY_RUN=false
```

行为：

- 匹配 `QQ..._bot:qqcode...` 格式。
- 命中后真实发送时，发送原始消息文本到 `QQ_CODER_DRIVER_TARGET_BOT`。
- dry-run 时只记录结果，不真实发送。

### zyxfids driver

文件：

```text
code_router_agent/drivers/zyxfids.py
```

匹配示例：

```text
YzWTAnBkqUZhnbZEvpvt34eT3kCN1IOCUTqoMql9
d6a9d8f8edd6dd915e8df42f5526e5b0885ebaba
0fcce8cb7e03406c0df33dbdf820dc938faa48e5
zyxfids_bot
```

关键配置：

```env
ZYXFIDS_DRIVER_TARGET_BOT=@zyxfids_bot
ZYXFIDS_DRIVER_DRY_RUN=true
```

行为：

- 匹配 40 位 hex。
- 匹配 32 到 96 位字母数字 token。
- 文本中包含 `zyxfids_bot` 也会命中。
- 命中后真实发送时，发送原始消息文本到 `ZYXFIDS_DRIVER_TARGET_BOT`。

### amumu_jiema driver

文件：

```text
code_router_agent/drivers/amumu_jiema.py
```

匹配示例：

```text
amumujiemabot_i9med9nbz4
amumujiemabot_1m56uqdxhq
```

关键配置：

```env
AMUMU_JIEMA_DRIVER_TARGET_BOT=@amumujiemabot
AMUMU_JIEMA_DRIVER_DRY_RUN=true
```

行为：

- 匹配 `amumujiemabot_` 开头、后面跟字母数字的代码。
- 命中后真实发送时，发送原始消息文本到 `AMUMU_JIEMA_DRIVER_TARGET_BOT`。

## 验证片段

验证 driver 自动注册和原始文本发送行为：

```powershell
@'
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.drivers.qq_coder import QQCoderDriver
from code_router_agent.drivers.zyxfids import ZyxFidsDriver
from code_router_agent.drivers.amumu_jiema import AmumuJiemaDriver

async def main():
    settings = CodeRouterAgentSettings.from_env()
    settings = replace(settings, qq_coder_dry_run=True, zyxfids_dry_run=True, amumu_jiema_dry_run=True)
    cases = [
        (QQCoderDriver(), 'prefix QQn8zw_bot:qqcode12936a8660_79V suffix'),
        (ZyxFidsDriver(), 'prefix d6a9d8f8edd6dd915e8df42f5526e5b0885ebaba suffix'),
        (AmumuJiemaDriver(), 'prefix amumujiemabot_i9med9nbz4 suffix'),
    ]
    for driver, text in cases:
        task = SimpleNamespace(message_content=text)
        result = await driver.step(task, settings)
        print(driver.name, result.state_payload['messages_to_send'])

asyncio.run(main())
'@ | D:\developer\anaconda3\envs\proxy\python.exe -
```

预期输出中，每个 `messages_to_send` 都应包含完整原始文本。

## backup_bot

用途：定时把 SQLite 或其他文件发送到 Telegram 群组/channel。

关键配置：

```env
BACKUP_BOT_ENABLED=false
BACKUP_BOT_TOKEN=
BACKUP_CHAT_ID=
BACKUP_PATHS=data/bot.db,data/bot.db-shm,data/bot.db-wal
BACKUP_DELETE_OLD=true
BACKUP_CAPTION_PREFIX=T-bot database backup
BACKUP_ADMIN_USER_IDS=
BACKUP_BOT_PROXY_URL=
```

行为：

- 支持多个备份文件。
- 每个文件独立计算 hash。
- 只有文件发生变化时才发送。
- 记录每个文件上一条 Telegram message_id。
- 如果 `BACKUP_DELETE_OLD=true`，发送新版前会尝试删除该文件旧备份消息。
- 群组里可以有多个文件，删除逻辑不依赖“最后一条消息”，而是依赖本地状态文件记录的 message_id。
- bot 可以向 channel 发文件，但需要把 bot 加为 channel 管理员，并配置正确的 channel chat id。

## 取件码机器人关键约定

`telegram_file_code_bot` 已从 demo 重构为较完整实现。当前关键约定：

- Bundle 支持 `description`。
- 用户直接 `/desc`、直接发图片或视频时，等同于已经 `/new`。
- 取件码摘要体现内容数量，例如图片 200 个显示 `P200`，不压缩摘要里的数量。
- `MAX_ITEMS_PER_BUNDLE` 和 `MAX_CODE_SUMMARY_LENGTH` 是配置项；不配置时不限制，或只做系统保护。
- `DEFAULT_EXPIRY` 支持类似 `7d`，也支持 `forever`。
- 过期取件码不能再使用；数据是否保留取决于清理策略，之前讨论倾向于数据仍在表里，后续可以加清理任务。
- 取件码返回时使用 Markdown/HTML code 样式，方便点击复制。
- `/recent` 返回近期取件码，列表里的取件码使用 code 样式，并显示短描述。
- 管理员 `/codes` 查询所有取件码，返回内容类似 `/recent`，分页展示，并显示不超过配置长度的描述。
- 描述长度配置默认 10。
- 用户消息里包含多个取件码时，需要逐个返回相应内容。
- 用户消息里除取件码外还包含其他文字时，也要能识别取件码。
- 可配置分页取回：打开时按页/批次发送内容，关闭时保持一次性发送。
- 给用户发送取件码对应内容时，使用媒体组发送。
- 不再发送“已加入当前内容包”这类高频提示。

## README / Docker / requirements

已经做过的相关变更：

- `requirements.txt` 加入：
  - `telethon`
  - `PySocks`
  - `python-socks[asyncio]`
- `Dockerfile` 已加入复制：
  - `code_collector_bot`
  - `code_router_agent`
  - `tg_msg_collector_bot`
- README 已加入多 bot/agent、proxy、workflow、driver 配置说明。

## 注意事项

- `.env` 是真实配置文件，包含敏感信息。不要把 token、api hash、session、手机号等写入文档或输出。
- 使用 `git status --short` 查看当前改动。
- 如果运行 Python 测试产生 `__pycache__`，完成后可以删除。
- 在 Windows 上 `apply_patch` 可能因 sandbox helper 失败；如果失败，可用 PowerShell/.NET 以 UTF-8 写入文件，但要做精确替换并及时验证。
- 新增 driver 的最小步骤：
  1. 在 `code_router_agent/drivers/` 新增 driver 文件。
  2. 实现 `name`、`auto_register`、`matches()`、`step()`。
  3. 在 `registry.py` 加入 factory。
  4. 如需配置，在 `config.py`、`.env.example`、README 中补配置说明。
  5. dry-run 验证 `matches()` 和 `messages_to_send`。

