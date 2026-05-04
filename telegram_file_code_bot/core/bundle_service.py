from __future__ import annotations

from datetime import datetime, timezone

from telegram_file_code_bot.app.config import Settings
from telegram_file_code_bot.core.code_service import CodeService
from telegram_file_code_bot.core.models import Bundle, BundleItemInput, BundleStatus, DraftBundle
from telegram_file_code_bot.core.policy import parse_expiry_spec
from telegram_file_code_bot.storage.sqlite_repo import SQLiteBundleRepository


class BundleService:
    def __init__(self, settings: Settings, repository: SQLiteBundleRepository, code_service: CodeService) -> None:
        self.settings = settings
        self.repository = repository
        self.code_service = code_service
        self._drafts: dict[int, DraftBundle] = {}

    def has_draft(self, user_id: int) -> bool:
        return user_id in self._drafts

    def get_draft(self, user_id: int) -> DraftBundle | None:
        return self._drafts.get(user_id)

    def start_draft(self, *, user_id: int, owner_name: str | None, expiry_spec: str | None = None) -> DraftBundle:
        if user_id in self._drafts:
            raise ValueError("你已有一个未完成的内容包。发送 /done 生成取件码，发送 /cancel 放弃当前内容包。")
        spec = expiry_spec or self.settings.default_expiry
        parse_expiry_spec(spec, self.settings.default_expiry)
        draft = DraftBundle(user_id=user_id, owner_name=owner_name, description=None, expiry_spec=spec)
        self._drafts[user_id] = draft
        return draft

    def ensure_draft(self, *, user_id: int, owner_name: str | None) -> DraftBundle:
        draft = self._drafts.get(user_id)
        if draft is not None:
            return draft
        return self.start_draft(user_id=user_id, owner_name=owner_name)

    def set_description(self, *, user_id: int, owner_name: str | None, description: str) -> DraftBundle:
        draft = self.ensure_draft(user_id=user_id, owner_name=owner_name)
        draft.description = description.strip() or None
        draft.touch()
        return draft

    def add_item(self, *, user_id: int, owner_name: str | None, item: BundleItemInput) -> DraftBundle:
        draft = self.ensure_draft(user_id=user_id, owner_name=owner_name)
        next_count = len(draft.items) + 1
        if self.settings.max_items_per_bundle is not None and next_count > self.settings.max_items_per_bundle:
            raise ValueError(f"当前内容包最多允许 {self.settings.max_items_per_bundle} 条内容。")
        draft.items.append(item)
        draft.touch()
        return draft

    def cancel_draft(self, user_id: int) -> bool:
        return self._drafts.pop(user_id, None) is not None

    def finish_draft(self, user_id: int) -> Bundle:
        draft = self._drafts.get(user_id)
        if draft is None:
            raise ValueError("当前没有未完成的内容包。")
        if not draft.items:
            raise ValueError("当前内容包还没有任何内容，不能生成取件码。")
        if self.settings.max_items_per_bundle is not None and len(draft.items) > self.settings.max_items_per_bundle:
            raise ValueError(f"当前内容包最多允许 {self.settings.max_items_per_bundle} 条内容。")

        expiry_policy = parse_expiry_spec(draft.expiry_spec, self.settings.default_expiry)
        code = self.code_service.generate_code(draft.items, self.repository.code_exists)
        bundle = self.repository.create_bundle(
            code=code,
            owner_user_id=draft.user_id,
            owner_name=draft.owner_name,
            description=draft.description,
            visibility="public",
            expires_at=expiry_policy.expires_at,
            max_downloads=None,
            items=draft.items,
        )
        self._drafts.pop(user_id, None)
        return bundle

    def get_redeemable_bundle(self, code: str) -> Bundle:
        bundle = self.repository.get_bundle(code)
        if bundle is None:
            raise ValueError("没有找到这个取件码。")
        if bundle.status != BundleStatus.ACTIVE:
            raise ValueError("这个取件码已经不可用。")
        if bundle.is_expired(datetime.now(timezone.utc)):
            raise ValueError("这个取件码已经过期。")
        if bundle.is_download_exhausted():
            raise ValueError("这个取件码已经达到领取次数上限。")
        return bundle

    def record_download(self, code: str) -> None:
        self.repository.increment_download_count(code)
