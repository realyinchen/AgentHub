class ConversationJournalError(RuntimeError):
    """Base error for authoritative conversation journal operations."""


class ConversationOwnershipError(ConversationJournalError):
    """The requested thread does not belong to the supplied user."""


class ConversationIdempotencyConflict(ConversationJournalError):
    """An idempotency key was reused with a different immutable payload."""


class ConversationLifecycleError(ConversationJournalError):
    """A terminal lifecycle event has no matching user source event."""
