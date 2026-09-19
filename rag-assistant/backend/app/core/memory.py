import time
import uuid
import logging
from typing import Optional
from app.models.schemas import SessionState
from app.config import settings

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self):
        self.sessions: dict[str, SessionState] = {}

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        now = time.time()
        self.sessions[session_id] = SessionState(
            session_id=session_id,
            created_at=now,
            last_active=now,
            running_summary="",
            last_turn=None,
            has_uploaded_docs=False,
            total_upload_bytes=0,
            file_hashes=set(),
        )
        logger.info(f"Created session {session_id}")
        return session_id

    def get_session(self, session_id: str) -> Optional[SessionState]:
        session = self.sessions.get(session_id)
        if session:
            session.last_active = time.time()
        return session

    def delete_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Deleted session {session_id}")

    def update_conversation(self, session_id: str, question: str, answer: str):
        session = self.get_session(session_id)
        if session:
            session.last_turn = (question, answer)

    def update_summary(self, session_id: str, new_summary: str):
        session = self.get_session(session_id)
        if session:
            session.running_summary = new_summary

    def get_expired_sessions(self) -> list[str]:
        now = time.time()
        ttl_seconds = settings.SESSION_TTL_MINUTES * 60
        return [
            sid for sid, state in self.sessions.items()
            if (now - state.last_active) > ttl_seconds
        ]

    def sweep_sessions(self) -> list[str]:
        expired = self.get_expired_sessions()
        for sid in expired:
            self.delete_session(sid)
        if expired:
            logger.info(f"Swept {len(expired)} expired sessions")
        return expired

_session_manager = SessionManager()

def get_session_manager() -> SessionManager:
    return _session_manager
