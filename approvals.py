import asyncio

# In-memory stores — use Redis in production
pending_approvals: dict[str, asyncio.Event] = {}
approval_results: dict[str, bool] = {}

def create_approval(approval_id: str):
    """Create a new approval event waiting for admin response."""
    pending_approvals[approval_id] = asyncio.Event()

def set_approval_result(approval_id: str, approved: bool):
    """Called when admin clicks Yes/No. Wakes up the waiting request."""
    approval_results[approval_id] = approved
    event = pending_approvals.get(approval_id)
    if event:
        event.set()

async def wait_for_approval(approval_id: str, timeout: int = 300) -> bool | None:
    """Wait for admin response. Returns True/False, or None on timeout."""
    event = pending_approvals.get(approval_id)
    if not event:
        return None
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return approval_results.get(approval_id)
    except asyncio.TimeoutError:
        return None
    finally:
        # Cleanup
        pending_approvals.pop(approval_id, None)
        approval_results.pop(approval_id, None)