import os
import json
import sqlite3
import logging
import math
import html
import hashlib
from logging.handlers import RotatingFileHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, BotCommand
from telegram.request import HTTPXRequest
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# 日志配置
file_handler = RotatingFileHandler(
    '/app/data/app.log',
    maxBytes=10 * 1024 * 1024,
    backupCount=3,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# 获取根日志记录器
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
# 清除现有的处理器，避免重复
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv('BOT_TOKEN')
ALLOWED_GROUP_IDS = os.getenv('ALLOWED_GROUP_IDS', '').split(',')
PROXY_URL = os.getenv('PROXY_URL')  # 获取代理地址


DB_PATH = '/app/data/bot_telegram_data.db'
PAGE_SIZE = 10 
search_cache = {}

TYPE_ICONS = {
    "text": "📝", "photo": "🖼️", "video": "🎥", "voice": "🎙️", "audio": "🎵", "document": "📄"
}

def get_media_value_from_raw_json(content_type, raw_json, field_name):
    if not raw_json:
        return None
    try:
        data = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return None

    if content_type == "photo":
        photos = data.get("photo") or []
        return photos[-1].get(field_name) if photos else None

    media = data.get(content_type) or {}
    if isinstance(media, dict):
        return media.get(field_name)
    return None

def prefixed_media_id(content_type, value):
    return f"{content_type}_{value}" if value else None

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS bot_contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id INTEGER,
            media_group_id TEXT,
            chat_id INTEGER,
            content_type TEXT,
            text_content TEXT,
            media_file_id TEXT UNIQUE, 
            file_unique_id TEXT,
            thumbnail_id TEXT,
            date TIMESTAMP,
            raw_json TEXT
        )
    ''')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(bot_contents)')}
    if 'file_unique_id' not in columns:
        conn.execute('ALTER TABLE bot_contents ADD COLUMN file_unique_id TEXT')

    rows = conn.execute('''
        SELECT id, content_type, raw_json
        FROM bot_contents
        WHERE file_unique_id IS NULL AND raw_json IS NOT NULL
    ''').fetchall()
    for row_id, content_type, raw_json in rows:
        file_unique_id = prefixed_media_id(
            content_type,
            get_media_value_from_raw_json(content_type, raw_json, 'file_unique_id')
        )
        if file_unique_id:
            conn.execute(
                'UPDATE bot_contents SET file_unique_id = ? WHERE id = ?',
                (file_unique_id, row_id)
            )

    conn.execute('CREATE INDEX IF NOT EXISTS idx_bot_contents_media_group_id ON bot_contents (media_group_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_bot_contents_chat_id ON bot_contents (chat_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_bot_contents_date ON bot_contents (date)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_bot_contents_chat_msg ON bot_contents (chat_id, msg_id)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_contents_file_unique_id ON bot_contents (file_unique_id) WHERE file_unique_id IS NOT NULL')
    conn.close()

# --- 自动设置 Bot 命令菜单 ---
async def post_init(application):
    """在 Bot 启动时自动设置菜单栏指令列表"""
    commands = [
        BotCommand("start", "查看详细使用说明"),
        BotCommand("list", "查看最近保存的消息列表"),
        BotCommand("search", "按关键词搜索已保存内容"),
        BotCommand("get", "获取指定 ID 的单条消息内容"),
        BotCommand("msg_group", "获取指定 ID 所属的整个媒体组(相册)")
    ]
    await application.bot.set_my_commands(commands)

# --- 指令：/start (说明书) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # if str(update.effective_chat.id) not in ALLOWED_GROUP_IDS: return
    
    help_text = (
        "🤖 <b>Telegram 消息采集助手使用说明</b>\n\n"
        "本 Bot 会自动记录此群组中所有的多媒体消息。您可以执行以下指令进行检索：\n\n"
        "🔹 <b>/list [页码]</b>\n"
        "显示最近保存的消息列表。点击下方按钮可翻页，或直接输入 <code>/list 5</code> 跳转。\n\n"
        "🔹 <b>/search &lt;关键词&gt; [页码]</b>\n"
        "按关键词搜索已保存的文本或媒体说明。\n"
        "例：<code>/search 发票 2</code>\n\n"
        "🔹 <b>/get &lt;ID&gt;</b>\n"
        "根据列表显示的 ID 获取单条消息原始内容（回显图片、视频或文字）。\n"
        "例：<code>/get 123</code>\n\n"
        "🔹 <b>/msg_group &lt;ID&gt;</b>\n"
        "如果某条记录带有 📦 图标，说明它属于一个相册。使用此命令可获取整组内容。\n"
        "例：<code>/msg_group 123</code>\n\n"
        "💡 <b>提示</b>：直接在私聊中发送消息给 Bot，若您在白名单内，也会被记录。"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')

# --- 指令：/list ---
def get_page_data(page):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM bot_contents')
    total_count = cursor.fetchone()[0]
    total_pages = math.ceil(total_count / PAGE_SIZE) if total_count > 0 else 1
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    offset = (page - 1) * PAGE_SIZE
    cursor.execute('SELECT id, content_type, text_content, media_group_id FROM bot_contents ORDER BY id DESC LIMIT ? OFFSET ?', (PAGE_SIZE, offset))
    rows = cursor.fetchall()
    conn.close()
    return rows, total_count, total_pages, page

def get_search_page_data(keyword, page):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    like_keyword = f"%{keyword}%"
    cursor.execute(
        "SELECT COUNT(*) FROM bot_contents WHERE COALESCE(text_content, '') LIKE ?",
        (like_keyword,)
    )
    total_count = cursor.fetchone()[0]
    total_pages = math.ceil(total_count / PAGE_SIZE) if total_count > 0 else 1
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    offset = (page - 1) * PAGE_SIZE
    cursor.execute(
        '''
        SELECT id, content_type, text_content, media_group_id
        FROM bot_contents
        WHERE COALESCE(text_content, '') LIKE ?
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        ''',
        (like_keyword, PAGE_SIZE, offset)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows, total_count, total_pages, page

def remember_search(keyword):
    token = hashlib.sha1(keyword.encode('utf-8')).hexdigest()[:10]
    search_cache[token] = keyword
    if len(search_cache) > 100:
        search_cache.pop(next(iter(search_cache)))
    return token

def build_keyboard(current_page, total_pages, rows=None, callback_prefix="list"):
    keyboard = []

    # if rows:
    #     for r in rows:
    #         db_id = r[0]
    #         f_type = r[1]
    #         caption = r[2]
    #         g_id = r[3]
    #         icon = TYPE_ICONS.get(f_type, "❓")
    #         txt = (caption[:16] + "..") if caption and len(caption) > 16 else (caption or "[无内容]")

    #         if g_id:
    #             label = f"{icon} 📦 /group_{db_id} | {txt}"
    #             callback_data = f"group_{db_id}"
    #         else:
    #             label = f"{icon} /get_{db_id} | {txt}"
    #             callback_data = f"get_{db_id}"

    #         keyboard.append([InlineKeyboardButton(label[:64], callback_data=callback_data)])

    nav_row = []
    if current_page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"{callback_prefix}_{current_page - 1}"))
    if current_page < total_pages: nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"{callback_prefix}_{current_page + 1}"))
    if nav_row: keyboard.append(nav_row)
    num_row = []
    start, end = max(1, current_page - 2), min(total_pages, current_page + 2)
    for i in range(start, end + 1):
        label = f"·{i}·" if i == current_page else str(i)
        num_row.append(InlineKeyboardButton(label, callback_data=f"{callback_prefix}_{i}"))
    if num_row: keyboard.append(num_row)
    return InlineKeyboardMarkup(keyboard)

def build_media_keyboard(current_page, total_pages):
    keyboard = []
    nav_row = []
    if current_page > 1: nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"list_{current_page - 1}"))
    if current_page < total_pages: nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"list_{current_page + 1}"))
    if nav_row: keyboard.append(nav_row)
    num_row = []
    start, end = max(1, current_page - 2), min(total_pages, current_page + 2)
    for i in range(start, end + 1):
        label = f"·{i}·" if i == current_page else str(i)
        num_row.append(InlineKeyboardButton(label, callback_data=f"list_{i}"))
    if num_row: keyboard.append(num_row)
    return InlineKeyboardMarkup(keyboard)

def build_list_text(rows, final_page, total_pages, title="📊 内容列表"):
    res = f"<b>{html.escape(title)} (第 {final_page}/{total_pages} 页)</b>\n" + "—"*15 + "\n"

    for r in rows:
        db_id = r[0]
        f_type = r[1]
        caption = r[2]
        g_id = r[3]

        icon = TYPE_ICONS.get(f_type, "❓")
        txt = (caption[:12] + "..") if caption and len(caption) > 12 else (caption or "[无内容]")
        txt = html.escape(txt)

        if g_id:
            click_cmd = f"/group_{db_id}"
            group_tag = "📦 "
        else:
            click_cmd = f"/get_{db_id}"
            group_tag = ""

        res += f"{icon} {group_tag}{html.escape(click_cmd)} | {txt}\n"

    return res + "—"*15 + "\n<i>点击下方按钮直接查看内容</i>"

async def list_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) not in ALLOWED_GROUP_IDS: return
    try: target_page = int(context.args[0]) if context.args else 1
    except: target_page = 1
    rows, total, total_pages, final_page = get_page_data(target_page)
    if not rows:
        await update.message.reply_text("📭 数据库目前是空的。")
        return
    res = build_list_text(rows, final_page, total_pages)
    await update.message.reply_text(res, parse_mode='HTML', reply_markup=build_keyboard(final_page, total_pages, rows))



async def list_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 从数据库获取记录
    if str(update.effective_chat.id) not in ALLOWED_GROUP_IDS: return
    try: target_page = int(context.args[0]) if context.args else 1
    except: target_page = 1
    rows, total, total_pages, final_page = get_page_data(target_page)
    
    if not rows:
        await update.message.reply_text("目前没有保存的内容。")
        return

    res = build_list_text(rows, final_page, total_pages)
    await update.message.reply_text(
        res, 
        parse_mode='HTML', 
        reply_markup=build_keyboard(final_page, total_pages, rows)
    )

async def search_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) not in ALLOWED_GROUP_IDS: return
    if not context.args:
        await update.message.reply_text("请输入关键词。用法：/search <关键词> [页码]")
        return

    target_page = 1
    keyword_parts = context.args
    if len(context.args) > 1:
        try:
            target_page = int(context.args[-1])
            keyword_parts = context.args[:-1]
        except ValueError:
            pass

    keyword = " ".join(keyword_parts).strip()
    if not keyword:
        await update.message.reply_text("请输入关键词。用法：/search <关键词> [页码]")
        return

    rows, total, total_pages, final_page = get_search_page_data(keyword, target_page)
    if not rows:
        await update.message.reply_text(f"没有找到包含「{html.escape(keyword)}」的内容。", parse_mode='HTML')
        return

    token = remember_search(keyword)
    res = build_list_text(rows, final_page, total_pages, title=f"🔎 搜索：{keyword}")
    await update.message.reply_text(
        res,
        parse_mode='HTML',
        reply_markup=build_keyboard(final_page, total_pages, rows, callback_prefix=f"search_{token}")
    )

# --- 指令：/msg_group ---
async def get_msg_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) not in ALLOWED_GROUP_IDS: return
    if not context.args:
        await update.message.reply_text("❌ 请输入 ID。用法：`/msg_group <ID>`")
        return
    target_id = context.args[0]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT media_group_id FROM bot_contents WHERE id = ?', (target_id,))
    res = cursor.fetchone()
    if not res or not res[0]:
        await update.message.reply_text("❌ 该记录不属于任何消息组。")
        conn.close()
        return
    g_id = res[0]
    cursor.execute('SELECT content_type, text_content, media_file_id, raw_json FROM bot_contents WHERE media_group_id = ?', (g_id,))
    media_rows = cursor.fetchall()
    conn.close()
    group_caption = next((row[1] for row in media_rows if row[1]), "")
    media_group = []
    for i, row in enumerate(media_rows):
        c_type, text, f_id, raw_json = row
        raw_fid = get_sendable_file_id(c_type, f_id, raw_json)
        caption = group_caption if i == 0 else ""
        if c_type == "photo" and raw_fid: media_group.append(InputMediaPhoto(media=raw_fid, caption=caption))
        elif c_type == "video" and raw_fid: media_group.append(InputMediaVideo(media=raw_fid, caption=caption))
    if media_group: await update.message.reply_media_group(media=media_group)
    else: await update.message.reply_text("⚠️ 组内无有效媒体内容。")

# --- 指令：/get ---
def get_file_id_from_raw_json(content_type, raw_json):
    return get_media_value_from_raw_json(content_type, raw_json, 'file_id')

def get_sendable_file_id(content_type, stored_file_id, raw_json=None):
    raw_file_id = get_file_id_from_raw_json(content_type, raw_json)
    if raw_file_id:
        return raw_file_id
    if not stored_file_id:
        return None
    return stored_file_id.split('_', 1)[1] if '_' in stored_file_id else stored_file_id

async def get_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) not in ALLOWED_GROUP_IDS: return
    if not context.args:
        await update.message.reply_text("❌ 请输入 ID。用法：`/get <ID>`")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT content_type, text_content, media_file_id, thumbnail_id, raw_json FROM bot_contents WHERE id = ?', (context.args[0],))
    row = cursor.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("❌ 未找到记录。")
        return
    c_type, text, f_id, thumb_id, raw_json = row
    cap = f"🆔 ID: {context.args[0]}\n📂 类型: {c_type}\n📝 内容: {text}"
    raw_fid = get_sendable_file_id(c_type, f_id, raw_json)
    try:
        if c_type == "text": await update.message.reply_text(cap)
        elif c_type == "photo": await update.message.reply_photo(photo=raw_fid, caption=cap)
        elif c_type == "video": await update.message.reply_video(video=raw_fid, caption=cap, thumbnail=thumb_id)
        else:
            method = getattr(update.message, f"reply_{c_type}")
            await method(raw_fid, caption=cap)
    except Exception as e: await update.message.reply_text(f"⚠️ 回显失败: {e}")

# --- 回调按钮与消息保存 (逻辑保持不变) ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[1])
    rows, total, total_pages, final_page = get_page_data(page)
    res = build_list_text(rows, final_page, total_pages)
    await query.edit_message_text(res, parse_mode='HTML', reply_markup=build_keyboard(final_page, total_pages, rows))

async def search_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, token, page_text = query.data.split("_", 2)
    keyword = search_cache.get(token)
    if not keyword:
        await query.edit_message_text("搜索上下文已失效，请重新发送 /search 命令。")
        return

    page = int(page_text)
    rows, total, total_pages, final_page = get_search_page_data(keyword, page)
    if not rows:
        await query.edit_message_text(f"没有找到包含「{html.escape(keyword)}」的内容。", parse_mode='HTML')
        return

    res = build_list_text(rows, final_page, total_pages, title=f"🔎 搜索：{keyword}")
    await query.edit_message_text(
        res,
        parse_mode='HTML',
        reply_markup=build_keyboard(final_page, total_pages, rows, callback_prefix=f"search_{token}")
    )

caption_cache = {}
async def handle_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"收到消息！来自 Chat ID: {update.effective_chat.id}")
    msg = update.effective_message
    if not msg or str(update.effective_chat.id) not in ALLOWED_GROUP_IDS: return
    c_type = "text"; m_obj = None; thumb_id = None
    if msg.photo: c_type = "photo"; m_obj = msg.photo[-1]; thumb_id = msg.photo[0].file_id 
    elif msg.video: c_type = "video"; m_obj = msg.video; thumb_id = msg.video.thumbnail.file_id if msg.video.thumbnail else None
    elif msg.voice: c_type = "voice"; m_obj = msg.voice
    elif msg.audio: c_type = "audio"; m_obj = msg.audio
    elif msg.document: c_type = "document"; m_obj = msg.document; thumb_id = msg.document.thumbnail.file_id if msg.document.thumbnail else None
    txt = msg.caption or msg.text or ""
    if msg.media_group_id:
        if txt: caption_cache[msg.media_group_id] = txt
        else: txt = caption_cache.get(msg.media_group_id, "")
        if len(caption_cache) > 50: caption_cache.pop(next(iter(caption_cache)))
    media_file_id = prefixed_media_id(c_type, m_obj.file_id) if m_obj else None
    file_unique_id = prefixed_media_id(c_type, m_obj.file_unique_id) if m_obj else None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('INSERT OR IGNORE INTO bot_contents (msg_id, media_group_id, chat_id, content_type, text_content, media_file_id, file_unique_id, thumbnail_id, date, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (msg.message_id, msg.media_group_id, update.effective_chat.id, c_type, txt, media_file_id, file_unique_id, thumb_id, msg.date.isoformat(), json.dumps(msg.to_dict(), default=str)))
            if msg.media_group_id and txt:
                conn.execute(
                    '''
                    UPDATE bot_contents
                    SET text_content = ?
                    WHERE media_group_id = ?
                      AND (text_content IS NULL OR text_content = '')
                    ''',
                    (txt, msg.media_group_id)
                )
    except Exception:
        logging.exception("保存消息失败")

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # 必须调用，否则按钮会一直转圈
    
    data = query.data
    
    if data.startswith("get_"):
        media_id = data.split("_", 1)[1]
        # 这里调用你原来的 get 逻辑
        await send_single_media(query.message, media_id)
        
    elif data.startswith("group_"):
        db_id = data.split("_", 1)[1]
        await send_media_group_by_db_id(query.message, db_id)

async def send_single_media(message, db_id):
    """发送单个媒体文件"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, content_type, text_content, media_file_id, thumbnail_id, raw_json FROM bot_contents WHERE id = ?",
        (db_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        await message.reply_text("未找到该记录。")
        return

    f_type = row['content_type']
    f_id = get_sendable_file_id(f_type, row['media_file_id'], row['raw_json'])
    caption = f"🆔 ID: {row['id']}\n📂 类型: {f_type}\n📝 内容: {row['text_content'] or ''}"

    try:
        if f_type == "text":
            await message.reply_text(caption)
        elif f_type == "photo" and f_id:
            await message.reply_photo(photo=f_id, caption=caption)
        elif f_type == "video" and f_id:
            await message.reply_video(video=f_id, caption=caption, thumbnail=row['thumbnail_id'])
        elif f_id and hasattr(message, f"reply_{f_type}"):
            method = getattr(message, f"reply_{f_type}")
            await method(f_id, caption=caption)
        else:
            await message.reply_text("不支持的消息类型，或记录中没有可回发的 file_id。")
    except Exception as e:
        logging.exception("回显单条消息失败，ID=%s", db_id)
        await message.reply_text(f"⚠️ 回显失败: {e}")

async def send_media_group(message, group_id):
    """发送整个媒体组内容"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT content_type, text_content, media_file_id, raw_json FROM bot_contents WHERE media_group_id = ? ORDER BY id ASC",
        (group_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await message.reply_text("未找到该媒体组记录。")
        return

    group_caption = next((row['text_content'] for row in rows if row['text_content']), "")
    media_list = []
    for i, row in enumerate(rows):
        f_id = get_sendable_file_id(row['content_type'], row['media_file_id'], row['raw_json'])
        caption = group_caption if i == 0 else ""
        if row['content_type'] == "photo" and f_id:
            media_list.append(InputMediaPhoto(media=f_id, caption=caption))
        elif row['content_type'] == "video" and f_id:
            media_list.append(InputMediaVideo(media=f_id, caption=caption))

    if media_list:
        await message.reply_media_group(media=media_list)
    else:
        await message.reply_text("该组内无有效媒体。")

async def send_media_group_by_db_id(message, db_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT media_group_id FROM bot_contents WHERE id = ?', (db_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        await message.reply_text("该记录不属于任何媒体组。")
        return

    await send_media_group(message, row[0])

# 定义一个超简单的测试 Handler
async def debug_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.effective_message.text
    logging.info(f"🚨 [监控] 收到任何内容! ChatID: {chat_id}, UserID: {user_id}, Text: {text}")

# --- 处理点击单条 ID ---
async def handle_click_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd_text = update.message.text # 例如 "/get_102"
    db_id = cmd_text.split('_', 1)[1]
    # 调用你之前定义的发送单文件函数
    await send_single_media(update.message, db_id)

# --- 处理点击媒体组 ---
async def handle_click_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd_text = update.message.text # 例如 "/group_102"
    db_id = cmd_text.split('_', 1)[1]
    await send_media_group_by_db_id(update.message, db_id)
    
if __name__ == '__main__':
    init_db()
    # 使用 post_init 来初始化菜单
    builder = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init)
    if PROXY_URL:
        logging.info(f"检测到代理配置: {PROXY_URL}")
        # 对于 python-telegram-bot v20.x+，直接在 builder 中传入即可
        builder.proxy(PROXY_URL)
        builder.get_updates_proxy(PROXY_URL)

        # proxy_settings = HTTPXRequest(proxy_url=PROXY_URL)
        # builder.request(proxy_settings)       
    app = builder.build()

    # 将这个监控放在最前面，且不加任何权限过滤
    app.add_handler(MessageHandler(filters.ALL, debug_monitor), group=-1)

    app.add_handler(CommandHandler("start", start))
    # app.add_handler(CommandHandler("list", list_msgs))
    app.add_handler(CommandHandler("list", list_media))
    app.add_handler(CommandHandler("search", search_msgs))
    app.add_handler(CommandHandler("get", get_msg))
    app.add_handler(CommandHandler("msg_group", get_msg_group))
    app.add_handler(MessageHandler(filters.Regex(r'^/get_\d+$'), handle_click_get))
    app.add_handler(MessageHandler(filters.Regex(r'^/group_\d+$'), handle_click_group))
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r'^list_\d+$'))
    app.add_handler(CallbackQueryHandler(search_button_handler, pattern=r'^search_[0-9a-f]{10}_\d+$'))
    # 注册回调处理器
    app.add_handler(CallbackQueryHandler(button_callback_handler, pattern=r'^(get|group)_.+'))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_save))
    app.run_polling()
