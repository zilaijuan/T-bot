from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from telethon.errors import InputUserDeactivatedError

from code_collector_bot.models import TaskRecord, TaskStatus
from code_collector_bot.storage import TaskRepository
from code_router_agent.channel_listener import ChannelMessageListener
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.drivers import create_auto_registered_drivers
from code_router_agent.drivers.base import Driver


LOGGER = logging.getLogger(__name__)


class CodeRouterAgent:
    def __init__(self, settings: CodeRouterAgentSettings, repository: TaskRepository | None = None) -> None:
        settings.validate()
        self.settings = settings
        self.repository = repository or TaskRepository(settings.database_path)
        self.repository.init()
        self.drivers = create_auto_registered_drivers()
        if not self.drivers:
            raise RuntimeError("No auto-registered code router drivers are enabled.")
        self._backfill_missing_codes()
        self._stop_event = asyncio.Event()

    def _backfill_missing_codes(self) -> None:
        updated_count = 0
        while True:
            tasks = self.repository.list_tasks_missing_code(limit=1000)
            if not tasks:
                break
            changed_in_batch = 0
            for task in tasks:
                driver = self._select_driver(task)
                if driver is None:
                    continue
                matched_code = driver.matched_code(task, self.settings)
                if not matched_code:
                    continue
                self.repository.update_task_code(task.task_id, matched_code)
                updated_count += 1
                changed_in_batch += 1
            if changed_in_batch == 0:
                break
        if updated_count:
            LOGGER.info("Backfilled code for %s workflow tasks.", updated_count)

    async def run_forever(self) -> None:
        driver_names = ", ".join(driver.name for driver in self.drivers)
        LOGGER.info("code_router_agent started with drivers: %s", driver_names)
        tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(self._run_router(), name="code_router_agent:router")
        ]
        if self.settings.channel_listener_enabled:
            listener = ChannelMessageListener(self.settings)
            tasks.append(
                asyncio.create_task(
                    listener.run_forever(self._stop_event),
                    name="code_router_agent:channel_listener",
                )
            )
        else:
            LOGGER.info(
                "code_router_agent channel listener is disabled. Set CODE_ROUTER_AGENT_CHANNEL_LISTENER_ENABLED=true to start it."
            )
        try:
            await self._stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            LOGGER.info("code_router_agent stopped.")

    def stop(self) -> None:
        self._stop_event.set()

    async def run_once(self) -> int:
        task = self.repository.claim_next_due_task_for_routing()
        if task is None:
            return 0
        await self._process_task(task)
        return 1

    async def _run_router(self) -> None:
        while not self._stop_event.is_set():
            processed = await self.run_once()
            sleep_seconds = self.settings.poll_interval_seconds if processed else self.settings.idle_sleep_seconds
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_seconds)
            except asyncio.TimeoutError:
                pass

    async def _process_task(self, task: TaskRecord) -> None:
        driver = self._select_driver(task)
        if driver is None:
            LOGGER.warning("Task %s did not match any enabled driver.", task.task_id)
            state_payload = _encode_state_payload(
                task=task,
                driver_name="unmatched",
                new_state={"driver": "unmatched"},
                result={"error": "No enabled driver matched this task."},
                next_action="NONE",
            )
            self.repository.update_task_state(
                task.task_id,
                status=TaskStatus.FAILED,
                state_payload=state_payload,
                next_run_at=datetime.now(timezone.utc),
                target_worker="unmatched",
            )
            return

        matched_code = driver.matched_code(task, self.settings)
        if matched_code:
            duplicate_task = self.repository.find_done_task_by_code(matched_code, exclude_task_id=task.task_id)
            if duplicate_task is not None:
                LOGGER.info(
                    "Task %s matched driver %s but duplicates DONE task %s for code %s.",
                    task.task_id,
                    driver.name,
                    duplicate_task.task_id,
                    matched_code,
                )
                state_payload = _encode_state_payload(
                    task=task,
                    driver_name=driver.name,
                    new_state={
                        "driver": driver.name,
                        "code": matched_code,
                        "duplicate_of_task_id": duplicate_task.task_id,
                    },
                    result={"message": "Duplicate code; task skipped.", "duplicate_of_task_id": duplicate_task.task_id},
                    next_action="NONE",
                )
                self.repository.update_task_state(
                    task.task_id,
                    status=TaskStatus.DUPLICATE,
                    state_payload=state_payload,
                    next_run_at=datetime.now(timezone.utc),
                    target_worker=driver.name,
                    code=matched_code,
                )
                return

        try:
            LOGGER.info("Task %s matched driver %s; executing step.", task.task_id, driver.name)
            result = await driver.step(task, self.settings)
            next_run_at = datetime.now(timezone.utc) + timedelta(seconds=max(result.delay_seconds, 0))
            state_payload = _encode_state_payload(
                task=task,
                driver_name=driver.name,
                new_state={**result.state_payload, "code": matched_code},
                result=result.result,
                next_action=str(result.next_action),
            )
            updated = self.repository.update_task_state(
                task.task_id,
                status=result.to_task_status(),
                state_payload=state_payload,
                next_run_at=next_run_at,
                target_worker=driver.name,
                code=matched_code,
            )
            LOGGER.info(
                "Task %s handled by driver %s: %s -> %s",
                task.task_id,
                driver.name,
                task.status,
                updated.status if updated else result.to_task_status(),
            )
        except Exception as exc:
            non_retryable = _is_non_retryable_driver_error(exc)
            next_status = TaskStatus.FAILED if non_retryable else TaskStatus.RETRY
            next_run_at = datetime.now(timezone.utc)
            if not non_retryable:
                next_run_at += timedelta(seconds=self.settings.idle_sleep_seconds)
            LOGGER.exception(
                "Task %s failed while running driver %s; status=%s.",
                task.task_id,
                driver.name,
                next_status,
            )
            state_payload = _encode_state_payload(
                task=task,
                driver_name=driver.name,
                new_state={**_decode_state_payload(task.state_payload), "code": matched_code},
                result={"error": str(exc), "error_type": type(exc).__name__, "non_retryable": non_retryable},
                next_action="NONE",
            )
            self.repository.update_task_state(
                task.task_id,
                status=next_status,
                state_payload=state_payload,
                next_run_at=next_run_at,
                target_worker=driver.name,
                code=matched_code,
            )

    def _select_driver(self, task: TaskRecord) -> Driver | None:
        for driver in self.drivers:
            if driver.matches(task, self.settings):
                return driver
        return None


def _is_non_retryable_driver_error(exc: Exception) -> bool:
    return isinstance(exc, InputUserDeactivatedError)

def _encode_state_payload(
    *,
    task: TaskRecord,
    driver_name: str,
    new_state: dict[str, Any],
    result: dict[str, Any],
    next_action: str,
) -> str:
    previous_state = _decode_state_payload(task.state_payload)
    payload = {
        **previous_state,
        **new_state,
        "last_execution": {
            "driver": driver_name,
            "next_action": next_action,
            "result": result,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _decode_state_payload(raw_value: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_value or "{}")
    except json.JSONDecodeError:
        return {"raw_state_payload": raw_value}
    return value if isinstance(value, dict) else {"state_payload": value}