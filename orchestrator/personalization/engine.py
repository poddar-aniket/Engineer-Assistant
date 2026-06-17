from orchestrator.personalization.strategies import BasePersonalizationStrategy


class PersonalizationEngine:
    def __init__(self, strategy: BasePersonalizationStrategy):
        self.strategy = strategy

    def get_prompt_context(self, action_type: str, limit: int = 5) -> str:
        return self.strategy.get_context(action_type=action_type, limit=limit)

    def build_personalized_prompt(
        self, base_prompt: str, action_type: str, limit: int = 5
    ) -> str:
        context = self.get_prompt_context(action_type=action_type, limit=limit)
        if not context:
            return base_prompt
        return f"{context}\n\n{base_prompt}"