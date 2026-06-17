from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from orchestrator.repository.models import Base


class Correction(Base):
    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True, index=True)
    action_type = Column(String(50), nullable=False, index=True)
    original = Column(Text, nullable=False)
    corrected = Column(Text, nullable=False)
    user_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)