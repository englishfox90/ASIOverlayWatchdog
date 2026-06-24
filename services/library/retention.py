"""
Image library retention policy.

Enforces two bounds together: keep at most ``retention_days`` of history, and
keep the library under ``max_size_gb`` on disk — whichever bites first. Age is
applied first (the user-facing "last N days" promise), then the size cap trims
the oldest survivors as a disk backstop for dense daytime auto-exposure runs.

Each removal deletes the file *and* its index row so the two never diverge.
"""

_BATCH = 500  # delete oldest rows in chunks when enforcing the size cap


def prune(index, store, retention_days, max_size_gb, now_epoch):
    """Prune the library to satisfy the age and size bounds.

    Args:
        index: ``LibraryIndex``.
        store: ``LibraryStore``.
        retention_days: Max age in days (<= 0 disables the age bound).
        max_size_gb: Max total size in GB (<= 0 disables the size bound).
        now_epoch: Current PC-local epoch seconds.

    Returns:
        Dict ``{"removed": int, "freed_bytes": int}``.
    """
    removed = 0
    freed = 0

    # --- Age bound ---
    if retention_days and retention_days > 0:
        cutoff = int(now_epoch - retention_days * 86400)
        old = index.rows_older_than(cutoff)
        if old:
            for _id, path, size in old:
                store.delete(path)
                freed += size or 0
            removed += index.delete_ids([r[0] for r in old])

    # --- Size bound ---
    if max_size_gb and max_size_gb > 0:
        max_bytes = int(max_size_gb * 1024 ** 3)
        total = index.total_bytes()
        while total > max_bytes:
            batch = index.oldest_rows(_BATCH)
            if not batch:
                break
            for _id, path, size in batch:
                store.delete(path)
                freed += size or 0
                total -= size or 0
                if total <= max_bytes:
                    # Trim the batch to only what we actually removed.
                    batch = batch[: batch.index((_id, path, size)) + 1]
                    break
            removed += index.delete_ids([r[0] for r in batch])

    return {"removed": removed, "freed_bytes": freed}


def reconcile_orphans(index, store):
    """Drop index rows whose backing file is gone (e.g. after a crash).

    Returns the number of stale rows removed.
    """
    stale = [rid for rid, path in index.all_rows() if not store.exists(path)]
    return index.delete_ids(stale)
