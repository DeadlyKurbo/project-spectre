from __future__ import annotations

import asyncio

from spectre.moderation.discord_bridge import DiscordModerationBridge, DiscordModerationRequest


def test_discord_bridge_handles_missing_executor():
    bridge = DiscordModerationBridge()
    receipt = asyncio.run(
        bridge.execute(
            DiscordModerationRequest(
                operation_key="op-1",
                subject_id="123",
                action="ban",
                guild_id="456",
                reason="rule violation",
            )
        )
    )
    assert receipt.success is False
    assert receipt.error is not None


def test_discord_bridge_returns_executor_payload():
    async def fake_executor(request: DiscordModerationRequest):
        assert request.action == "timeout"
        return {"ok": True, "operationKey": request.operation_key}

    bridge = DiscordModerationBridge(executor=fake_executor)
    receipt = asyncio.run(
        bridge.execute(
            DiscordModerationRequest(
                operation_key="op-2",
                subject_id="123",
                action="timeout",
                guild_id="456",
                reason="spam",
            )
        )
    )
    assert receipt.success is True
    assert receipt.response_payload["operationKey"] == "op-2"
