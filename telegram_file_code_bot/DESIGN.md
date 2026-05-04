# Telegram File Code Bot 设计文档

## 1. 项目定位

本项目是一个基于 Telegram 的内容暂存与取回机器人。

用户向机器人发送文字、图片、视频、文件等内容后，机器人将这些内容组织成一个 Bundle，并生成一个取件码。之后任何用户向机器人发送该取件码，机器人会把对应的内容按原顺序发送回给用户。

项目目标不是只做一个 demo，而是设计成一个结构清晰、可配置、可扩展的小型服务。

## 2. 核心概念

### 2.1 Bundle

Bundle 是一个已经完成创建、可以通过取件码取回的内容包。

字段建议：

```text
Bundle
  code
  owner_user_id
  description
  visibility
  created_at
  expires_at
  max_downloads
  download_count
  status
```

说明：

- `code` 是用户看到和使用的取件码。
- `owner_user_id` 是创建者 Telegram 用户 ID。
- `description` 是用户为内容包添加的描述，可为空。
- `expires_at` 为空时表示不过期。
- `max_downloads` 为空时表示不限制领取次数。
- `download_count` 记录已经被领取的次数。
- `status` 可用于标记 active、expired、deleted 等状态。

### 2.2 BundleItem

BundleItem 是 Bundle 中的一条具体内容。

字段建议：

```text
BundleItem
  bundle_id
  position
  type
  telegram_file_id
  local_path
  text
  caption
  file_name
  mime_type
  size
  metadata_json
```

说明：

- `position` 用于保证取回时按用户上传顺序发送。
- `type` 可取值：`text`、`photo`、`video`、`document`、`audio`、`voice` 等。
- `telegram_file_id` 用于复用 Telegram 文件。
- `local_path` 用于本地或对象存储文件。
- `metadata_json` 用于保留 Telegram 特有字段或后续扩展字段。

### 2.3 DraftBundle

DraftBundle 是用户正在编辑、尚未生成取件码的临时内容包。

字段建议：

```text
DraftBundle
  user_id
  description
  expiry_spec
  items
  created_at
  updated_at
```

DraftBundle 在用户发送 `/done` 后固化为 Bundle，并生成取件码。

## 3. 用户交互设计

### 3.1 自动草稿机制

用户不必先发送 `/new`。以下行为都等同于已经开始了一个新草稿：

- 直接发送文字
- 直接发送图片
- 直接发送视频
- 直接发送文件
- 直接发送 `/desc 描述`

如果用户当前没有草稿，机器人自动创建一个 DraftBundle。

### 3.2 创建内容包

推荐流程：

```text
/desc 这是一组会议资料
[发送图片]
[发送视频]
[发送文件]
/done
```

机器人在 `/done` 后生成取件码。

### 3.3 `/new`

`/new` 用于显式开始一个新草稿，或设置有效期。

示例：

```text
/new
/new 7d
/new forever
```

如果用户已经有未完成草稿，机器人应提示：

```text
你已有一个未完成的内容包。
发送 /done 生成取件码，发送 /cancel 放弃当前内容包。
```

是否支持 `/new force` 重新开始，可以作为后续增强项。

### 3.4 `/desc`

`/desc` 用于设置或覆盖当前草稿的描述。

示例：

```text
/desc 这是项目截图，给设计同事查看
```

规则：

- 如果当前没有草稿，则自动创建草稿。
- 如果当前已有描述，则新描述覆盖旧描述。
- 描述字段属于 Bundle，不作为普通文本 item 保存。

### 3.5 `/done`

`/done` 将当前草稿固化为 Bundle，并生成取件码。

规则：

- 如果草稿没有任何 item，但只有 description，应拒绝生成。
- 如果配置了 `MAX_ITEMS_PER_BUNDLE`，生成前需要检查 item 数量。
- 如果配置了 `MAX_CODE_SUMMARY_LENGTH`，生成前需要检查取件码摘要长度。
- 生成成功后清除当前用户草稿。

### 3.6 `/cancel`

`/cancel` 放弃当前草稿。

### 3.7 取回内容

用户发送取件码后：

```text
用户发送 code
-> 标准化 code
-> 查询 Bundle
-> 检查是否存在
-> 检查是否过期
-> 检查是否超过领取次数
-> 先发送 description
-> 按 position 顺序发送所有 BundleItem
-> 增加 download_count
```

如果 Bundle 有 description，取回时应先发送 description，再发送内容。

## 4. 取件码格式

取件码由内容摘要和随机码组成：

```text
{SUMMARY}-{RANDOM}
```

示例：

```text
P3V1F2-K7M9Q2RA
P200-K7M9Q2RA
T2P200V15F7A1-K7M9Q2RA
```

### 4.1 内容摘要

内容摘要用于体现 Bundle 中包含了多少文字、图片、视频、文件、音频。

类型标记：

```text
T = text
P = photo
V = video
F = file/document
A = audio/voice
```

摘要生成规则：

- 固定顺序：`T P V F A`
- 只显示数量大于 0 的类型
- 数量显示真实值
- 不压缩数量
- 不截断数量

示例：

```text
P200
P200V3F18
T1P12V4F300A2
```

如果有 200 张图片，则必须显示为：

```text
P200
```

不能压缩为 `P99` 或其他形式。

### 4.2 随机码

随机码默认 8 位。

