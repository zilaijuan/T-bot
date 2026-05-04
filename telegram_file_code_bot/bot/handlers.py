from __future__ import annotations

import html
import secrets
from math import ceil

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from telegram_file_code_bot.app.config import Settings
from telegram_file_code_bot.bot.delivery import PAGE_CALLBACK_PREFIX, deliver_bundle, deliver_bundle_page
from telegram_file_code_bot.bot.responses import bundle_created_text, bundle_info_text, draft_summary, start_text, stats_text
from telegram_file_code_bot.core.bundle_service import BundleService
from telegram_file_code_bot.core.code_service import extract_codes, normalize_code
from telegram_file_code_bot.core.models import BundleItemInput, ContentType
from telegram_file_code_bot.storage.sqlite_repo import SQLiteBundleRepository

PAGE_TOKEN_CACHE_LIMIT = 1000
DEFAULT_RECENT_LIMIT = 10
MAX_RECENT_LIMIT = 100
CODE_LIST_PAGE_SIZE = 10
CODE_LIST_CALLBACK_PREFIX = "codes"


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
    application.add_handler(CommandHandler("setdesc", setdesc_handler))
    application.add_handler(CommandHandler("recent", recent_handler))
    application.add_handler(CommandHandler("codes", codes_handler))
    application.add_handler(CallbackQueryHandler(codes_page_callback_handler, pattern=rf"^{CODE_LIST_CALLBACK_PREFIX}:\d+$"))
    application.add_handler(CallbackQueryHandler(page_callback_handler, pattern=rf"^{PAGE_CALLBACK_PREFIX}:[^:]+:\d+$"))
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
    await update.message.reply_text(bundle_created_text(bundle), parse_mode="HTML")


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


async def setdesc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if len(context.args) < 2:
        await update.message.reply_text("用法：/setdesc CODE 描述文字")
        return

    code = normalize_code(context.args[0])
    description = " ".join(context.args[1:]).strip() or None
    repository = _repository(context)
    bundle = repository.get_bundle(code)
    if bundle is None:
        await update.message.reply_text("没有找到这个取件码。")
        return
    if bundle.owner_user_id != update.effective_user.id and not _is_admin(update, context):
        await update.message.reply_text("只有创建者或管理员可以修改这个取件码的描述。")
        return

    repository.update_description(code, description)
    await update.message.reply_text("描述已更新。")


async def recent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not _is_admin(update, context):
        return

    limit = DEFAULT_RECENT_LIMIT
    if context.args:
        try:
            limit = int(context.args[0])
        except ValueError:
            await update.message.reply_text("用法：/recent [数量]")
            return
        if limit <= 0:
            await update.message.reply_text("数量必须大于 0。")
            return
        limit = min(limit, MAX_RECENT_LIMIT)

    bundles = _repository(context).recent_bundles(limit=limit)
    if not bundles:
        await update.message.reply_text("暂无内容包。")
        return
    lines = _format_bundle_list_lines(
        bundles,
        description_length=_settings(context).code_list_description_length,
    )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def codes_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not _is_admin(update, context):
        return

    page = 1
    if context.args:
        try:
            page = int(context.args[0])
        except ValueError:
            await update.message.reply_text("用法：/codes [页码]")
            return
        if page <= 0:
            await update.message.reply_text("页码必须大于 0。")
            return

    await _send_codes_page(update.message, context, page)


async def codes_page_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return
    await query.answer()
    if query.from_user is None or query.from_user.id not in _settings(context).admin_user_ids:
        await query.message.reply_text("只有管理员可以查看取件码列表。")
        return

    parts = query.data.split(":") if query.data else []
    if len(parts) != 2:
        return
    try:
        page = int(parts[1])
    except ValueError:
        return

    await _send_codes_page(query.message, context, page)


