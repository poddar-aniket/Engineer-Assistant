from sqlalchemy.orm import Session
from datetime import datetime
from orchestrator.repository.correction_models import Correction


class CorrectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        action_type: str,
        original: str,
        corrected: str,
        user_note: str | None = None,
    ) -> Correction:
        correction = Correction(
            action_type=action_type,
            original=original,
            corrected=corrected,
            user_note=user_note,
            created_at=datetime.utcnow(),
        )
        self.db.add(correction)
        self.db.commit()
        self.db.refresh(correction)
        return correction

    def get_recent(self, limit: int = 5) -> list[Correction]:
        return (
            self.db.query(Correction)
            .order_by(Correction.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_recent_by_type(
        self, action_type: str, limit: int = 5
    ) -> list[Correction]:
        return (
            self.db.query(Correction)
            .filter(Correction.action_type == action_type)
            .order_by(Correction.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_recent_mixed(
        self, action_type: str, limit: int = 5
    ) -> list[Correction]:
        typed = self.get_recent_by_type(action_type, limit)
        if len(typed) >= limit:
            return typed
        needed = limit - len(typed)
        typed_ids = [c.id for c in typed]
        global_rest = (
            self.db.query(Correction)
            .filter(Correction.id.notin_(typed_ids))
            .order_by(Correction.created_at.desc())
            .limit(needed)
            .all()
        )
        return typed + global_rest