from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import Application

from telegram_file_code_bot.app.config import Settings
from telegram_file_code_bot.app.logging import configure_logging
from telegram_file_code_bot.bot.handlers import register_handlers
from telegram_file_code_bot.core.bundle_service import BundleService
from telegram_file_code_bot.core.code_service import CodeService
from telegram_file_code_bot.storage.sqlite_repo import SQLiteBundleRepository


LOGGER = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "查看使用说明或通过取件码取回内容"),
        BotCommand("help", "查看帮助"),
        BotCommand("new", "开始新的内容包，可带有效期"),
        BotCommand("desc", "设置当前内容包描述"),
        BotCommand("done", "生成取件码"),
        BotCommand("cancel", "放弃当前内容包"),
        BotCommand("setdesc", "更新指定取件码的描述"),
        BotCommand("info", "管理员查看取件码信息"),
        BotCommand("delete", "管理员删除取件码"),
        BotCommand("recent", "管理员查看最近内容包"),
        BotCommand("stats", "管理员查看统计信息"),
    ]
    await application.bot.set_my_commands(commands)
    me = await application.bot.get_me()
    LOGGER.info("Bot started as @%s", me.username)


def build_application(settings: Settings | None = None) -> Application:
    settings = settings or Settings.from_env()
    repository = SQLiteBundleRepository(settings.database_path)
    repository.init()

    code_service = CodeService(
        random_length=settings.code_random_length,
        max_summary_length=settings.max_code_summary_length,
    )
    bundle_service = BundleService(settings=settings, repository=repository, code_service=code_service)

    application = Application.builder().token(settings.bot_token).post_init(post_init).build()
    application.bot_data["settings"] = settings
    application.bot_data["repository"] = repository
    application.bot_data["code_service"] = code_service
    application.bot_data["bundle_service"] = bundle_service
    register_handlers(application)
    return application


def run() -> None:
    configure_logging()
    application = build_application()
    application.run_polling(allowed_updates=None)
