from __future__ import annotations

from dataclasses import dataclass

from keeper_factory.schemas.enums import Verdict


@dataclass(frozen=True)
class PairwiseAgreement:
    result: Verdict
    bidirectional_agreed: bool
    forward: Verdict
    backward: Verdict


def reconcile_bidirectional(
    forward: Verdict,
    backward: Verdict,
) -> PairwiseAgreement:
    """Reconcile candidate-vs-reference with swapped positions (D6).

    forward: verdict for LEFT (candidate) relative to RIGHT (reference)
    backward: verdict for LEFT (reference) relative to RIGHT (candidate)
    """
    if forward == Verdict.BETTER and backward == Verdict.WORSE:
        return PairwiseAgreement(forward, True, forward, backward)
    if forward == Verdict.WORSE and backward == Verdict.BETTER:
        return PairwiseAgreement(forward, True, forward, backward)
    if forward == Verdict.SAME and backward == Verdict.SAME:
        return PairwiseAgreement(Verdict.SAME, True, forward, backward)
    return PairwiseAgreement(Verdict.SAME, False, forward, backward)
