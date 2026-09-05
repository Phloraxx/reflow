from __future__ import annotations

import reflow.evaluation.pitch_demo as pitch_demo_module
from reflow.domain.types import EntityId
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


def test_exception_context_uses_indexed_manifest_membership(monkeypatch) -> None:
    service = PitchDemoService()
    service.generate(
        PitchDatasetConfig(
            settlement_count=100,
            profile=EvaluationProfile.RECONCILIATION_ADVERSARIAL,
            world_seed=402,
            observation_seed=1402,
        )
    )
    tuple(service.run_stream())
    pending = service.settlements(status="pending_bank_credit")[0]["settlement_id"]

    class FastProvider:
        def propose(self, context, tools):
            tools.case_snapshot()
            tools.proof_snapshot()
            source_id = context.available_source_envelope_ids[0]
            tools.source_evidence(source_id)
            return {
                "case_id": str(context.case_id),
                "observation_id": str(context.observation_id),
                "proof_version_id": str(context.proof_version_id),
                "hypothesis": "Bank delivery is incomplete and should be requested",
                "citations": [str(source_id)],
                "financial_claims": [],
                "next_action": "REQUEST_SOURCE",
                "request_source_kind": "bank",
            }

    monkeypatch.setattr(
        pitch_demo_module,
        "investigation_provider_from_environment",
        lambda: FastProvider(),
    )
    original_eq = EntityId.__eq__
    comparisons = 0

    def counting_eq(self, other):
        nonlocal comparisons
        comparisons += 1
        return original_eq(self, other)

    monkeypatch.setattr(EntityId, "__eq__", counting_eq)
    result = service.investigate_settlement(str(pending))

    assert result["status"] == "validated"
    assert result["next_action"] == "REQUEST_SOURCE"
    # The old tuple-membership scans exceeded fifty million comparisons here.
    assert comparisons < 100_000

def test_razorpay_probe_distinguishes_authenticated_empty_test_sandbox(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fetch_payments(self):
            return ()

        def fetch_settlements(self):
            return ()

        def fetch_recon(self, *, year: int, month: int):
            assert (year, month) == (2026, 9)
            return ()

    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_example")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    monkeypatch.setenv("REFLOW_RAZORPAY_ACCOUNT_ID", "acct_demo")
    monkeypatch.setenv("REFLOW_RAZORPAY_MODE", "test")
    monkeypatch.setattr(pitch_demo_module, "RazorpayAcceptanceClient", FakeClient)

    result = PitchDemoService().probe_razorpay()

    assert result["authenticated"] is True
    assert result["sandbox_state"] == "empty"
    assert result["payments"] == 0
    assert result["settlements"] == 0
    assert result["recon_rows"] == 0
    assert set(result["endpoint_checks"].values()) == {"ok"}
