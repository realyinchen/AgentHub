class MemoryVersionError(RuntimeError):
    """Base failure for the canonical memory version store."""


class MemoryVersionSourceError(MemoryVersionError):
    """The commit source is missing, non-user, or outside the caller scope."""


class MemoryVersionIdempotencyConflict(MemoryVersionError):
    """A receipt identifier was reused for a different canonical fact."""


class MemoryVersionTargetNotFound(MemoryVersionError):
    """A forget operation could not resolve an active chain head."""
