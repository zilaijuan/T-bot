from __future__ import annotations

import logging
from pathlib import Path
from threading import Thread
from uuid import uuid4

from flask import Flask, abort, redirect, render_template, request, url_for
from werkzeug.serving import make_server
from werkzeug.utils import secure_filename

from telegram_file_code_bot.database import BundleItemInput
from telegram_file_code_bot.state import RuntimeState
from telegram_file_code_bot.utils import (
    build_bundle_url,
    build_deep_link,
    format_datetime,
    format_expiry_label,
    guess_media_type,
    normalize_code,
    parse_expiry_spec,
)


LOGGER = logging.getLogger(__name__)


class ManagedWebServer:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state
        self.app = create_web_app(state)
        self.server = make_server(
            host=state.settings.web_host,
            port=state.settings.web_port,
            app=self.app,
            threaded=True,
        )
        self.thread = Thread(
            target=self.server.serve_forever,
            name="telegram-file-code-web",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()
        LOGGER.info(
            "Web upload page started at http://%s:%s",
            self.state.settings.web_host,
            self.state.settings.web_port,
        )

    def stop(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)


def create_web_app(state: RuntimeState) -> Flask:
    app = Flask(__name__, template_folder="templates")

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            default_expiry=state.settings.default_expiry_spec,
            bot_username=state.bot_username,
            error_message=None,
        )

    @app.post("/lookup")
    def lookup():
        code = normalize_code(request.form.get("code", ""))
        if code is None:
            return render_template(
                "index.html",
                default_expiry=state.settings.default_expiry_spec,
                bot_username=state.bot_username,
                error_message="请输入有效取件码。",
            ), 400

        return redirect(url_for("bundle_page", code=code))

    @app.post("/upload")
    def upload():
        files = [file for file in request.files.getlist("files") if file and file.filename]
        if not files:
            return render_template(
                "index.html",
                default_expiry=state.settings.default_expiry_spec,
                bot_username=state.bot_username,
                error_message="请至少选择一个文件。",
            ), 400

        expiry_input = request.form.get("expiry_spec", state.settings.default_expiry_spec)
        try:
            expiry_policy = parse_expiry_spec(expiry_input, state.settings.default_expiry_spec)
        except ValueError as exc:
            return render_template(
                "index.html",
                default_expiry=state.settings.default_expiry_spec,
                bot_username=state.bot_username,
                error_message=str(exc),
            ), 400

        caption = request.form.get("caption", "").strip() or None
        state.settings.upload_dir.mkdir(parents=True, exist_ok=True)

        saved_paths: list[Path] = []
        bundle_items: list[BundleItemInput] = []

        try:
            for index, uploaded_file in enumerate(files, start=1):
                original_name = secure_filename(uploaded_file.filename) or f"upload-{uuid4().hex}"
                suffix = Path(original_name).suffix
                target_path = state.settings.upload_dir / f"{uuid4().hex}{suffix}"
                uploaded_file.save(target_path)
                saved_paths.append(target_path)

                bundle_items.append(
                    BundleItemInput(
                        media_type=guess_media_type(original_name, uploaded_file.mimetype),
                        storage_type="local",
                        telegram_file_id=None,
                        local_path=str(target_path),
                        caption=caption if index == 1 else None,
                        file_name=original_name,
                        mime_type=uploaded_file.mimetype or None,
                    )
                )

            bundle = state.database.create_bundle(
                items=bundle_items,
                source="web",
                uploader_id=None,
                uploader_name="web",
                is_permanent=expiry_policy.is_permanent,
                expires_at=expiry_policy.expires_at.isoformat() if expiry_policy.expires_at else None,
                code_length=state.settings.code_length,
            )
        except Exception:
            for path in saved_paths:
                path.unlink(missing_ok=True)
            raise

        public_base = state.settings.public_base_url or request.url_root.rstrip("/")
        return render_template(
            "bundle.html",
            bundle=bundle,
            bot_username=state.bot_username,
            bundle_url=build_bundle_url(public_base, bundle.code),
            deep_link=build_deep_link(state.bot_username, bundle.code),
            expiry_label=format_expiry_label(
                is_permanent=bundle.is_permanent,
                expires_at=bundle.expires_at,
            ),
            created_label=format_datetime(bundle.created_at),
            is_expired=bundle.is_expired(),
        )

    @app.get("/c/<code>")
    def bundle_page(code: str):
        normalized_code = normalize_code(code)
        if normalized_code is None:
            abort(404)

        bundle = state.database.get_bundle(normalized_code)
        if bundle is None:
            abort(404)

        public_base = state.settings.public_base_url or request.url_root.rstrip("/")
        return render_template(
            "bundle.html",
            bundle=bundle,
            bot_username=state.bot_username,
            bundle_url=build_bundle_url(public_base, bundle.code),
            deep_link=build_deep_link(state.bot_username, bundle.code),
            expiry_label=format_expiry_label(
                is_permanent=bundle.is_permanent,
                expires_at=bundle.expires_at,
            ),
            created_label=format_datetime(bundle.created_at),
            is_expired=bundle.is_expired(),
        )

    return app
