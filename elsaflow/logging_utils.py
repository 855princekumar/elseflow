from __future__ import annotations

from elsaflow.models import utc_now


class SessionLogger:
    def __init__(self, db, session_id: str) -> None:
        self.db = db
        self.session_id = session_id

    def info(self, message: str) -> None:
        self.db.log(self.session_id, "INFO", message, utc_now())

    def warning(self, message: str) -> None:
        self.db.log(self.session_id, "WARNING", message, utc_now())

    def error(self, message: str) -> None:
        self.db.log(self.session_id, "ERROR", message, utc_now())
