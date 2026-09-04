from pathlib import Path


def test_root_env_example_matches_runtime_environment_contract() -> None:
    values = {
        line.split("=", 1)[0]
        for line in Path(".env.example").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    assert values == {
        "OPENAI_API_KEY",
        "RAZORPAY_KEY_ID",
        "RAZORPAY_KEY_SECRET",
        "REFLOW_ADAPTER_MODEL",
        "REFLOW_AUTHZ_POLICY",
        "REFLOW_AUTH_MODE",
        "REFLOW_CF_ACCESS_AUD",
        "REFLOW_CF_ACCESS_ISSUER",
        "REFLOW_CASE_WORKFLOW_WRITES",
        "REFLOW_EVALUATION_ROOT",
        "REFLOW_FINAL_EVALUATION_SUMMARY",
        "REFLOW_INVESTIGATION_MODEL",
        "REFLOW_METRICS_TOKEN",
        "REFLOW_PG_DUMP_BIN",
        "REFLOW_PG_RESTORE_BIN",
        "REFLOW_POSTGRES_DSN",
        "REFLOW_RAZORPAY_ACCOUNT_ID",
        "REFLOW_RAZORPAY_EVIDENCE_ORIGIN",
        "REFLOW_RAZORPAY_WEBHOOK_MODE",
        "REFLOW_RAZORPAY_WEBHOOK_PREVIOUS_SECRET",
        "REFLOW_RAZORPAY_WEBHOOK_SECRET",
        "REFLOW_RESTORE_POSTGRES_DSN",
        "REFLOW_WEB_DIST",
    }
