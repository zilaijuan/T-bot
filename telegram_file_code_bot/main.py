from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from telegram import Message, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram_file_code_bot.config import Settings
from telegram_file_code_bot.database import Database, MediaRecord


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger(__name__)

CODE_PATTERN = re.compile(r"^[A-Z0-9]{4,64}$")


@dataclass(frozen=True, slots=True)
class IncomingMedia:
    media_type: str
    file_id: str
    file_name: str | None
    mime_type: str | None
    caption: str | None


async def post_init(application: Application) -> None:
    me = await application.bot.get_me()
    application.bot_data["bot_username"] = me.username
    LOGGER.info("Bot started as @%s", me.username)


async def post_shutdown(application: Application) -> None:
    database: Database = application.bot_data["database"]
    database.close()


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if context.args:
        await try_deliver_by_code(update, context, context.args[0])
        return

    await update.message.reply_text(
        "发送图片、视频或文件给我，我会返回一个随机取件码。\n"
        "之后任何人把这个取件码发给我，我就会把原文件发回去。"
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    await update.message.reply_text(
        "用法：\n"
        "1. 发送图片、视频或文件\n"
        "2. 收到随机取件码\n"
        "3. 发送取件码即可取回文件"
    )


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    incoming_media = extract_media(update.message)
    if incoming_media is None:
        return

    database: Database = context.application.bot_data["database"]
    settings: Settings = context.application.bot_data["settings"]

    record = database.create_record(
        media_type=incoming_media.media_type,
        file_id=incoming_media.file_id,
        caption=incoming_media.caption,
        uploader_id=update.effective_user.id,
        file_name=incoming_media.file_name,
        mime_type=incoming_media.mime_type,
        code_length=settings.code_length,
    )

    deep_link = build_deep_link(
        context.application.bot_data.get("bot_username"),
        record.code,
    )

    message = [f"取件码：{record.code}"]
    if deep_link:
        message.append(f"分享链接：{deep_link}")
    message.append("任何人把这串码发给我，都能取回这个文件。")

    await update.message.reply_text("\n".join(message))


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    await try_deliver_by_code(update, context, update.message.text)


async def try_deliver_by_code(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    raw_text: str,
) -> None:
    if update.message is None:
        return

    code = normalize_code(raw_text)
    if code is None:
        await update.message.reply_text(
            "没识别到有效取件码。请直接发送取件码，或者先上传图片、视频、文件。"
        )
        return

    database: Database = context.application.bot_data["database"]
    record = database.get_record(code)
    if record is None:
        await update.message.reply_text("这个取件码不存在，或者输入错了。")
        return

    try:
        await deliver_record(update.message, record)
    except BadRequest as exc:
        LOGGER.exception("Failed to deliver code %s", code)
        await update.message.reply_text(f"取件失败：{exc.message}")


async def deliver_record(message: Message, record: MediaRecord) -> None:
    if record.media_type == "photo":
        await message.reply_photo(
            photo=record.file_id,
            caption=record.caption,
        )
        return

    if record.media_type == "video":
        await message.reply_video(
            video=record.file_id,
            caption=record.caption,
        )
        return

    if record.media_type == "document":
        await message.reply_document(
            document=record.file_id,
            caption=record.caption,
        )
        return

    await message.reply_text("这个取件码对应的文件类型暂不支持。")


def extract_media(message: Message) -> IncomingMedia | None:
    if message.photo:
        largest_photo = max(message.photo, key=lambda item: item.file_size or 0)
        return IncomingMedia(
            media_type="photo",
            file_id=largest_photo.file_id,
            file_name=None,
            mime_type=None,
            caption=message.caption,
        )

    if message.video:
        return IncomingMedia(
            media_type="video",
            file_id=message.video.file_id,
            file_name=message.video.file_name,
            mime_type=message.video.mime_type,
            caption=message.caption,
        )

    if message.document:
        return IncomingMedia(
            media_type="document",
            file_id=message.document.file_id,
            file_name=message.document.file_name,
            mime_type=message.document.mime_type,
            caption=message.caption,
        )

    return None


def normalize_code(raw_text: str) -> str | None:
    code = raw_text.strip().upper()
    if not CODE_PATTERN.fullmatch(code):
        return None
    return code


def build_deep_link(bot_username: str | None, code: str) -> str | None:
    if not bot_username:
        return None
    return f"https://t.me/{bot_username}?start={code}"


def build_application() -> Application:
    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.init()

    application = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.bot_data["settings"] = settings
    application.bot_data["database"] = database

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, media_handler)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )

    return application


def run() -> None:
    application = build_application()
    application.run_polling(drop_pending_updates=False)
