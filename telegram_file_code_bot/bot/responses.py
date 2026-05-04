from __future__ import annotations

from telegram_file_code_bot.core.models import AdminStats, Bundle, DraftBundle
from telegram_file_code_bot.core.policy import format_expiry


def start_text() -> str:
    return (
        "发送文字、图片、视频或文件给我，我会先加入当前内容包。\n"
        "继续发送更多内容，或发送 /done 生成取件码。\n\n"
        "常用命令：\n"
        "/desc 描述文字 - 设置内容包描述\n"
        "/new 7d - 显式开始一个 7 天有效的内容包\n"
        "/done - 生成取件码\n"
        "/cancel - 放弃当前内容包"
    )


def draft_summary(draft: DraftBundle) -> str:
    description = draft.description or "无"
    return f"当前内容包：{len(draft.items)} 条内容\n描述：{description}\n有效期：{draft.expiry_spec}"


def bundle_created_text(bundle: Bundle) -> str:
    description = f"\n描述：{bundle.description}" if bundle.description else ""
    return (
        "内容包已生成。\n"
        f"取件码：{bundle.code}\n"
        f"内容数量：{len(bundle.items)}\n"
        f"有效期：{format_expiry(bundle.expires_at)}"
        f"{description}\n\n"
        "把取件码发送给机器人即可取回内容。"
    )


def bundle_info_text(bundle: Bundle) -> str:
    description = bundle.description or "无"
    return (
        f"取件码：{bundle.code}\n"
        f"状态：{bundle.status.value}\n"
        f"创建者：{bundle.owner_user_id}\n"
        f"内容数量：{len(bundle.items)}\n"
        f"领取次数：{bundle.download_count}\n"
        f"有效期：{format_expiry(bundle.expires_at)}\n"
        f"描述：{description}"
    )


def stats_text(stats: AdminStats) -> str:
    return (
        "统计信息：\n"
        f"总内容包：{stats.total_bundles}\n"
        f"有效内容包：{stats.active_bundles}\n"
        f"已删除内容包：{stats.deleted_bundles}\n"
        f"已过期内容包：{stats.expired_bundles}\n"
        f"总内容条目：{stats.total_items}\n"
        f"总领取次数：{stats.total_downloads}\n"
        f"24 小时新增：{stats.recent_bundles_24h}"
    )
