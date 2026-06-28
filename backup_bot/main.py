from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from backup_bot.config import BackupSettings
from backup_bot.service import BackupService


LOGGER = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "查看备份机器人说明"),
        BotCommand("status", "查看备份状态"),
        BotCommand("backup_now", "立即执行一次备份检查"),
    ]
    await application.bot.set_my_commands(commands)

    settings: BackupSettings = application.bot_data["settings"]
    if application.job_queue is None:
        raise RuntimeError("Backup bot requires JobQueue. Install python-telegram-bot[job-queue] or [all].")
    application.job_queue.run_repeating(
        backup_job,
        interval=settings.interval_seconds,
        first=10,
        name="sqlite_backup",
    )
    me = await application.bot.get_me()
    LOGGER.info("Backup bot started as @%s", me.username)


def build_application(settings: BackupSettings | None = None) -> Application:
    settings = settings or BackupSettings.from_env()
    settings.validate()
    service = BackupService(settings)

    builder = Application.builder().token(settings.bot_token).post_init(post_init)
    if settings.proxy_url:
        builder.proxy(settings.proxy_url)
        builder.get_updates_proxy(settings.proxy_url)
    application = builder.build()
    application.bot_data["settings"] = settings
    application.bot_data["backup_service"] = service
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("status", status_handler))
    application.add_handler(CommandHandler("backup_now", backup_now_handler))
    return application


async def backup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    service: BackupService = context.application.bot_data["backup_service"]
    result = await service.run_once(context.bot)
    LOGGER.info(
        "Backup job completed: checked=%s sent=%s skipped=%s missing=%s delete_failed=%s",
        result.checked,
        result.sent,
        result.skipped,
        result.missing,
        result.delete_failed,
    )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "SQLite 备份机器人已启动。\n"
        "/status 查看状态\n"
        "/backup_now 立即执行一次备份检查"
    )


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not await _ensure_can_use_command(update, context):
        return
    service: BackupService = context.application.bot_data["backup_service"]
    await update.message.reply_text(service.status_text())


async def backup_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not await _ensure_can_use_command(update, context):
        return
    service: BackupService = context.application.bot_data["backup_service"]
    result = await service.run_once(context.bot)
    await update.message.reply_text(result.to_text())


async def _ensure_can_use_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings: BackupSettings = context.application.bot_data["settings"]
    if not settings.admin_user_ids:
        return True
    user = update.effective_user
    allowed = user is not None and user.id in settings.admin_user_ids
    if not allowed and update.message is not None:
        await update.message.reply_text("你没有权限使用这个备份命令。")
    return allowed
