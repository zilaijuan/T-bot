from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from telegram import InputFile, Message, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram_file_code_bot.config import Settings
from telegram_file_code_bot.database import (
    AdminStats,
    BundleItem,
    BundleItemInput,
    BundleRecord,
    Database,
)
from telegram_file_code_bot.state import RuntimeState
from telegram_file_code_bot.utils import (
    build_bundle_url,
    build_deep_link,
    format_datetime,
    format_expiry_label,
    normalize_code,
    parse_expiry_spec,
)
from telegram_file_code_bot.web import ManagedWebServer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger(__name__)

DRAFT_KEY = "upload_draft"


@dataclass(slots=True)
class UploadDraft:
    expiry_spec: str
    is_permanent: bool
    expires_at: str | None
    items: list[BundleItemInput]


async def post_init(application: Application) -> None:
    state: RuntimeState = application.bot_data["state"]
    me = await application.bot.get_me()
    state.bot_username = me.username
    LOGGER.info("Bot started as @%s", me.username)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if context.args:
        await try_deliver_by_code(update, context, context.args[0])
        return

    state = get_state(context)
    web_hint = ""
    if state.settings.web_enabled:
        web_base = state.settings.public_base_url or f"http://{state.settings.web_host}:{state.settings.web_port}"
        web_hint = f"\nWeb 上传页：{web_base}"

    await update.message.reply_text(
        "发送图片、视频或文件给我，我会返回一个取件码。\n"
        "需要一码多文件时，先发 /new 7d 或 /new forever，再连续发文件，最后发 /done。"
        f"{web_hint}"
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    settings = get_settings(context)
    await update.message.reply_text(
        "用法：\n"
        "1. 直接发送一个文件：立即生成一个取件码\n"
        f"2. 默认有效期：{settings.default_expiry_spec}\n"
        "3. 批量上传：/new 7d 或 /new forever\n"
        "4. 上传完成后发送 /done\n"
        "5. 放弃当前批次：/cancel\n"
        "6. 任何人发送取件码，都能取回对应文件\n"
        "7. 管理员可用 /stats 查看统计"
    )


async def new_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    settings = get_settings(context)
    raw_spec = " ".join(context.args).strip() or settings.default_expiry_spec

    try:
        expiry_policy = parse_expiry_spec(raw_spec, settings.default_expiry_spec)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    context.user_data[DRAFT_KEY] = UploadDraft(
        expiry_spec=expiry_policy.raw_spec,
        is_permanent=expiry_policy.is_permanent,
        expires_at=expiry_policy.expires_at.isoformat() if expiry_policy.expires_at else None,
        items=[],
    )

    await update.message.reply_text(
        "已开启批量上传。\n"
        "现在把图片、视频、文件连续发给我。\n"
        f"有效期：{format_expiry_label(is_permanent=expiry_policy.is_permanent, expires_at=expiry_policy.expires_at)}\n"
        "全部发完后发送 /done。"
    )


async def done_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    draft = get_draft(context)
    if draft is None:
        await update.message.reply_text("当前没有进行中的批量上传。先发 /new。")
        return

    if not draft.items:
        await update.message.reply_text("这个批次里还没有文件。先上传文件，或者发 /cancel。")
        return

    bundle = create_bundle_from_inputs(
        context=context,
        items=draft.items,
        uploader_id=update.effective_user.id,
        uploader_name=update.effective_user.username or update.effective_user.full_name,
        source="telegram",
        is_permanent=draft.is_permanent,
        expires_at=draft.expires_at,
    )
    context.user_data.pop(DRAFT_KEY, None)

    await update.message.reply_text(
        build_bundle_created_message(context, bundle, prefix="批量上传完成。")
    )


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if context.user_data.pop(DRAFT_KEY, None) is None:
        await update.message.reply_text("当前没有进行中的批量上传。")
        return

    await update.message.reply_text("当前批量上传已取消。")


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    settings = get_settings(context)
    if update.effective_user.id not in settings.admin_user_ids:
        await update.message.reply_text("你不是管理员。")
        return

    stats = get_database(context).get_admin_stats()
    await update.message.reply_text(build_stats_message(stats))


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    media_item = extract_media(update.message)
    if media_item is None:
        return

    draft = get_draft(context)
    if draft is not None:
        draft.items.append(media_item)
        await update.message.reply_text(
            f"已加入批次，当前共 {len(draft.items)} 个文件。\n"
            f"有效期：{format_expiry_label(is_permanent=draft.is_permanent, expires_at=draft.expires_at)}\n"
            "继续上传，或者发送 /done 完成。"
        )
        return

    settings = get_settings(context)
    try:
        expiry_policy = parse_expiry_spec(settings.default_expiry_spec, settings.default_expiry_spec)
    except ValueError as exc:
        await update.message.reply_text(f"默认有效期配置错误：{exc}")
        return

    bundle = create_bundle_from_inputs(
        context=context,
        items=[media_item],
        uploader_id=update.effective_user.id,
        uploader_name=update.effective_user.username or update.effective_user.full_name,
        source="telegram",
        is_permanent=expiry_policy.is_permanent,
        expires_at=expiry_policy.expires_at.isoformat() if expiry_policy.expires_at else None,
    )

    await update.message.reply_text(build_bundle_created_message(context, bundle, prefix="文件已保存。"))


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    if get_draft(context) is not None:
        await update.message.reply_text("你正在批量上传。继续发文件，或发送 /done 完成，/cancel 放弃。")
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
            "没识别到有效取件码。请直接发送取件码，或者先上传文件。"
        )
        return

    database = get_database(context)
    bundle = database.get_bundle(code)
    if bundle is None:
        await update.message.reply_text("这个取件码不存在，或者输入错了。")
        return

    if bundle.is_expired():
        await update.message.reply_text(
            f"这个取件码已经过期。\n到期时间：{format_datetime(bundle.expires_at)}"
        )
        return

    try:
        delivered_count = await deliver_bundle(update.message, bundle)
    except BadRequest as exc:
        LOGGER.exception("Failed to deliver code %s", code)
        await update.message.reply_text(f"取件失败：{exc.message}")
        return

    if delivered_count > 0:
        database.mark_bundle_delivered(code)


