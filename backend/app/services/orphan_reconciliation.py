"""Report possible orphaned originals; deliberately never delete objects."""
from datetime import datetime, timedelta, timezone


def inventory_candidates(storage, is_referenced, *, now=None, grace=timedelta(hours=24)):
    """Yield old inventory entries that have no committed job or cleanup reference.

    A candidate is not proof that deletion is safe: an upload may still commit.
    Propagate inventory and database errors rather than treating them as absence.
    """
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None or grace < timedelta(hours=24):
        raise ValueError("A UTC-aware timestamp and at least 24 hours grace are required")
    cutoff = timestamp - grace
    for key, modified in storage.list_originals():
        if modified.tzinfo is None or modified.utcoffset() is None:
            raise ValueError("Inventory timestamp is not timezone-aware")
        if modified < cutoff and not is_referenced(key):
            yield key, modified
