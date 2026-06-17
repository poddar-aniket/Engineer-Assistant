from abc import ABC, abstractmethod
from orchestrator.repository.correction_repository import CorrectionRepository


class BasePersonalizationStrategy(ABC):
    @abstractmethod
    def get_context(self, action_type: str, limit: int = 5) -> str: ...


class RecencyStrategy(BasePersonalizationStrategy):
    def __init__(self, correction_repository: CorrectionRepository):
        self.correction_repository = correction_repository

    def get_context(self, action_type: str, limit: int = 5) -> str:
        corrections = self.correction_repository.get_recent_mixed(
            action_type=action_type, limit=limit
        )
        if not corrections:
            return ""

        lines = ["Past corrections to learn from:"]
        for c in corrections:
            lines.append(f"- Previously generated: {c.original!r}")
            lines.append(f"  User corrected to: {c.corrected!r}")
            if c.user_note:
                lines.append(f"  User note: {c.user_note!r}")
        return "\n".join(lines)