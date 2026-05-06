-- Moderation domain schema for Project Spectre.
-- PostgreSQL is the source of truth for moderation workflows and audit.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'identity_provider') THEN
        CREATE TYPE identity_provider AS ENUM ('website', 'discord');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'subject_status') THEN
        CREATE TYPE subject_status AS ENUM ('active', 'restricted', 'suspended', 'banned');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sanction_target') THEN
        CREATE TYPE sanction_target AS ENUM ('website', 'discord');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sanction_type') THEN
        CREATE TYPE sanction_type AS ENUM (
            'warning',
            'note',
            'read_only',
            'quarantine',
            'timeout',
            'suspension',
            'kick',
            'ban'
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sanction_status') THEN
        CREATE TYPE sanction_status AS ENUM ('pending', 'active', 'completed', 'revoked', 'failed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'case_status') THEN
        CREATE TYPE case_status AS ENUM ('open', 'investigating', 'actioned', 'resolved', 'dismissed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'case_priority') THEN
        CREATE TYPE case_priority AS ENUM ('low', 'normal', 'high', 'critical');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'appeal_status') THEN
        CREATE TYPE appeal_status AS ENUM ('submitted', 'under_review', 'approved', 'denied', 'withdrawn');
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS moderated_subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_label TEXT NOT NULL,
    status subject_status NOT NULL DEFAULT 'active',
    risk_score INTEGER NOT NULL DEFAULT 0 CHECK (risk_score BETWEEN 0 AND 100),
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL REFERENCES moderated_subjects(id) ON DELETE CASCADE,
    provider identity_provider NOT NULL,
    provider_user_id TEXT NOT NULL,
    display_name TEXT,
    provider_username TEXT,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    linked_by TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (provider, provider_user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_subject_id
    ON user_identities(subject_id);

CREATE TABLE IF NOT EXISTS moderation_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_case_key TEXT UNIQUE,
    subject_id UUID NOT NULL REFERENCES moderated_subjects(id) ON DELETE CASCADE,
    status case_status NOT NULL DEFAULT 'open',
    priority case_priority NOT NULL DEFAULT 'normal',
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    reporter_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    assignee_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    opened_by_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    resolved_by_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_moderation_cases_subject_id
    ON moderation_cases(subject_id);
CREATE INDEX IF NOT EXISTS idx_moderation_cases_status_priority
    ON moderation_cases(status, priority);

CREATE TABLE IF NOT EXISTS case_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES moderation_cases(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_summary TEXT NOT NULL,
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_events_case_id_created_at
    ON case_events(case_id, created_at DESC);

CREATE TABLE IF NOT EXISTS sanctions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES moderation_cases(id) ON DELETE SET NULL,
    subject_id UUID NOT NULL REFERENCES moderated_subjects(id) ON DELETE CASCADE,
    target sanction_target NOT NULL,
    sanction sanction_type NOT NULL,
    status sanction_status NOT NULL DEFAULT 'pending',
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    imposed_by_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    starts_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ends_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_by_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    revoke_reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sanctions_subject_id_status
    ON sanctions(subject_id, status);
CREATE INDEX IF NOT EXISTS idx_sanctions_case_id
    ON sanctions(case_id);

CREATE TABLE IF NOT EXISTS enforcement_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sanction_id UUID NOT NULL REFERENCES sanctions(id) ON DELETE CASCADE,
    operation_key TEXT NOT NULL UNIQUE,
    provider identity_provider NOT NULL,
    provider_scope_id TEXT,
    provider_action TEXT NOT NULL,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status sanction_status NOT NULL DEFAULT 'pending',
    error_message TEXT,
    attempted_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_enforcement_actions_sanction_id
    ON enforcement_actions(sanction_id);

CREATE TABLE IF NOT EXISTS appeals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sanction_id UUID NOT NULL REFERENCES sanctions(id) ON DELETE CASCADE,
    case_id UUID REFERENCES moderation_cases(id) ON DELETE SET NULL,
    appellant_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    submitted_by_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    status appeal_status NOT NULL DEFAULT 'submitted',
    appeal_reason TEXT NOT NULL,
    moderator_notes TEXT,
    decision_summary TEXT,
    decided_by_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_appeals_sanction_id_status
    ON appeals(sanction_id, status);

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    actor_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    subject_id UUID REFERENCES moderated_subjects(id) ON DELETE SET NULL,
    case_id UUID REFERENCES moderation_cases(id) ON DELETE SET NULL,
    sanction_id UUID REFERENCES sanctions(id) ON DELETE SET NULL,
    appeal_id UUID REFERENCES appeals(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    request_id TEXT,
    ip_address TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at
    ON audit_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_subject_id
    ON audit_events(subject_id);

CREATE TABLE IF NOT EXISTS moderation_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_key TEXT NOT NULL UNIQUE,
    policy_value JSONB NOT NULL,
    updated_by_identity_id UUID REFERENCES user_identities(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO moderation_policies (policy_key, policy_value)
VALUES
    ('audit_retention_days', '{"days": 3650}'::jsonb),
    ('audit_export_roles', '{"allowedRoles": ["Director", "Admin"]}'::jsonb),
    ('appeals_sla_hours', '{"hours": 72}'::jsonb)
ON CONFLICT (policy_key) DO NOTHING;
