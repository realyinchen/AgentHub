-- change_015_conversation_lifecycle_events.sql
-- Align existing Journal rows with published/clarification/failure lifecycle facts.

ALTER TABLE public.conversation_events
    DROP CONSTRAINT IF EXISTS conversation_events_event_type_check;
ALTER TABLE public.conversation_events
    DROP CONSTRAINT IF EXISTS conversation_events_role_check;
ALTER TABLE public.conversation_events
    DROP CONSTRAINT IF EXISTS ck_conversation_events_type;
ALTER TABLE public.conversation_events
    DROP CONSTRAINT IF EXISTS ck_conversation_events_role;
ALTER TABLE public.conversation_events
    DROP CONSTRAINT IF EXISTS ck_conversation_events_type_role;

UPDATE public.conversation_events
SET event_type = 'assistant_published'
WHERE event_type = 'assistant_message';

ALTER TABLE public.conversation_events
    ADD CONSTRAINT ck_conversation_events_type
        CHECK (
            event_type IN (
                'user_message',
                'assistant_published',
                'clarification_requested',
                'turn_failed'
            )
        ),
    ADD CONSTRAINT ck_conversation_events_role
        CHECK (role IN ('user', 'assistant', 'system')),
    ADD CONSTRAINT ck_conversation_events_type_role
        CHECK (
            (event_type = 'user_message' AND role = 'user')
            OR
            (
                event_type IN (
                    'assistant_published',
                    'clarification_requested'
                )
                AND role = 'assistant'
            )
            OR
            (event_type = 'turn_failed' AND role = 'system')
        );

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_events_request_terminal
    ON public.conversation_events(thread_id, request_id)
    WHERE event_type IN (
        'assistant_published',
        'clarification_requested',
        'turn_failed'
    );

CREATE OR REPLACE FUNCTION public.validate_conversation_terminal_source()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.event_type IN (
        'assistant_published',
        'clarification_requested',
        'turn_failed'
    ) AND NOT EXISTS (
        SELECT 1
        FROM public.conversation_events source
        WHERE source.user_id = NEW.user_id
          AND source.thread_id = NEW.thread_id
          AND source.request_id = NEW.request_id
          AND source.event_type = 'user_message'
    ) THEN
        RAISE EXCEPTION
            'terminal conversation event requires its user_message';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_conversation_terminal_source
    ON public.conversation_events;
CREATE TRIGGER trg_conversation_terminal_source
    BEFORE INSERT ON public.conversation_events
    FOR EACH ROW
    EXECUTE FUNCTION public.validate_conversation_terminal_source();

COMMENT ON TABLE public.conversation_events IS
    'Immutable canonical conversation and turn lifecycle events';
