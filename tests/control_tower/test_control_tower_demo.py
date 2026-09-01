from reflow.evaluation.control_tower_demo import build_demo_bundle


def test_demo_bundle_uses_real_non_green_proof_case_and_investigation_paths() -> None:
    bundle = build_demo_bundle()
    assert bundle.proof.status.value == "pending_bank_credit"
    assert bundle.run.outcome.value == "not_ready"
    assert len(bundle.observations) == 1
    assert bundle.observations[0].financial_status.value == "pending_bank_credit"
    assert bundle.observations[0].materiality_band.value == "critical"
    assert [item.kind.value for item in bundle.dispositions] == [
        "assign_owner",
        "request_source_correction",
    ]
    assert bundle.investigation.status.value == "validated"
    assert bundle.investigation.next_action.value == "REQUEST_SOURCE"
