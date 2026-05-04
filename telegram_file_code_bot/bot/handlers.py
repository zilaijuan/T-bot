from __future__ import annotations

from telegram import Message, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from telegram_file_code_bot.app.config import Settings
from telegram_file_code_bot.bot.delivery import deliver_bundle
from telegram_file_code_bot.bot.responses import bundle_created_text, bundle_info_text, draft_summary, start_text, stats_text
from telegram_file_code_bot.core.bundle_service import BundleService
from telegram_file_code_bot.core.code_service import looks_like_code, normalize_code
from telegram_file_code_bot.core.models import BundleItemInput, ContentType
from telegram_file_code_bot.storage.sqlite_repo import SQLiteBundleRepository


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("new", new_handler))
    application.add_handler(CommandHandler("desc", desc_handler))
    application.add_handler(CommandHandler("done", done_handler))
    application.add_handler(CommandHandler("cancel", cancel_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CommandHandler("info", info_handler))
    application.add_handler(CommandHandler("delete", delete_handler))
    application.add_handler(CommandHandler("recent", recent_handler))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE, media_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if context.args:
        await redeem_code(update.message, context, context.args[0])
        return
    await update.message.reply_text(start_text())


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is not None:
        await update.message.reply_text(start_text())


async def new_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if not _can_upload(update, context):
        await update.message.reply_text("当前机器人不允许你创建内容包。")
        return

    expiry_spec = " ".join(context.args).strip() or None
    service = _bundle_service(context)
    try:
        draft = service.start_draft(
            user_id=update.effective_user.id,
            owner_name=_owner_name(update),
            expiry_spec=expiry_spec,
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text("已开始新的内容包。\n" + draft_summary(draft))


async def desc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if not _can_upload(update, context):
        await update.message.reply_text("当前机器人不允许你创建内容包。")
        return

    description = " ".join(context.args).strip()
    if not description:
        await update.message.reply_text("请在 /desc 后面加上描述文字。")
        return

    draft = _bundle_service(context).set_description(
        user_id=update.effective_user.id,
        owner_name=_owner_name(update),
        description=description,
    )
    await update.message.reply_text("描述已更新。\n" + draft_summary(draft))


async def done_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    try:
        bundle = _bundle_service(context).finish_draft(update.effective_user.id)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(bundle_created_text(bundle))


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if _bundle_service(context).cancel_draft(update.effective_user.id):
        await update.message.reply_text("当前内容包已放弃。")
    else:
        await update.message.reply_text("当前没有未完成的内容包。")


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not _is_admin(update, context):
        return
    stats = _repository(context).get_admin_stats()
    await update.message.reply_text(stats_text(stats))


async def info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not _is_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("用法：/info CODE")
        return
    bundle = _repository(context).get_bundle(normalize_code(context.args[0]))
    if bundle is None:
        await update.message.reply_text("没有找到这个取件码。")
        return
    await update.message.reply_text(bundle_info_text(bundle))


async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not _is_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("用法：/delete CODE")
        return
    deleted = _repository(context).mark_deleted(normalize_code(context.args[0]))
    await update.message.reply_text("已删除。" if deleted else "没有找到可删除的取件码。")


async def recent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not _is_admin(update, context):
        return
    bundles = _repository(context).recent_bundles(limit=10)
    if not bundles:
        await update.message.reply_text("暂无内容包。")
        return
    lines = [f"{bundle.code} | {len(bundle.items)} 条 | {bundle.status.value}" for bundle in bundles]
    await update.message.reply_text("\n".join(lines))


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if not _can_upload(update, context):
        await update.message.reply_text("当前机器人不允许你创建内容包。")
        return

    item = _extract_media_item(update.message)
    if item is None:
        return
    try:
        draft = _bundle_service(context).add_item(
            user_id=update.effective_user.id,
            owner_name=_owner_name(update),
            item=item,
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text("已加入当前内容包。\n" + draft_summary(draft) + "\n继续发送内容，或发送 /done 生成取件码。")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None or update.effective_user is None:
        return

    text = update.message.text.strip()
    service = _bundle_service(context)
    if not service.has_draft(update.effective_user.id) and looks_like_code(text):
        await redeem_code(update.message, context, text)
        return

    if not _can_upload(update, context):
        await update.message.reply_text("当前机器人不允许你创建内容包。")
        return

    item = BundleItemInput(type=ContentType.TEXT, text=text)
    try:
        draft = service.add_item(user_id=update.effective_user.id, owner_name=_owner_name(update), item=item)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text("文字已加入当前内容包。\n" + draft_summary(draft) + "\n继续发送内容，或发送 /done 生成取件码。")


async def redeem_code(message: Message, context: ContextTypes.DEFAULT_TYPE, raw_code: str) -> None:
    if not _can_redeem(message, context):
        await message.reply_text("当前机器人不允许公开取回内容。")
        return

    code = normalize_code(raw_code)
    try:
        bundle = _bundle_service(context).get_redeemable_bundle(code)
    except ValueError as exc:
        await message.reply_text(str(exc))
        return

    await deliver_bundle(message, bundle)
    _bundle_service(context).record_download(bundle.code)


def _extract_media_item(message: Message) -> BundleItemInput | None:
    if message.photo:
        photo = message.photo[-1]
        return BundleItemInput(
            type=ContentType.PHOTO,
            telegram_file_id=photo.file_id,
            caption=message.caption,
            size=photo.file_size,
        )
    if message.video:
        return BundleItemInput(
            type=ContentType.VIDEO,
            telegram_file_id=message.video.file_id,
            caption=message.caption,
            file_name=message.video.file_name,
            mime_type=message.video.mime_type,
            size=message.video.file_size,
        )
    if message.document:
        return BundleItemInput(
            type=ContentType.DOCUMENT,
            telegram_file_id=message.document.file_id,
            caption=message.caption,
            file_name=message.document.file_name,
            mime_type=message.document.mime_type,
            size=message.document.file_size,
        )
    if message.audio:
        return BundleItemInput(
            type=ContentType.AUDIO,
            telegram_file_id=message.audio.file_id,
            caption=message.caption,
            file_name=message.audio.file_name,
            mime_type=message.audio.mime_type,
            size=message.audio.file_size,
        )
    if message.voice:
        return BundleItemInput(
            type=ContentType.VOICE,
            telegram_file_id=message.voice.file_id,
            caption=message.caption,
            mime_type=message.voice.mime_type,
            size=message.voice.file_size,
        )
    return None


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _repository(context: ContextTypes.DEFAULT_TYPE) -> SQLiteBundleRepository:
    return context.application.bot_data["repository"]


def _bundle_service(context: ContextTypes.DEFAULT_TYPE) -> BundleService:
    return context.application.bot_data["bundle_service"]


def _owner_name(update: Update) -> str | None:
    if update.effective_user is None:
        return None
    return update.effective_user.username or update.effective_user.full_name


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return user is not None and user.id in _settings(context).admin_user_ids


def _can_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = _settings(context)
    return settings.allow_public_upload or _is_admin(update, context)


def _can_redeem(message: Message, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = _settings(context)
    if settings.allow_public_redeem:
        return True
    return message.from_user is not None and message.from_user.id in settings.admin_user_ids
