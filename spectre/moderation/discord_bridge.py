from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

DiscordExecutor = Callable[["DiscordModerationRequest"], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class DiscordModerationRequest:
    operation_key: str
    subject_id: str
    action: str
    guild_id: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DiscordModerationReceipt:
    operation_key: str
    success: bool
    response_payload: dict[str, Any]
    error: str | None = None


class DiscordModerationBridge:
    """
    Executes moderation actions against Discord and returns idempotent receipts.

    The bridge can run with an injected executor from the running bot. Without
    an executor it returns a failed receipt, which still preserves auditability.
    """

    def __init__(self, executor: DiscordExecutor | None = None) -> None:
        self._executor = executor

    def bind_executor(self, executor: DiscordExecutor) -> None:
        self._executor = executor

    async def execute(self, request: DiscordModerationRequest) -> DiscordModerationReceipt:
        if self._executor is None:
            return DiscordModerationReceipt(
                operation_key=request.operation_key,
                success=False,
                response_payload={"ok": False, "reason": "discord-executor-unavailable"},
                error="Discord moderation executor is not configured.",
            )
        try:
            payload = await self._executor(request)
        except Exception as exc:  # pragma: no cover - runtime bridge safety
            return DiscordModerationReceipt(
                operation_key=request.operation_key,
                success=False,
                response_payload={"ok": False, "reason": "discord-executor-error"},
                error=str(exc),
            )
        return DiscordModerationReceipt(
            operation_key=request.operation_key,
            success=bool(payload.get("ok", False)),
            response_payload=payload,
            error=None if payload.get("ok", False) else str(payload.get("error") or "discord-action-failed"),
        )
