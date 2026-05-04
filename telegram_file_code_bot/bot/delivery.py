from __future__ import annotations

from telegram import Message

from telegram_file_code_bot.core.models import Bundle, BundleItem, ContentType


async def deliver_bundle(message: Message, bundle: Bundle) -> None:
    if bundle.description:
        await message.reply_text(bundle.description)

    for item in bundle.items:
        await _deliver_item(message, item)


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
