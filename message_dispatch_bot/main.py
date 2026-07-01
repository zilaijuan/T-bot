from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from message_dispatch_bot.config import MessageDispatchSettings
from message_dispatch_bot.dispatcher import MessageDispatcher
from message_dispatch_bot.storage import MessageDispatchRepository, SUBSCRIBER_INACTIVE


LOGGER = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "??????"),
        BotCommand("stop", "????"),
        BotCommand("status", "??????"),
    ]
    await application.bot.set_my_commands(commands)

    settings: MessageDispatchSettings = application.bot_data["settings"]
    if application.job_queue is None:
        raise RuntimeError("message_dispatch_bot requires JobQueue. Install python-telegram-bot[all].")
    application.job_queue.run_repeating(
        dispatch_job,
        interval=settings.interval_seconds,
        first=10,
        name="message_dispatch",
    )
    me = await application.bot.get_me()
    LOGGER.info("Message dispatch bot started as @%s interval=%ss", me.username, settings.interval_seconds)


def build_application(settings: MessageDispatchSettings | None = None) -> Application:
    settings = settings or MessageDispatchSettings.from_env()
    settings.validate()
    repository = MessageDispatchRepository(settings.database_path)
    repository.init()
    dispatcher = MessageDispatcher(settings, repository)

    builder = Application.builder().token(settings.bot_token).post_init(post_init)
    if settings.proxy_url:
        builder.proxy(settings.proxy_url)
        builder.get_updates_proxy(settings.proxy_url)
    application = builder.build()
    application.bot_data["settings"] = settings
    application.bot_data["repository"] = repository
    application.bot_data["dispatcher"] = dispatcher
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("stop", stop_handler))
    application.add_handler(CommandHandler("unsubscribe", stop_handler))
    application.add_handler(CommandHandler("status", status_handler))
    return application


async def dispatch_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    dispatcher: MessageDispatcher = context.application.bot_data["dispatcher"]
    processed = await dispatcher.run_once(context.bot)
    if processed:
        LOGGER.info("Message dispatch job processed %s output tasks.", processed)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    user = update.effective_user
    _repository(context).upsert_subscriber(
        user_id=user.id,
        chat_id=update.effective_chat.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    await update.message.reply_text("????????")


async def stop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    _repository(context).update_subscriber_status(update.effective_user.id, SUBSCRIBER_INACTIVE)
    await update.message.reply_text("??????")


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not _is_admin(update, context):
        await update.message.reply_text("??????????")
        return
    counts = _repository(context).subscriber_counts()
    lines = ["?? bot ???"]
    if counts:
        lines.extend(f"{status}: {total}" for status, total in sorted(counts.items()))
    else:
        lines.append("??????")
    await update.message.reply_text("\n".join(lines))


def _repository(context: ContextTypes.DEFAULT_TYPE) -> MessageDispatchRepository:
    return context.application.bot_data["repository"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> MessageDispatchSettings:
    return context.application.bot_data["settings"]


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = _settings(context)
    if not settings.admin_user_ids:
        return True
    user = update.effective_user
    return user is not None and user.id in settings.admin_user_ids
