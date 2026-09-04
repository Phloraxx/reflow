from __future__ import annotations

from reflow.evaluation.pitch_demo import PitchDatasetConfig, PitchDemoService
from reflow.evaluation.profiles import EvaluationProfile


def test_pitch_demo_hides_truth_until_after_real_reconciliation() -> None:
    service = PitchDemoService()
    generated = service.generate(
        PitchDatasetConfig(
            settlement_count=100,
            profile=EvaluationProfile.RECONCILIATION_ADVERSARIAL,
            world_seed=402,
            observation_seed=1402,
        )
    )
    assert generated["truth_unlocked"] is False
    assert generated["evaluation"] is None
    dataset = generated["dataset"]
    assert isinstance(dataset, dict)
    assert dataset["observed_record_count"] > 100
    assert len(str(dataset["dataset_sha256"])) == 64
    assert len(str(dataset["truth_commitment_sha256"])) == 64

    events = tuple(service.run_stream())
    assert any(item["event"] == "progress" for item in events)
    assert events[-1]["event"] == "run_completed"
    assert len(service.settlements()) == 100

    evaluation = service.unlock_truth()
    reflow = evaluation["reflow"]
    assert isinstance(reflow, dict)
    assert reflow["false_auto_reconciled"] == 0
    assert reflow["auto_reconciled"] == reflow["true_auto_reconciled"]
