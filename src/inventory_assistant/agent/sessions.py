"""Short-lived, process-local browser chat sessions."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any

SESSION_TTL_SECONDS = 30 * 60
MAX_TRANSCRIPT_TURNS = 20
MAX_SESSIONS = 200
MAX_PENDING_ORDERS = 20


@dataclass(frozen=True, slots=True)
class PendingChatOrder:
    reference: str
    confirmation_token: str
    summary: str
    sku: str
    expires_at: datetime

    def public(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "summary": self.summary,
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(slots=True)
class ChatSession:
    id: str
    last_activity: float
    transcript: list[dict[str, Any]] = field(default_factory=list)
    pending_orders: dict[str, PendingChatOrder] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def prune_pending(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        expired = [
            ref for ref, pending in self.pending_orders.items() if pending.expires_at <= current
        ]
        for reference in expired:
            del self.pending_orders[reference]

    def add_turn(self, turn: dict[str, Any]) -> None:
        self.transcript.append(turn)
        del self.transcript[:-MAX_TRANSCRIPT_TURNS]


class ChatSessionRegistry:
    """Concurrency-safe owner of opaque, expiring session identifiers."""

    def __init__(self, *, monotonic=time.monotonic) -> None:
        self._monotonic = monotonic
        self._sessions: dict[str, ChatSession] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str | None) -> tuple[ChatSession, bool]:
        with self._lock:
            self._prune_locked()
            if session_id:
                session = self._sessions.get(session_id)
                if session is not None:
                    session.last_activity = self._monotonic()
                    return session, False
            if len(self._sessions) >= MAX_SESSIONS:
                oldest = min(self._sessions.values(), key=lambda item: item.last_activity)
                del self._sessions[oldest.id]
            identifier = secrets.token_urlsafe(32)
            session = ChatSession(id=identifier, last_activity=self._monotonic())
            self._sessions[identifier] = session
            return session, True

    def _prune_locked(self) -> None:
        threshold = self._monotonic() - SESSION_TTL_SECONDS
        expired = [key for key, value in self._sessions.items() if value.last_activity <= threshold]
        for key in expired:
            del self._sessions[key]
