import asyncio

# In-memory stores — use Redis in production
pending_approvals: dict[str, asyncio.Event] = {}
approval_results: dict[str, bool] = {}
approval_phones: dict[str, str] = {}   # NEW: tracks phone for each approval_id


def create_approval(approval_id: str):
    """Create a new approval event waiting for admin response."""
    pending_approvals[approval_id] = asyncio.Event()


def set_approval_result(approval_id: str, approved: bool):
    """Called when admin clicks Yes/No. Stores the result."""
    approval_results[approval_id] = approved
    # Remove from pending so polling endpoint knows a decision was made
    pending_approvals.pop(approval_id, None)


async def wait_for_approval(approval_id: str, timeout: int = 300):
    """
    Optional: kept for backward compatibility.
    Not used in polling mode, but you can leave it in case you switch back.
    """
    event = pending_approvals.get(approval_id)
    if not event:
        return None
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return approval_results.get(approval_id)
    except asyncio.TimeoutError:
        return None
    finally:
        pending_approvals.pop(approval_id, None)
        approval_results.pop(approval_id, None)