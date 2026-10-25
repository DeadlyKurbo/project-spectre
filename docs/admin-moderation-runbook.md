# Admin Moderation Platform Runbook

## Overview

The admin moderation platform is now split into:

- API surface: `/api/moderation/*` (FastAPI router)
- Admin SPA entrypoint: `/admin` (legacy fallback: `/admin/legacy`)
- Moderation domain storage: PostgreSQL schema in `sql/moderation_schema.sql`.
  Without a PostgreSQL URL the records are kept as one JSON document
  (`moderation/state.json`) in the site's regular storage, so they still survive
  redeploys; that fallback keeps the newest 5000 audit events.

This system supports:

- cross-surface user identity linking (website + Discord)
- case lifecycle management, for cases against a person or a Discord server
- website and Discord sanctions
- appeals workflow
- immutable audit event timeline

## Deployment Prerequisites

Set these environment variables:

- `JWT_SECRET` (required for moderation API auth)
- `MODERATION_DATABASE_URL` (preferred, falls back to `DATABASE_URL`)
- `ADMIN_MODERATION_SPA_ENABLED=1` to route `/admin` to the moderation SPA

Optional:

- `ADMIN_MODERATION_SPA_ENABLED=0` to keep `/admin` on the legacy page

## Database Migration

Apply moderation schema:

```bash
psql "$MODERATION_DATABASE_URL" -f sql/moderation_schema.sql
```

The migration contains:

- identity provider and sanction enums
- moderation subjects and linked identities
- cases, case events, sanctions, enforcement actions
- appeals and audit events
- retention/export policy defaults

## Operational Verification Checklist

1. Request a valid admin JWT (`role` = `Admin` or `Director`).
2. Create a subject via `POST /api/moderation/subjects`.
3. Link a Discord identity via `POST /api/moderation/subjects/{id}/identities`.
4. Open a case via `POST /api/moderation/cases`.
5. Apply a sanction via `POST /api/moderation/sanctions`.
6. Submit and decide an appeal via `POST/PATCH /api/moderation/appeals*`.
7. Confirm audit entries appear in `GET /api/moderation/audit-events`.
8. Open `/admin` and verify the SPA renders all tabs.

## Cases Against People and Servers

**Open a case** asks whether the case is against a person or a server, then
opens a picker:

- **A person** lists everyone who has signed in to the website with Discord
  (newest first), then tracked people who never signed in. The website records
  each Discord account when it signs in, and any already signed-in session on
  its next page load, in `system/website_users.json` in the persistent store
  (`GET /api/moderation/registered-users`). Opening a case against someone not
  tracked yet adds them under People with their Discord account linked.
- **A server** lists the servers the bot is in plus blacklisted servers
  (`GET /api/moderation/registered-servers`).

`POST /api/moderation/cases` takes `subjectType` (`person` or `server`), then
`subjectId` or `discordUserId` (+ `displayName`) for a person, or `serverId`
(+ `serverName`) for a server. Server cases and sanctions have no `subjectId`;
the PostgreSQL schema adds `subject_type`, `server_id` and `server_name` to
`moderation_cases` and `sanctions` on start-up.

## Discord Enforcement Notes

Discord actions are executed through `SpectreContext.execute_discord_moderation`.
The bridge always records an enforcement action receipt keyed by operation key.
If the executor is unavailable or a guild/member cannot be resolved, the action
is marked failed and logged for audit instead of silently dropping.

## Server Blacklist

Admins can ban a whole Discord server from the bot under **Admin console →
Server blacklist** (`/admin#servers`), by server ID and with a required reason.

- The list lives in the persistent store at `system/guild_blacklist.json`.
  The bot re-reads it every 10 seconds, so bans and lifts apply within that.
- The bot stays in a blacklisted server but stops working there. Every slash
  command, button, dropdown and form is answered with a private notice that
  the server is blacklisted, with an "Appeal the ban" link to the SPECTRE
  Discord. Nothing else in the bot sees those interactions.
- Archive and mission report menus are no longer deployed or refreshed in a
  blacklisted server, and queued deploys for it are dropped.
- The primary server (`GUILD_ID`) cannot be blacklisted.
- Lifting a blacklist restores the bot in that server right away.
- Each blacklist is recorded as a **Server blacklist** sanction and as
  `server.blacklisted` / `server.unblacklisted` audit events. Lifting the
  sanction from **Sanctions**, or approving an appeal against it, lifts the
  blacklist too.
- The blacklist document is what the bot enforces. Loading `/admin` matches the
  server sanctions to it, so servers blacklisted before blacklists were
  recorded get a sanction, and a sanction whose server is no longer listed ends.

## Rollback

If rollback is needed:

1. Set `ADMIN_MODERATION_SPA_ENABLED=0`.
2. Leave moderation API routes deployed (read-only incident analysis remains possible).
3. Keep audit/sanction data intact; do not drop moderation tables during incident rollback.