async def deliver_bundle(message: Message, bundle: BundleRecord) -> int:
    if len(bundle.items) > 1:
        await message.reply_text(f"找到 {len(bundle.items)} 个文件，开始发送。")

    delivered_count = 0
    for item in bundle.items:
        if await deliver_item(message, item):
            delivered_count += 1

    if delivered_count == 0:
        await message.reply_text("这个取件码对应的文件暂时无法发送。")

    return delivered_count


async def deliver_item(message: Message, item: BundleItem) -> bool:
    if item.storage_type == "telegram":
        return await deliver_telegram_item(message, item)

    if item.storage_type == "local":
        return await deliver_local_item(message, item)

    await message.reply_text(f"不支持的存储类型：{item.storage_type}")
    return False


async def deliver_telegram_item(message: Message, item: BundleItem) -> bool:
    payload = item.telegram_file_id
    if not payload:
        await message.reply_text("这个文件缺少 Telegram file_id。")
        return False

    if item.media_type == "photo":
        await message.reply_photo(photo=payload, caption=item.caption)
        return True

    if item.media_type == "video":
        await message.reply_video(video=payload, caption=item.caption)
        return True

    if item.media_type == "document":
        await message.reply_document(document=payload, caption=item.caption)
        return True

    await message.reply_text(f"暂不支持的文件类型：{item.media_type}")
    return False


async def deliver_local_item(message: Message, item: BundleItem) -> bool:
    if not item.local_path:
        await message.reply_text("这个文件缺少本地路径。")
        return False

    file_path = Path(item.local_path)
    if not file_path.exists():
        await message.reply_text(f"文件不存在：{item.file_name or file_path.name}")
        return False

    with file_path.open("rb") as file_handle:
        if item.media_type == "photo":
            await message.reply_photo(photo=file_handle, caption=item.caption)
            return True

        if item.media_type == "video":
            await message.reply_video(video=file_handle, caption=item.caption)
            return True

        if item.media_type == "document":
            await message.reply_document(
                document=InputFile(file_handle, filename=item.file_name or file_path.name),
                caption=item.caption,
            )
            return True

    await message.reply_text(f"暂不支持的文件类型：{item.media_type}")
    return False


