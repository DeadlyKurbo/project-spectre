"""Discord moderation over the REST API, usable from any process holding the bot token.

The website and the bot run as separate processes, so the admin console cannot
reach the bot's gateway client. Bans, kicks, timeouts and warning DMs only need
the REST API, which this module calls directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote

import httpx

from .discord_bridge import DiscordModerationRequest

DISCORD_API_BASE = "https://discord.com/api/v10"
TIMEOUT_ACTIONS = {"timeout", "read_only", "quarantine"}
BAN_ACTIONS = {"ban", "suspension"}
# Discord caps member timeouts at 28 days.
MAX_TIMEOUT_SECONDS = 28 * 24 * 3600

_ERROR_HINTS = {
    10007: "That user is not a member of this server.",
    10013: "Discord does not recognise that user ID.",
    10026: "That user is not banned in this server.",
    50001: "The bot cannot see this server or member.",
    50007: "The user has DMs closed, so the warning could not be delivered.",
    50013: "The bot is missing permissions, or the member's role is higher than the bot's.",
}


class DiscordRestModerator:
    def __init__(
        self,
        token: str,
        *,
        api_base: str = DISCORD_API_BASE,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=10.0))

    async def execute(self, request: DiscordModerationRequest) -> dict[str, Any]:
        action = str(request.action or "").strip().lower()
        user_id, guild_id = _ids(request)
        if not user_id:
            return {"ok": False, "error": "No Discord account is linked to this person."}
        if action in {"warning", "note"}:
            if action == "note":
                return {"ok": True, "action": action}
            return await self._send_warning(user_id, request)
        if not guild_id:
            return {"ok": False, "error": "Choose the Discord server to apply this in."}
        reason = request.reason
        if action in TIMEOUT_ACTIONS:
            seconds = int(request.metadata.get("durationSeconds") or 0)
            seconds = max(60, min(seconds or 3600, MAX_TIMEOUT_SECONDS))
            until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            return await self._call(
                "PATCH",
                f"/guilds/{guild_id}/members/{user_id}",
                reason,
                json={"communication_disabled_until": until.isoformat()},
            )
        if action == "kick":
            return await self._call("DELETE", f"/guilds/{guild_id}/members/{user_id}", reason)
        if action in BAN_ACTIONS:
            return await self._call(
                "PUT", f"/guilds/{guild_id}/bans/{user_id}", reason, json={"delete_message_seconds": 0}
            )
        return {"ok": False, "error": f"Unsupported Discord action: {action}"}

    async def revoke(self, request: DiscordModerationRequest) -> dict[str, Any]:
        action = str(request.action or "").strip().lower()
        user_id, guild_id = _ids(request)
        if not user_id or not guild_id:
            return {"ok": False, "error": "Missing Discord user or server for this sanction."}
        if action in BAN_ACTIONS:
            return await self._call("DELETE", f"/guilds/{guild_id}/bans/{user_id}", request.reason)
        if action in TIMEOUT_ACTIONS:
            return await self._call(
                "PATCH",
                f"/guilds/{guild_id}/members/{user_id}",
                request.reason,
                json={"communication_disabled_until": None},
            )
        return {"ok": True, "action": action, "note": "Nothing to undo on Discord for this action."}

    async def _send_warning(self, user_id: str, request: DiscordModerationRequest) -> dict[str, Any]:
        channel = await self._call("POST", "/users/@me/channels", None, json={"recipient_id": user_id})
        if not channel.get("ok"):
            return channel
        channel_id = (channel.get("data") or {}).get("id")
        server = request.metadata.get("guildName") or "SPECTRE"
        content = f"**Warning from the {server} moderation team**\n{request.reason}"
        return await self._call("POST", f"/channels/{channel_id}/messages", None, json={"content": content[:2000]})

    async def _call(self, method: str, path: str, reason: str | None, *, json: Any = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bot {self._token}"}
        if reason:
            headers["X-Audit-Log-Reason"] = quote(reason[:400], safe=" ")
        try:
            async with self._client_factory() as client:
                response = await client.request(method, self._api_base + path, headers=headers, json=json)
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"Could not reach Discord: {exc.__class__.__name__}"}
        if response.status_code < 300:
            data = response.json() if response.content else {}
            return {"ok": True, "status": response.status_code, "data": data}
        return {"ok": False, "status": response.status_code, "error": _describe_error(response)}


def _ids(request: DiscordModerationRequest) -> tuple[str, str]:
    user_id = str(request.target_user_id or "").strip()
    guild_id = str(request.guild_id or "").strip()
    return (user_id if user_id.isdigit() else ""), (guild_id if guild_id.isdigit() else "")


def _describe_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = body.get("code") if isinstance(body, dict) else None
    if code in _ERROR_HINTS:
        return _ERROR_HINTS[code]
    message = body.get("message") if isinstance(body, dict) else None
    return f"Discord returned {response.status_code}" + (f": {message}" if message else "")


__all__ = ["DiscordRestModerator", "TIMEOUT_ACTIONS", "BAN_ACTIONS"]
