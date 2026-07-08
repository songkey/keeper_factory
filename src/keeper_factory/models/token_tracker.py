from __future__ import annotations

from dataclasses import dataclass, field

from keeper_factory.schemas.experiment import CallCounts, ExperimentCost, TokenUsageEntry


@dataclass
class TokenTracker:
    """Aggregate token usage by model_name for ledger cost records."""

    _by_model: dict[str, TokenUsageEntry] = field(default_factory=dict)
    vlm_calls: int = 0
    edit_calls: int = 0

    def record_vlm_call(self, model_name: str, usage: dict[str, int | None] | None) -> None:
        self.vlm_calls += 1
        self._merge_usage(model_name, usage)

    def record_edit_call(self, model_name: str, usage: dict[str, int | None] | None) -> None:
        self.edit_calls += 1
        self._merge_usage(model_name, usage)

    def _merge_usage(self, model_name: str, usage: dict[str, int | None] | None) -> None:
        if not usage:
            return
        entry = self._by_model.get(model_name)
        if entry is None:
            entry = TokenUsageEntry(model=model_name)
            self._by_model[model_name] = entry

        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        thinking_tokens = int(usage.get("thinking_tokens") or 0)
        cache_tokens = int(usage.get("cache_tokens") or 0)

        self._by_model[model_name] = TokenUsageEntry(
            model=model_name,
            input=entry.input + input_tokens,
            input_cached=entry.input_cached + cache_tokens,
            output=entry.output + output_tokens,
            output_thinking=entry.output_thinking + thinking_tokens,
        )

    def to_experiment_cost(self) -> ExperimentCost:
        return ExperimentCost(
            calls=CallCounts(vlm=self.vlm_calls, edit=self.edit_calls),
            tokens=sorted(self._by_model.values(), key=lambda item: item.model),
        )

    def reset(self) -> None:
        self._by_model.clear()
        self.vlm_calls = 0
        self.edit_calls = 0
