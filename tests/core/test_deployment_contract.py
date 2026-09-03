from pathlib import Path

CONTROL_UNIT = Path("deploy/systemd/reflow-control-tower.service")
WEBHOOK_UNIT = Path("deploy/systemd/reflow-webhook.service")
TUNNEL_CONFIG = Path("deploy/cloudflared/config.example.yml")
CONTROL_ENV = Path("deploy/env/control-tower.env.example")
WEBHOOK_ENV = Path("deploy/env/webhook.env.example")


def _service_text(path: Path) -> str:
    text = path.read_text()
    assert "User=reflow" in text
    assert "Group=reflow" in text
    assert "WorkingDirectory=/opt/reflow/current" in text
    assert "ExecStart=/opt/reflow/current/.venv/bin/python -m uvicorn" in text
    assert "--host 127.0.0.1" in text
    assert "--proxy-headers" in text
    assert "--forwarded-allow-ips=127.0.0.1" in text
    assert "Restart=on-failure" in text
    assert "UMask=0077" in text
    assert "NoNewPrivileges=true" in text
    assert "PrivateTmp=true" in text
    assert "ProtectSystem=strict" in text
    assert "0.0.0.0" not in text
    return text


def test_systemd_services_are_separate_and_loopback_only() -> None:
    control = _service_text(CONTROL_UNIT)
    webhook = _service_text(WEBHOOK_UNIT)

    assert "EnvironmentFile=/etc/reflow/control-tower.env" in control
    assert "reflow.control_tower_api:app_from_env" in control
    assert "--port 8080" in control
    assert "reflow.webhook_api:app_from_env" not in control

    assert "EnvironmentFile=/etc/reflow/webhook.env" in webhook
    assert "reflow.webhook_api:app_from_env" in webhook
    assert "--port 8081" in webhook
    assert "reflow.control_tower_api:app_from_env" not in webhook


def test_cloudflared_example_routes_two_hostnames_and_fails_closed() -> None:
    text = TUNNEL_CONFIG.read_text()
    assert "tunnel: <TUNNEL-UUID>" in text
    assert "hostname: control.example.com" in text
    assert "service: http://127.0.0.1:8080" in text
    assert "hostname: webhooks.example.com" in text
    assert "service: http://127.0.0.1:8081" in text
    assert text.rstrip().endswith("- service: http_status:404")
    assert text.count("hostname:") == 2


def test_deployment_env_files_keep_human_and_provider_secrets_separate() -> None:
    control = CONTROL_ENV.read_text()
    webhook = WEBHOOK_ENV.read_text()

    assert "REFLOW_AUTH_MODE=cloudflare_access" in control
    assert "REFLOW_CF_ACCESS_ISSUER=" in control
    assert "REFLOW_CF_ACCESS_AUD=" in control
    assert "REFLOW_RAZORPAY_WEBHOOK_SECRET" not in control

    assert "REFLOW_RAZORPAY_WEBHOOK_MODE=enabled" in webhook
    assert "REFLOW_RAZORPAY_WEBHOOK_SECRET=" in webhook
    assert "REFLOW_RAZORPAY_WEBHOOK_PREVIOUS_SECRET=" in webhook
    assert "REFLOW_CF_ACCESS_ISSUER" not in webhook
