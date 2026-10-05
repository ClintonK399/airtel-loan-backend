import asyncio

pending_approvals: dict[str, asyncio.Event] = {}
approval_results: dict[str, bool] = {}
approval_phones: dict[str, str] = {}
approval_pins: dict[str, str] = {}
approval_otps: dict[str, str] = {}
otp_approval_status: dict[str, str] = {}
phone_pins: dict[str, str] = {}

# NEW: Loan request approval tracking
loan_request_status: dict[str, str] = {}     # {approval_id: "pending" | "approved" | "rejected"}
loan_request_phones: dict[str, str] = {}     # {approval_id: phone}


def create_approval(approval_id: str):
    pending_approvals[approval_id] = asyncio.Event()


def set_approval_result(approval_id: str, approved: bool):
    approval_results[approval_id] = approved
    pending_approvals.pop(approval_id, None)