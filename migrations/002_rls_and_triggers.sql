-- ===========================================================================
-- MassageVIP Riyadh — Row Level Security, triggers and grants
-- ---------------------------------------------------------------------------
-- Hand-written (not generated). Apply AFTER 001_init.sql.
--
-- IMPORTANT — how this fits together:
--   * The Python backend connects with a privileged Postgres role (the
--     Supabase *service role* / direct `postgres` user) and therefore
--     BYPASSES RLS. All authorisation for the API is enforced in FastAPI.
--   * RLS below exists as DEFENCE IN DEPTH: it stops any browser/client that
--     somehow obtained the public anon key from reading or writing CRM data.
--   * The SUPABASE SERVICE-ROLE KEY must NEVER ship to a browser or mobile app.
--
-- Resulting posture: anon = no access at all; authenticated staff = read +
-- limited write; everything else denied.
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Auto-maintain updated_at
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    t text;
    tables_with_updated_at text[] := ARRAY[
        'contacts', 'campaigns', 'leads', 'conversations', 'bookings',
        'follow_up_jobs', 'users'
    ];
BEGIN
    FOREACH t IN ARRAY tables_with_updated_at LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%1$s_updated_at ON public.%1$I', t);
        EXECUTE format(
            'CREATE TRIGGER trg_%1$s_updated_at '
            'BEFORE UPDATE ON public.%1$I '
            'FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()', t);
    END LOOP;
END;
$$;

-- ---------------------------------------------------------------------------
-- 2. Helper: current application role from the Supabase JWT
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.current_app_role()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(
        (auth.jwt() -> 'app_metadata' ->> 'app_role'),
        (auth.jwt() ->> 'role'),
        'anonymous'
    );
$$;

CREATE OR REPLACE FUNCTION public.is_staff()
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT public.current_app_role() IN ('owner', 'staff', 'service_role');
$$;

-- ---------------------------------------------------------------------------
-- 3. Enable RLS on every CRM table (deny-by-default once enabled)
-- ---------------------------------------------------------------------------
ALTER TABLE public.contacts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.campaigns       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leads           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lead_events     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bookings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.follow_up_jobs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.automation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users           ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- 4. Policies: authenticated staff may read; writes on operational tables
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t text;
    readable text[] := ARRAY[
        'contacts', 'campaigns', 'leads', 'lead_events', 'conversations',
        'messages', 'bookings', 'follow_up_jobs', 'automation_runs', 'audit_logs'
    ];
    writable text[] := ARRAY[
        'contacts', 'leads', 'lead_events', 'conversations', 'messages',
        'bookings', 'campaigns', 'follow_up_jobs'
    ];
BEGIN
    FOREACH t IN ARRAY readable LOOP
        EXECUTE format('DROP POLICY IF EXISTS %1$s_staff_read ON public.%1$I', t);
        EXECUTE format(
            'CREATE POLICY %1$s_staff_read ON public.%1$I '
            'FOR SELECT TO authenticated USING (public.is_staff())', t);
    END LOOP;

    FOREACH t IN ARRAY writable LOOP
        EXECUTE format('DROP POLICY IF EXISTS %1$s_staff_insert ON public.%1$I', t);
        EXECUTE format(
            'CREATE POLICY %1$s_staff_insert ON public.%1$I '
            'FOR INSERT TO authenticated WITH CHECK (public.is_staff())', t);

        EXECUTE format('DROP POLICY IF EXISTS %1$s_staff_update ON public.%1$I', t);
        EXECUTE format(
            'CREATE POLICY %1$s_staff_update ON public.%1$I '
            'FOR UPDATE TO authenticated USING (public.is_staff()) '
            'WITH CHECK (public.is_staff())', t);
    END LOOP;
    -- Deletion is never granted through RLS: only the service role may delete.
END;
$$;

DROP POLICY IF EXISTS users_owner_read ON public.users;
CREATE POLICY users_owner_read ON public.users
    FOR SELECT TO authenticated
    USING (public.current_app_role() = 'owner');

-- audit_logs are append-only for clients; the backend (service role) writes them.
DROP POLICY IF EXISTS audit_logs_no_client_write ON public.audit_logs;
CREATE POLICY audit_logs_no_client_write ON public.audit_logs
    FOR INSERT TO authenticated WITH CHECK (false);

-- ---------------------------------------------------------------------------
-- 5. Grants (Supabase roles)
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO anon, authenticated;

GRANT SELECT, INSERT, UPDATE ON
    public.contacts, public.campaigns, public.leads, public.lead_events,
    public.conversations, public.messages, public.bookings, public.follow_up_jobs
TO authenticated;

GRANT SELECT ON public.automation_runs, public.audit_logs TO authenticated;

-- anon (public landing pages) gets NOTHING: it must go through the API.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;

COMMIT;