推荐字符集：

```text
ABCDEFGHJKLMNPQRSTUVWXYZ23456789
```

避免容易混淆的字符：

```text
0 O 1 I L
```

### 4.3 权威数据来源

取件码里的摘要只作为用户可读信息，不作为权威数据。

系统取回内容时必须以数据库中的 BundleItem 为准。

也就是说，即使取件码中包含 `P3V1F2`，系统也不能只根据摘要判断实际内容，而必须读取数据库。

## 5. 配置项设计

建议 `.env` 支持：

```env
TELEGRAM_FILE_CODE_BOT_TOKEN=
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

ADMIN_USER_IDS=
ALLOW_PUBLIC_UPLOAD=true
ALLOW_PUBLIC_REDEEM=true

WEB_ENABLED=false
PUBLIC_BASE_URL=
```

### 5.1 `DEFAULT_EXPIRY`

`DEFAULT_EXPIRY` 是取件码的默认有效期。当用户直接发送内容，或发送 `/new` 但没有指定有效期时，系统使用该配置。

支持格式：

```text
30m      30 分钟
12h      12 小时
7d       7 天
4w       4 周
forever  永久有效
```

其中：

```text
m = 分钟
h = 小时
d = 天
w = 周
forever = 永久有效
```

### 5.2 `MAX_ITEMS_PER_BUNDLE`

限制单个 Bundle/Draft 中最多允许多少个 item。

规则：

- 未配置：不限制
- 空字符串：不限制
- `0`：不限制
- 负数：不限制
- 正整数：启用限制

示例：

```env
MAX_ITEMS_PER_BUNDLE=500
```

表示一个 Bundle 最多允许 500 个 item。

### 5.3 `MAX_CODE_SUMMARY_LENGTH`

限制取件码中 `SUMMARY` 部分的最大字符数。

规则：

- 未配置：不限制
- 空字符串：不限制
- `0`：不限制
- 负数：不限制
- 正整数：启用限制

如果超过限制，系统必须拒绝生成取件码，不能压缩、截断或改写摘要。

示例：

```env
MAX_CODE_SUMMARY_LENGTH=64
```

如果真实摘要超过 64 个字符，机器人提示用户减少内容数量，或联系管理员调整配置。

### 5.4 `PAGINATED_REDEEM_ENABLED`

控制使用取件码取回内容时是否按页批量发送。

规则：

- `false`：默认值，保持原行为，一次性发送全部内容。
- `true`：当内容数量超过 `REDEEM_PAGE_SIZE` 时，分页发送。

分页模式下，机器人先发送第一页内容，然后发送分页按钮。按钮包括：

- 上一页
- 下一页
- 当前页附近的页码

用户点击按钮时，机器人发送对应页的内容。

### 5.5 `REDEEM_PAGE_SIZE`

分页取回时每页发送的内容条数。

示例：

```env
REDEEM_PAGE_SIZE=10
```

表示每页最多发送 10 条 BundleItem。

### 5.6 `CODE_LIST_DESCRIPTION_LENGTH`

管理员取件码列表中显示的描述摘要长度。

示例：

```env
CODE_LIST_DESCRIPTION_LENGTH=10
```

表示 `/codes` 命令返回列表时，描述最多显示 10 个字符，超出后用省略号表示。

## 6. 存储策略

建议将存储抽象为 `StorageBackend`。

第一版优先支持：

```text
TelegramFileIdStorage
```

即优先保存 Telegram `file_id`，取回时直接通过 Telegram 发送。

后续可扩展：

```text
LocalFileStorage
S3Storage
```

设计原则：

- Bot handler 不直接关心文件保存细节。
- Core service 只依赖存储接口。
- 具体存储实现可替换。

## 7. 推荐项目结构

```text
telegram_file_code_bot/
  app/
    main.py
    config.py
    logging.py

    bot/
      handlers.py
      keyboards.py
      responses.py
      delivery.py

    core/
      code_service.py
      bundle_service.py
      policy.py
      models.py

    storage/
      database.py
      sqlite_repo.py
      migrations/
      file_store.py

    web/
      app.py
      templates/
      static/

    jobs/
      cleanup.py
```

## 8. 管理员功能

第一版建议支持：

```text
/stats
/info CODE
/delete CODE
/recent
```

后续可扩展：

```text
/ban USER_ID
/unban USER_ID
```

## 9. 第一版范围

第一版建议实现：

- 自动草稿机制
- `/new`
- `/desc`
- `/done`
- `/cancel`
- 文字、图片、视频、文件上传
- Bundle description
- 带内容摘要的取件码
- 不压缩、不截断的真实数量摘要
- 可选的 `MAX_ITEMS_PER_BUNDLE`
- 可选的 `MAX_CODE_SUMMARY_LENGTH`
- SQLite 存储
- Telegram `file_id` 存储
- 管理员统计、查询、删除

第一版暂不优先实现：

- 复杂 Web 上传
- Web 管理后台
- S3 存储
- 用户付费或复杂权限系统

## 10. 待确认事项

后续实现前仍需确认：

- 默认有效期是 `7d`、`30d` 还是 `forever`
- 是否允许所有人上传
- 是否允许所有人取回
- description 最大长度是否需要配置
- 单个用户是否需要每日上传限额
- 取回时是否通知上传者
- 是否支持一次性领取码
