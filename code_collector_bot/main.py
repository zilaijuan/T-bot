from __future__ import annotations

import json
import logging

from telegram import BotCommand, Message, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from code_collector_bot.config import CodeCollectorSettings
from code_collector_bot.models import TaskInput
from code_collector_bot.storage import TaskRepository


LOGGER = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "查看 Workflow Entry Bot 说明"),
        BotCommand("stats", "管理员查看任务状态统计"),
    ]
    await application.bot.set_my_commands(commands)
    me = await application.bot.get_me()
    LOGGER.info("Code collector bot started as @%s", me.username)


def build_application(settings: CodeCollectorSettings | None = None) -> Application:
    settings = settings or CodeCollectorSettings.from_env()
    settings.validate()

    repository = TaskRepository(settings.database_path)
    repository.init()

    builder = Application.builder().token(settings.bot_token).post_init(post_init)
    if settings.proxy_url:
        builder.proxy(settings.proxy_url)
        builder.get_updates_proxy(settings.proxy_url)
    application = builder.build()
    application.bot_data["settings"] = settings
    application.bot_data["task_repository"] = repository
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, collect_message_handler))
    return application


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "Workflow Entry Bot 已启动。\n"
        "发送任意消息后，我会把它写入 workflow_tasks，等待 Worker 执行。"
    )


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not _is_admin(update, context):
        return
    stats = _repository(context).count_by_status()
    if not stats:
        await update.message.reply_text("暂无任务。")
        return
    lines = ["任务状态统计："]
    lines.extend(f"{status}: {total}" for status, total in sorted(stats.items()))
    await update.message.reply_text("\n".join(lines))


async def collect_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    if not _can_submit(update, context):
        await update.message.reply_text("当前机器人不允许你提交任务。")
        return

    message = update.message
    settings = _settings(context)
    content = _message_content(message)
    task = TaskInput(
        user_id=update.effective_user.id,
        username=update.effective_user.username or update.effective_user.full_name,
        chat_id=update.effective_chat.id,
        message_id=message.message_id,
        message_type=_message_type(message),
        message_content=content,
        target_worker=settings.default_worker,
        telegram_file_id=_telegram_file_id(message),
        raw_message_json=json.dumps(message.to_dict(), ensure_ascii=False, default=str),
    )
    record = _repository(context).create_task(task)
    await message.reply_text(f"任务已接收。\nTask ID: {record.task_id}\nWorker: {record.target_worker}")


def _message_content(message: Message) -> str:
    return message.text or message.caption or ""


def _message_type(message: Message) -> str:
    if message.text:
        return "text"
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.document:
        return "document"
    if message.audio:
        return "audio"
    if message.voice:
        return "voice"
    return "unknown"


def _telegram_file_id(message: Message) -> str | None:
    if message.photo:
        return message.photo[-1].file_id
    if message.video:
        return message.video.file_id
    if message.document:
        return message.document.file_id
    if message.audio:
        return message.audio.file_id
    if message.voice:
        return message.voice.file_id
    return None


def _settings(context: ContextTypes.DEFAULT_TYPE) -> CodeCollectorSettings:
    return context.application.bot_data["settings"]


def _repository(context: ContextTypes.DEFAULT_TYPE) -> TaskRepository:
    return context.application.bot_data["task_repository"]


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return user is not None and user.id in _settings(context).admin_user_ids


def _can_submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = _settings(context)
    return settings.allow_public_submit or _is_admin(update, context)
