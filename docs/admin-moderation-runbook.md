# Admin Moderation Platform Runbook

## Overview

The admin moderation platform is now split into:

- API surface: `/api/moderation/*` (FastAPI router)
- Admin SPA entrypoint: `/admin` (legacy fallback: `/admin/legacy`)
- Moderation domain storage: PostgreSQL schema in `sql/moderation_schema.sql`

This system supports:

- cross-surface user identity linking (website + Discord)
- case lifecycle management
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

## Discord Enforcement Notes

Discord actions are executed through `SpectreContext.execute_discord_moderation`.
The bridge always records an enforcement action receipt keyed by operation key.
If the executor is unavailable or a guild/member cannot be resolved, the action
is marked failed and logged for audit instead of silently dropping.

## Rollback

If rollback is needed:

1. Set `ADMIN_MODERATION_SPA_ENABLED=0`.
2. Leave moderation API routes deployed (read-only incident analysis remains possible).
3. Keep audit/sanction data intact; do not drop moderation tables during incident rollback.
