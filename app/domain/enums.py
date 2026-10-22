from enum import StrEnum


class TaskStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AttemptStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


ACTIVE_ATTEMPT_STATUSES = (AttemptStatus.PENDING, AttemptStatus.SENT)


class ErrorType(StrEnum):
    TECHNICAL = "technical"
    MODERATION = "moderation"
    PAYLOAD = "payload"
    TIMEOUT = "timeout"


class LateResult(StrEnum):
    ACCEPTED = "accepted"
    IGNORED = "ignored"


class LedgerReason(StrEnum):
    TOPUP = "topup"
    CHARGE = "charge"
    REFUND = "refund"
