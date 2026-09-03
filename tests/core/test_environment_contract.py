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
        "REFLOW_EVALUATION_ROOT",
        "REFLOW_FINAL_EVALUATION_SUMMARY",
        "REFLOW_INVESTIGATION_MODEL",
        "REFLOW_POSTGRES_DSN",
        "REFLOW_RAZORPAY_ACCOUNT_ID",
        "REFLOW_WEB_DIST",
    }
