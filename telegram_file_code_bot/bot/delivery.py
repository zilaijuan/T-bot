from __future__ import annotations

from math import ceil

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message

from telegram_file_code_bot.core.models import Bundle, BundleItem, ContentType

PAGE_CALLBACK_PREFIX = "fcp"
PAGE_NEIGHBOR_COUNT = 2


async def deliver_bundle(message: Message, bundle: Bundle) -> None:
    if bundle.description:
        await message.reply_text(bundle.description)

    for item in bundle.items:
        await _deliver_item(message, item)


async def deliver_bundle_page(
    message: Message,
    bundle: Bundle,
    *,
    page: int,
    page_size: int,
    token: str,
) -> None:
    total_pages = max(1, ceil(len(bundle.items) / page_size))
    page = min(max(page, 1), total_pages)

    if page == 1 and bundle.description:
        await message.reply_text(bundle.description)

    start = (page - 1) * page_size
    end = start + page_size
    for item in bundle.items[start:end]:
        await _deliver_item(message, item)

    await message.reply_text(
        f"第 {page}/{total_pages} 页，共 {len(bundle.items)} 条内容。",
        reply_markup=build_page_keyboard(token=token, current_page=page, total_pages=total_pages),
    )


def build_page_keyboard(*, token: str, current_page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None

    rows: list[list[InlineKeyboardButton]] = []
    nav_row: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav_row.append(_page_button("上一页", token, current_page - 1))
    if current_page < total_pages:
        nav_row.append(_page_button("下一页", token, current_page + 1))
    if nav_row:
        rows.append(nav_row)

    start = max(1, current_page - PAGE_NEIGHBOR_COUNT)
    end = min(total_pages, current_page + PAGE_NEIGHBOR_COUNT)
    page_row = [
        _page_button(f"·{page}·" if page == current_page else str(page), token, page)
        for page in range(start, end + 1)
    ]
    if page_row:
        rows.append(page_row)

    return InlineKeyboardMarkup(rows)


def _page_button(label: str, token: str, page: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=f"{PAGE_CALLBACK_PREFIX}:{token}:{page}")


async def _deliver_item(message: Message, item: BundleItem) -> None:
    caption = item.caption
    if item.type == ContentType.TEXT:
        await message.reply_text(item.text or "")
    elif item.type == ContentType.PHOTO and item.telegram_file_id:
        await message.reply_photo(photo=item.telegram_file_id, caption=caption)
    elif item.type == ContentType.VIDEO and item.telegram_file_id:
        await message.reply_video(video=item.telegram_file_id, caption=caption)
    elif item.type == ContentType.DOCUMENT and item.telegram_file_id:
        await message.reply_document(document=item.telegram_file_id, caption=caption)
    elif item.type == ContentType.AUDIO and item.telegram_file_id:
        await message.reply_audio(audio=item.telegram_file_id, caption=caption)
    elif item.type == ContentType.VOICE and item.telegram_file_id:
        await message.reply_voice(voice=item.telegram_file_id, caption=caption)
    else:
        await message.reply_text("有一条内容暂时无法发送。")
