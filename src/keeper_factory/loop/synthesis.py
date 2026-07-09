from __future__ import annotations

from dataclasses import dataclass, field

from keeper_factory.config import LoadedConfig
from keeper_factory.loop.validation import ValidationCampaignResult
from keeper_factory.memory import MemoryStore, PromotionManager
from keeper_factory.schemas import (
    Confidence,
    KnowledgeDocument,
    KnowledgeScope,
    KnowledgeStatus,
    KnowledgeType,
    ValidationState,
)
from keeper_factory.schemas.knowledge import KnowledgeLineage


@dataclass
class SynthesisResult:
    promoted_ids: list[str] = field(default_factory=list)
    failure_note_ids: list[str] = field(default_factory=list)
    discarded_recipe_ids: list[str] = field(default_factory=list)


def synthesize_from_validation(
    *,
    loaded: LoadedConfig,
    memory: MemoryStore,
    campaign: ValidationCampaignResult | None,
    loop: int,
    dry_run: bool,
) -> SynthesisResult:
    manager = PromotionManager(memory)
    result = SynthesisResult()
    result.discarded_recipe_ids = manager.discard_expired_case_recipes(current_loop=loop)

    if campaign is None or not campaign.outcomes:
        return result

    recipe = memory.get(campaign.recipe_id)
    if recipe is None:
        return result

    n = len(campaign.outcomes)
    worse_rate = campaign.worse_count / n if n else 1.0
    positive = sum(1 for item in campaign.outcomes if item.score > 0)

    if worse_rate > loaded.config.promotion.worse_rate_max:
        fn_id = memory.allocate_id(KnowledgeType.FAILURE_NOTE)
        failure = KnowledgeDocument(
            id=fn_id,
            type=KnowledgeType.FAILURE_NOTE,
            status=KnowledgeStatus.CANDIDATE,
            created_loop=loop,
            updated_loop=loop,
            scope=recipe.scope,
            confidence=Confidence.LOW,
            evidence=[item.exp_id for item in campaign.outcomes],
            lineage=KnowledgeLineage(derived_from=recipe.id),
            failure_pattern=f"Validation failed for {recipe.declared_dimension}",
            avoid_rule=recipe.strategy_summary or "Avoid repeating this strategy cluster.",
            failure_tags=[],
        )
        memory.save(failure)
        manager.promote_to_candidate(fn_id, loop=loop)
        result.failure_note_ids.append(fn_id)
        recipe.status = KnowledgeStatus.DEPRECATED
        recipe.updated_loop = loop
        memory.save(recipe)
        return result

    if positive >= loaded.config.promotion.min_samples:
        pp_id = memory.allocate_id(KnowledgeType.PATTERN_PATCH)
        patch = KnowledgeDocument(
            id=pp_id,
            type=KnowledgeType.PATTERN_PATCH,
            status=KnowledgeStatus.CANDIDATE,
            created_loop=loop,
            updated_loop=loop,
            scope=recipe.scope,
            confidence=Confidence.LOW,
            evidence=[item.exp_id for item in campaign.outcomes],
            lineage=KnowledgeLineage(derived_from=recipe.id),
            principle=recipe.strategy_summary or f"Validated pattern for {recipe.declared_dimension}",
            prompt_fragment=(
                f"When improving {recipe.declared_dimension}, "
                f"reuse strategy: {recipe.strategy_summary or 'see evidence'}"
            ),
            risk_note=None,
        )
        memory.save(patch)
        manager.promote_to_candidate(pp_id, loop=loop)
        result.promoted_ids.append(pp_id)
        recipe.validation_state = ValidationState.RESOLVED
        recipe.updated_loop = loop
        memory.save(recipe)

    return result
