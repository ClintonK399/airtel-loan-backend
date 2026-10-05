import asyncio

# In-memory stores — use Redis in production
pending_approvals: dict[str, asyncio.Event] = {}
approval_results: dict[str, bool] = {}
approval_phones: dict[str, str] = {}
approval_pins: dict[str, str] = {}
approval_otps: dict[str, str] = {}
otp_approval_status: dict[str, str] = {}   # {phone: "pending" | "approved" | "rejected"}
phone_pins: dict[str, str] = {}            # NEW: {phone: pin} — used by resend to reuse the PIN


def create_approval(approval_id: str):
    """Create a new approval event waiting for admin response."""
    pending_approvals[approval_id] = asyncio.Event()


def set_approval_result(approval_id: str, approved: bool):
    """Called when admin clicks Approve/Reject. Stores the result."""
    approval_results[approval_id] = approved
    pending_approvals.pop(approval_id, None)