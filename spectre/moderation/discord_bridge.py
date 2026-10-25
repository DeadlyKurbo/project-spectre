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
    # Discord user ID resolved from the subject's linked identity. ``subject_id``
    # is the moderation subject's UUID and is never a Discord ID.
    target_user_id: str = ""


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

    def __init__(self, executor: DiscordExecutor | None = None, revoker: DiscordExecutor | None = None) -> None:
        self._executor = executor
        self._revoker = revoker

    def bind_executor(self, executor: DiscordExecutor) -> None:
        self._executor = executor

    def bind_revoker(self, revoker: DiscordExecutor) -> None:
        self._revoker = revoker

    @property
    def available(self) -> bool:
        return self._executor is not None

    async def revoke(self, request: DiscordModerationRequest) -> DiscordModerationReceipt:
        """Undo a ban or timeout. Same receipt semantics as :meth:`execute`."""

        return await self._run(self._revoker, request)

    async def execute(self, request: DiscordModerationRequest) -> DiscordModerationReceipt:
        return await self._run(self._executor, request)

    async def _run(
        self, executor: DiscordExecutor | None, request: DiscordModerationRequest
    ) -> DiscordModerationReceipt:
        if executor is None:
            return DiscordModerationReceipt(
                operation_key=request.operation_key,
                success=False,
                response_payload={"ok": False, "reason": "discord-executor-unavailable"},
                error="Discord moderation executor is not configured.",
            )
        try:
            payload = await executor(request)
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
