# Telegram Bot 分发与多 Worker 执行系统设计（v0.2）

> 本文档用于系统设计持续演进与会话续接 当前版本：v0.2（2026-06）

------------------------------------------------------------------------

# 一、系统目标

构建一个轻量级 Telegram 消息分发与执行系统，实现：

-   用户消息接入与任务化
-   多 Worker 并行执行不同第三方 Telegram Bot
-   Worker 内任务串行执行
-   支持多轮对话 + 分页操作
-   支持中断恢复
-   支持动态等待策略（Delay）
-   支持状态驱动执行模型

------------------------------------------------------------------------

# 二、整体架构

    用户
      ↓
    入口 Telegram Bot（Dispatcher）
      ↓
    数据库（Task Storage）
      ↓
    Worker Pool（并行）
      ↓
    Worker（Rule + Driver + Executor）
      ↓
    Telethon 用户账号代理（User Agent）
      ↓
    第三方 Telegram Bot

------------------------------------------------------------------------

# 三、核心设计原则

## 1. 职责分离

-   Entry Bot：只负责写 DB
-   Worker：只负责执行任务
-   Driver：只负责对接第三方 Bot
-   DB：负责状态与恢复

------------------------------------------------------------------------

## 2. Actor 模型

-   Worker = Actor
-   Worker 之间并行
-   Worker 内任务串行
-   Driver step 化执行

------------------------------------------------------------------------

## 3. 状态驱动执行（State Driven Execution）

系统不是函数调用，而是状态机：

    Task → State → Execution → State Update → Continue

------------------------------------------------------------------------

# 四、数据库设计（Task）

## Task 表

    task_id
    user_id
    message_content
    status
    target_worker
    state_payload
    next_run_at
    created_at
    updated_at

------------------------------------------------------------------------

## status

    NEW
    RUNNING
    WAIT
    DONE
    FAILED
    RETRY

------------------------------------------------------------------------

## state_payload（关键）

用于恢复执行状态：

``` json
{
  "page": 3,
  "last_message_id": 12345,
  "last_action": "click_next"
}
```

------------------------------------------------------------------------

## next_run_at（调度核心）

用于延迟调度：

-   控制 Action Delay
-   控制 Task Delay
-   控制 Retry Delay

------------------------------------------------------------------------

# 五、Worker 设计

## Worker 定义

    Worker = Rule + Driver + Executor

------------------------------------------------------------------------

## Worker 模型

    while True:
        task = fetch_task(next_run_at <= now)

        driver = DriverFactory(task.target_worker)

        state = task.state_payload

        result = driver.step(state)

        update_task(result)

------------------------------------------------------------------------

## Worker 特性

-   Worker 之间并行
-   Worker 内串行执行
-   Worker 无业务逻辑
-   Worker 不解析 Bot 行为

------------------------------------------------------------------------

# 六、规则系统（Rule System）

## 当前设计：Hard Code in Worker

每个 Worker 内部维护规则：

``` python
RULES = [
    {
        "name": "order",
        "keywords": ["订单", "下单"]
    },
    {
        "name": "payment",
        "keywords": ["支付", "充值"]
    }
]
```

------------------------------------------------------------------------

## 匹配逻辑

    message → RULES → target_worker

------------------------------------------------------------------------

## 特点

-   简单
-   可控
-   无配置依赖
-   适合 MVP 阶段

------------------------------------------------------------------------

# 七、Driver 系统（核心）

## Driver 定义

    Driver = 第三方 Bot 适配器

------------------------------------------------------------------------

## Driver 接口

    init(task, state)
    step(state) → ExecutionResult
    restore(state_payload)

------------------------------------------------------------------------

## Driver 能力

-   发送消息
-   接收回复
-   点击按钮
-   处理分页
-   多轮对话
-   状态恢复

------------------------------------------------------------------------

# 八、Execution Result（核心设计）

Driver 每一步返回 ExecutionResult：

    status
    next_action
    delay
    state_payload
    result

------------------------------------------------------------------------

## status

    CONTINUE
    WAIT_REPLY
    DONE
    RETRY
    FAILED

------------------------------------------------------------------------

## next_action

    SEND_MESSAGE
    CLICK_BUTTON
    CLICK_NEXT_PAGE
    WAIT
    NONE

------------------------------------------------------------------------

## delay（统一模型）

所有 delay 统一由 Driver 决定：

-   Action Delay
-   Task Delay
-   Retry Delay

Worker 不区分语义。

------------------------------------------------------------------------

## 示例

    status = CONTINUE
    next_action = CLICK_NEXT_PAGE
    delay = 2

    status = DONE
    delay = 15

    status = RETRY
    delay = 30

------------------------------------------------------------------------

# 九、分页与多轮对话处理

Driver 内部统一处理：

-   next page
-   inline button
-   pagination
-   multi-step dialog

Worker 不参与逻辑判断。

------------------------------------------------------------------------

# 十、User Agent（Telethon）

## 职责

-   使用 Telegram 用户账号登录
-   与第三方 Bot 通信
-   发送消息
-   接收消息
-   点击按钮

------------------------------------------------------------------------

# 十一、调度模型（核心）

## Pull-based Scheduler

Worker 定时扫描：

    status != DONE
    AND next_run_at <= NOW()

------------------------------------------------------------------------

## 优点

-   简单可靠
-   易恢复
-   不依赖消息队列
-   支持重启恢复

------------------------------------------------------------------------

# 十二、中断恢复机制

## 核心思想

> 恢复状态，而不是恢复执行

------------------------------------------------------------------------

## 恢复流程

    DB state_payload
       ↓
    Driver.restore()
       ↓
    继续 step()

------------------------------------------------------------------------

## 支持场景

-   Worker 崩溃恢复
-   服务重启恢复
-   网络异常恢复
-   Telegram session 重连

------------------------------------------------------------------------

# 十三、系统本质

当前系统已经不是 Bot 系统，而是：

> Telegram Workflow Execution Engine（工作流执行引擎）

------------------------------------------------------------------------

# 十四、当前版本特性

✔ Task 化\
✔ Worker 并行\
✔ Worker 内串行\
✔ Rule hard code（Worker 内）\
✔ Driver 插件化\
✔ ExecutionResult 驱动\
✔ 分页支持\
✔ 多轮对话支持\
✔ 中断恢复\
✔ next_run_at 调度模型\
✔ Telethon 用户代理执行

------------------------------------------------------------------------

# 十五、后续演进方向（未实现）

-   Rule Engine 独立化
-   Driver 插件标准库
-   多用户 Agent pool
-   分布式 Worker
-   AI routing
-   自动 Driver 识别机制

------------------------------------------------------------------------

# 十六、会话续接说明

下次开启新会话时可直接使用：

> "继续 Telegram Workflow Execution Engine（v0.2），包含 Worker +
> Driver + ExecutionResult + next_run_at 调度模型"

即可无缝继续设计。
