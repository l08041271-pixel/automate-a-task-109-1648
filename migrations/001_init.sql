-- ===========================================================================
-- MassageVIP Riyadh — initial PostgreSQL schema (Supabase compatible)
-- ---------------------------------------------------------------------------
-- GENERATED FILE — do not edit by hand.
-- Regenerate with:  python scripts/generate_schema_sql.py
-- Source of truth:  app/db/models/*.py
--
-- Apply in the Supabase SQL editor, or with:
--   psql "$DATABASE_URL" -f migrations/001_init.sql
-- ===========================================================================

BEGIN;
CREATE TABLE audit_logs (
	actor VARCHAR(200) NOT NULL, 
	actor_type VARCHAR(30) NOT NULL, 
	action VARCHAR(80) NOT NULL, 
	entity_type VARCHAR(60), 
	entity_id VARCHAR(64), 
	before JSONB, 
	after JSONB, 
	ip_address VARCHAR(64), 
	user_agent VARCHAR(300), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID NOT NULL, 
	CONSTRAINT pk_audit_logs PRIMARY KEY (id)
);
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX ix_audit_logs_entity ON audit_logs (entity_type, entity_id);

CREATE TABLE automation_runs (
	run_type VARCHAR(60) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	duration_ms INTEGER, 
	metrics JSONB, 
	recommendations JSONB, 
	error TEXT, 
	id UUID NOT NULL, 
	CONSTRAINT pk_automation_runs PRIMARY KEY (id), 
	CONSTRAINT ck_automation_runs_run_status CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED'))
);
CREATE INDEX ix_automation_runs_run_type_started_at ON automation_runs (run_type, started_at);

CREATE TABLE campaigns (
	name VARCHAR(200) NOT NULL, 
	channel VARCHAR(60), 
	source VARCHAR(40) NOT NULL, 
	utm_source VARCHAR(120), 
	utm_medium VARCHAR(120), 
	utm_campaign VARCHAR(160), 
	utm_content VARCHAR(160), 
	utm_term VARCHAR(160), 
	landing_url VARCHAR(500), 
	status VARCHAR(30) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	budget_amount NUMERIC(12, 2), 
	spend_amount NUMERIC(12, 2), 
	currency VARCHAR(3) NOT NULL, 
	notes TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_campaigns PRIMARY KEY (id), 
	CONSTRAINT uq_campaigns_utm_channel UNIQUE (utm_campaign, channel), 
	CONSTRAINT ck_campaigns_lead_source CHECK (source IN ('WEBSITE_FORM', 'LANDING_PAGE', 'WHATSAPP_INBOUND', 'SOCIAL', 'REFERRAL', 'MANUAL', 'OTHER'))
);

CREATE TABLE contacts (
	wa_id VARCHAR(32), 
	phone_e164 VARCHAR(20), 
	email VARCHAR(320), 
	display_name VARCHAR(200), 
	city VARCHAR(120), 
	locale VARCHAR(16), 
	consent_status VARCHAR(40) NOT NULL, 
	consent_source VARCHAR(120), 
	opted_out_at TIMESTAMP WITH TIME ZONE, 
	opt_out_reason VARCHAR(300), 
	first_seen_at TIMESTAMP WITH TIME ZONE, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	identity_hash VARCHAR(64), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_contacts PRIMARY KEY (id), 
	CONSTRAINT uq_contacts_wa_id UNIQUE (wa_id), 
	CONSTRAINT uq_contacts_phone_e164 UNIQUE (phone_e164), 
	CONSTRAINT uq_contacts_email UNIQUE (email), 
	CONSTRAINT ck_contacts_phone_e164_e164_format CHECK (phone_e164 IS NULL OR phone_e164 LIKE '+%%'), 
	CONSTRAINT ck_contacts_consent_status CHECK (consent_status IN ('UNKNOWN', 'GRANTED', 'DENIED', 'OPTED_OUT'))
);
CREATE INDEX ix_contacts_identity_hash ON contacts (identity_hash);

CREATE TABLE users (
	email VARCHAR(320) NOT NULL, 
	hashed_password VARCHAR(255) NOT NULL, 
	full_name VARCHAR(200), 
	role VARCHAR(40) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT uq_users_email UNIQUE (email), 
	CONSTRAINT ck_users_user_role CHECK (role IN ('OWNER', 'STAFF', 'VIEWER'))
);

CREATE TABLE leads (
	contact_id UUID, 
	campaign_id UUID, 
	source VARCHAR(40) NOT NULL, 
	source_detail VARCHAR(200), 
	name VARCHAR(200), 
	phone_e164 VARCHAR(20), 
	email VARCHAR(320), 
	wa_id VARCHAR(32), 
	initial_inquiry TEXT, 
	service_interest VARCHAR(200), 
	preferred_time_text VARCHAR(200), 
	preferred_time_at TIMESTAMP WITH TIME ZONE, 
	location_text VARCHAR(200), 
	stage VARCHAR(40) NOT NULL, 
	booking_status VARCHAR(40), 
	consent_status VARCHAR(40) NOT NULL, 
	score INTEGER, 
	classification VARCHAR(40), 
	score_explanation JSONB, 
	missing_info JSONB, 
	recommended_action TEXT, 
	scored_at TIMESTAMP WITH TIME ZONE, 
	utm_source VARCHAR(120), 
	utm_medium VARCHAR(120), 
	utm_campaign VARCHAR(160), 
	utm_content VARCHAR(160), 
	utm_term VARCHAR(160), 
	dedupe_key VARCHAR(64), 
	last_activity_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_leads PRIMARY KEY (id), 
	CONSTRAINT uq_leads_dedupe_key UNIQUE (dedupe_key), 
	CONSTRAINT ck_leads_score_range CHECK (score IS NULL OR (score >= 0 AND score <= 100)), 
	CONSTRAINT fk_leads_contact_id_contacts FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL, 
	CONSTRAINT fk_leads_campaign_id_campaigns FOREIGN KEY(campaign_id) REFERENCES campaigns (id) ON DELETE SET NULL, 
	CONSTRAINT ck_leads_lead_source CHECK (source IN ('WEBSITE_FORM', 'LANDING_PAGE', 'WHATSAPP_INBOUND', 'SOCIAL', 'REFERRAL', 'MANUAL', 'OTHER')), 
	CONSTRAINT ck_leads_pipeline_stage CHECK (stage IN ('NEW', 'CONTACTED', 'QUALIFIED', 'BOOKED', 'COMPLETED', 'LOST')), 
	CONSTRAINT ck_leads_booking_status CHECK (booking_status IN ('REQUESTED', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'NO_SHOW')), 
	CONSTRAINT ck_leads_consent_status CHECK (consent_status IN ('UNKNOWN', 'GRANTED', 'DENIED', 'OPTED_OUT')), 
	CONSTRAINT ck_leads_lead_classification CHECK (classification IN ('HOT', 'WARM', 'COLD'))
);
CREATE INDEX ix_leads_campaign_id ON leads (campaign_id);
CREATE INDEX ix_leads_classification ON leads (classification);
CREATE INDEX ix_leads_created_at ON leads (created_at);
CREATE INDEX ix_leads_phone_e164 ON leads (phone_e164);
CREATE INDEX ix_leads_source ON leads (source);
CREATE INDEX ix_leads_stage ON leads (stage);

CREATE TABLE bookings (
	lead_id UUID, 
	contact_id UUID, 
	service VARCHAR(200), 
	location_text VARCHAR(200), 
	requested_time_at TIMESTAMP WITH TIME ZONE, 
	scheduled_at TIMESTAMP WITH TIME ZONE, 
	duration_minutes INTEGER, 
	status VARCHAR(40) NOT NULL, 
	price_amount NUMERIC(12, 2), 
	currency VARCHAR(3) NOT NULL, 
	verified BOOLEAN NOT NULL, 
	verified_by VARCHAR(200), 
	verified_at TIMESTAMP WITH TIME ZONE, 
	verification_notes TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_bookings PRIMARY KEY (id), 
	CONSTRAINT ck_bookings_confirmed_requires_verification CHECK (status <> 'CONFIRMED' OR verified = true), 
	CONSTRAINT fk_bookings_lead_id_leads FOREIGN KEY(lead_id) REFERENCES leads (id) ON DELETE SET NULL, 
	CONSTRAINT fk_bookings_contact_id_contacts FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL, 
	CONSTRAINT ck_bookings_booking_status CHECK (status IN ('REQUESTED', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'NO_SHOW'))
);
CREATE INDEX ix_bookings_lead_id ON bookings (lead_id);
CREATE INDEX ix_bookings_scheduled_at ON bookings (scheduled_at);
CREATE INDEX ix_bookings_status ON bookings (status);

CREATE TABLE conversations (
	contact_id UUID, 
	lead_id UUID, 
	channel VARCHAR(30) NOT NULL, 
	wa_conversation_id VARCHAR(120), 
	status VARCHAR(40) NOT NULL, 
	assigned_to VARCHAR(200), 
	last_message_at TIMESTAMP WITH TIME ZONE, 
	message_count INTEGER NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_conversations PRIMARY KEY (id), 
	CONSTRAINT uq_conversations_channel_wa_id UNIQUE (channel, wa_conversation_id), 
	CONSTRAINT fk_conversations_contact_id_contacts FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL, 
	CONSTRAINT fk_conversations_lead_id_leads FOREIGN KEY(lead_id) REFERENCES leads (id) ON DELETE SET NULL, 
	CONSTRAINT ck_conversations_conversation_status CHECK (status IN ('OPEN', 'PENDING', 'ESCALATED', 'CLOSED'))
);
CREATE INDEX ix_conversations_contact_id ON conversations (contact_id);
CREATE INDEX ix_conversations_last_message_at ON conversations (last_message_at);

CREATE TABLE lead_events (
	lead_id UUID NOT NULL, 
	event_type VARCHAR(60) NOT NULL, 
	from_value VARCHAR(200), 
	to_value VARCHAR(200), 
	actor VARCHAR(120) NOT NULL, 
	metadata JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID NOT NULL, 
	CONSTRAINT pk_lead_events PRIMARY KEY (id), 
	CONSTRAINT fk_lead_events_lead_id_leads FOREIGN KEY(lead_id) REFERENCES leads (id) ON DELETE CASCADE
);
CREATE INDEX ix_lead_events_event_type ON lead_events (event_type);
CREATE INDEX ix_lead_events_lead_id_created_at ON lead_events (lead_id, created_at);

CREATE TABLE follow_up_jobs (
	lead_id UUID, 
	conversation_id UUID, 
	job_type VARCHAR(40) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	max_attempts INTEGER NOT NULL, 
	last_error TEXT, 
	payload JSONB, 
	idempotency_key VARCHAR(120), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_follow_up_jobs PRIMARY KEY (id), 
	CONSTRAINT uq_follow_up_jobs_idempotency_key UNIQUE (idempotency_key), 
	CONSTRAINT fk_follow_up_jobs_lead_id_leads FOREIGN KEY(lead_id) REFERENCES leads (id) ON DELETE CASCADE, 
	CONSTRAINT fk_follow_up_jobs_conversation_id_conversations FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE SET NULL, 
	CONSTRAINT ck_follow_up_jobs_job_type CHECK (job_type IN ('UNANSWERED_INQUIRY', 'INCOMPLETE_BOOKING', 'REQUESTED_LATER', 'APPOINTMENT_REMINDER', 'POST_APPOINTMENT_FEEDBACK')), 
	CONSTRAINT ck_follow_up_jobs_job_status CHECK (status IN ('SCHEDULED', 'RUNNING', 'DONE', 'CANCELLED', 'FAILED'))
);
CREATE INDEX ix_follow_up_jobs_lead_id ON follow_up_jobs (lead_id);
CREATE INDEX ix_follow_up_jobs_status_due_at ON follow_up_jobs (status, due_at);

CREATE TABLE messages (
	conversation_id UUID NOT NULL, 
	direction VARCHAR(40) NOT NULL, 
	wa_message_id VARCHAR(200), 
	msg_type VARCHAR(30) NOT NULL, 
	body TEXT, 
	status VARCHAR(40) NOT NULL, 
	is_automated BOOLEAN NOT NULL, 
	error TEXT, 
	raw_payload JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID NOT NULL, 
	CONSTRAINT pk_messages PRIMARY KEY (id), 
	CONSTRAINT uq_messages_wa_message_id UNIQUE (wa_message_id), 
	CONSTRAINT fk_messages_conversation_id_conversations FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	CONSTRAINT ck_messages_message_direction CHECK (direction IN ('INBOUND', 'OUTBOUND')), 
	CONSTRAINT ck_messages_message_status CHECK (status IN ('RECEIVED', 'DRAFTED', 'QUEUED', 'SENT', 'DELIVERED', 'READ', 'FAILED'))
);
CREATE INDEX ix_messages_conversation_id_created_at ON messages (conversation_id, created_at);
CREATE INDEX ix_messages_direction ON messages (direction);


COMMIT;