def extract_media(message: Message) -> BundleItemInput | None:
    if message.photo:
        largest_photo = max(message.photo, key=lambda item: item.file_size or 0)
        return BundleItemInput(
            media_type="photo",
            storage_type="telegram",
            telegram_file_id=largest_photo.file_id,
            local_path=None,
            caption=message.caption,
            file_name=None,
            mime_type=None,
        )

    if message.video:
        return BundleItemInput(
            media_type="video",
            storage_type="telegram",
            telegram_file_id=message.video.file_id,
            local_path=None,
            caption=message.caption,
            file_name=message.video.file_name,
            mime_type=message.video.mime_type,
        )

    if message.document:
        return BundleItemInput(
            media_type="document",
            storage_type="telegram",
            telegram_file_id=message.document.file_id,
            local_path=None,
            caption=message.caption,
            file_name=message.document.file_name,
            mime_type=message.document.mime_type,
        )

    return None


def create_bundle_from_inputs(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    items: list[BundleItemInput],
    uploader_id: int | None,
    uploader_name: str | None,
    source: str,
    is_permanent: bool,
    expires_at: str | None,
) -> BundleRecord:
    settings = get_settings(context)
    database = get_database(context)
    return database.create_bundle(
        items=items,
        source=source,
        uploader_id=uploader_id,
        uploader_name=uploader_name,
        is_permanent=is_permanent,
        expires_at=expires_at,
        code_length=settings.code_length,
    )


def build_bundle_created_message(
    context: ContextTypes.DEFAULT_TYPE,
    bundle: BundleRecord,
    *,
    prefix: str,
) -> str:
    state = get_state(context)
    settings = get_settings(context)

    message_lines = [
        prefix,
        f"取件码：{bundle.code}",
        f"文件数：{len(bundle.items)}",
        f"有效期：{format_expiry_label(is_permanent=bundle.is_permanent, expires_at=bundle.expires_at)}",
    ]

    deep_link = build_deep_link(state.bot_username, bundle.code)
    if deep_link:
        message_lines.append(f"分享链接：{deep_link}")

    bundle_url = build_bundle_url(settings.public_base_url, bundle.code)
    if bundle_url:
        message_lines.append(f"网页详情：{bundle_url}")

    message_lines.append("任何人把这串码发给我，都可以取回这组文件。")
    return "\n".join(message_lines)


def build_stats_message(stats: AdminStats) -> str:
    return (
        "管理员统计：\n"
        f"总取件码：{stats.total_bundles}\n"
        f"总文件数：{stats.total_items}\n"
        f"有效中的取件码：{stats.active_bundles}\n"
        f"已过期取件码：{stats.expired_bundles}\n"
        f"永久有效：{stats.permanent_bundles}\n"
        f"临时有效：{stats.temporary_bundles}\n"
        f"Telegram 上传：{stats.telegram_bundles}\n"
        f"Web 上传：{stats.web_bundles}\n"
        f"累计取件次数：{stats.total_pickups}\n"
        f"上传用户数：{stats.unique_uploaders}\n"
        f"最近 24 小时新增：{stats.recent_bundles_24h}"
    )


def get_state(context: ContextTypes.DEFAULT_TYPE) -> RuntimeState:
    return context.application.bot_data["state"]


def get_settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return get_state(context).settings


def get_database(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return get_state(context).database


def get_draft(context: ContextTypes.DEFAULT_TYPE) -> UploadDraft | None:
    draft = context.user_data.get(DRAFT_KEY)
    if isinstance(draft, UploadDraft):
        return draft
    return None


def build_application(state: RuntimeState) -> Application:
    application = (
        Application.builder()
        .token(state.settings.bot_token)
        .post_init(post_init)
        .build()
    )

    application.bot_data["state"] = state

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("new", new_handler))
    application.add_handler(CommandHandler("done", done_handler))
    application.add_handler(CommandHandler("cancel", cancel_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, media_handler)
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )

    return application


def run() -> None:
    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.init()

    state = RuntimeState(
        settings=settings,
        database=database,
    )

    web_server: ManagedWebServer | None = None
    if settings.web_enabled:
        web_server = ManagedWebServer(state)
        web_server.start()

    application = build_application(state)

    try:
        application.run_polling(drop_pending_updates=False)
    finally:
        if web_server is not None:
            web_server.stop()
        database.close()