async def _send_codes_page(message: Message, context: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    repository = _repository(context)
    total = repository.count_bundles()
    if total == 0:
        await message.reply_text("暂无内容包。")
        return

    total_pages = max(1, ceil(total / CODE_LIST_PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    bundles = repository.list_bundles(limit=CODE_LIST_PAGE_SIZE, offset=(page - 1) * CODE_LIST_PAGE_SIZE)
    lines = [f"取件码列表 第 {page}/{total_pages} 页，共 {total} 个"]
    lines.extend(_format_bundle_list_lines(bundles, description_length=_settings(context).code_list_description_length))
    await message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=_build_codes_page_keyboard(current_page=page, total_pages=total_pages),
    )


async def page_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return
    await query.answer()
    if not _can_redeem_user(query.from_user.id if query.from_user else None, context):
        await query.message.reply_text("当前机器人不允许公开取回内容。")
        return

    parts = query.data.split(":") if query.data else []
    if len(parts) != 3:
        return
    _, token, raw_page = parts
    code = _page_token_cache(context).get(token)
    if code is None:
        await query.message.reply_text("分页按钮已失效，请重新发送取件码。")
        return

    try:
        page = int(raw_page)
    except ValueError:
        return

    try:
        bundle = _bundle_service(context).get_redeemable_bundle(code)
    except ValueError as exc:
        await query.message.reply_text(str(exc))
        return

    await deliver_bundle_page(
        query.message,
        bundle,
        page=page,
        page_size=_settings(context).redeem_page_size,
        token=token,
    )


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
        _bundle_service(context).add_item(
            user_id=update.effective_user.id,
            owner_name=_owner_name(update),
            item=item,
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None or update.effective_user is None:
        return

    text = update.message.text.strip()
    service = _bundle_service(context)
    codes = extract_codes(text)
    if not service.has_draft(update.effective_user.id) and codes:
        for code in codes:
            await redeem_code(update.message, context, code)
        return

    if not _can_upload(update, context):
        await update.message.reply_text("当前机器人不允许你创建内容包。")
        return

    item = BundleItemInput(type=ContentType.TEXT, text=text)
    try:
        service.add_item(user_id=update.effective_user.id, owner_name=_owner_name(update), item=item)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return


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

    settings = _settings(context)
    if settings.paginated_redeem_enabled and len(bundle.items) > settings.redeem_page_size:
        token = _remember_page_token(context, bundle.code)
        await deliver_bundle_page(
            message,
            bundle,
            page=1,
            page_size=settings.redeem_page_size,
            token=token,
        )
    else:
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


def _page_token_cache(context: ContextTypes.DEFAULT_TYPE) -> dict[str, str]:
    return context.application.bot_data.setdefault("page_token_cache", {})


def _remember_page_token(context: ContextTypes.DEFAULT_TYPE, code: str) -> str:
    cache = _page_token_cache(context)
    if len(cache) >= PAGE_TOKEN_CACHE_LIMIT:
        cache.pop(next(iter(cache)))
    for _ in range(20):
        token = secrets.token_urlsafe(6)
        if token not in cache:
            cache[token] = code
            return token
    raise RuntimeError("无法创建分页会话，请稍后重试。")


def _format_bundle_list_lines(bundles, *, description_length: int) -> list[str]:
    lines = []
    for bundle in bundles:
        description = _description_preview(bundle.description, description_length)
        lines.append(
            f"<code>{html.escape(bundle.code)}</code> | {len(bundle.items)} 条 | "
            f"{html.escape(bundle.status.value)} | {html.escape(description)}"
        )
    return lines


def _description_preview(description: str | None, length: int) -> str:
    if not description:
        return "无描述"
    stripped = description.strip()
    if len(stripped) <= length:
        return stripped
    return stripped[:length]


def _build_codes_page_keyboard(*, current_page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None

    rows: list[list[InlineKeyboardButton]] = []
    nav_row: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav_row.append(_codes_page_button("上一页", current_page - 1))
    if current_page < total_pages:
        nav_row.append(_codes_page_button("下一页", current_page + 1))
    if nav_row:
        rows.append(nav_row)

    start = max(1, current_page - 2)
    end = min(total_pages, current_page + 2)
    rows.append([
        _codes_page_button(f"·{page}·" if page == current_page else str(page), page)
        for page in range(start, end + 1)
    ])
    return InlineKeyboardMarkup(rows)


def _codes_page_button(label: str, page: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=f"{CODE_LIST_CALLBACK_PREFIX}:{page}")


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
    return _can_redeem_user(message.from_user.id if message.from_user else None, context)


def _can_redeem_user(user_id: int | None, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = _settings(context)
    if settings.allow_public_redeem:
        return True
    return user_id is not None and user_id in settings.admin_user_ids
