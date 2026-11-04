from bot.config import Settings, load_settings


def test_webhook_targets_keep_primary_first_and_remove_duplicates(monkeypatch):
    primary = "https://discord.example/primary"
    secondary = "https://discord.example/secondary"
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", primary)
    monkeypatch.setenv("DISCORD_ADDITIONAL_WEBHOOK_URLS", f" {secondary}, {primary}, ")
    monkeypatch.setenv("DISCORD_ADDITIONAL_WEBHOOKS_START_AT", "2026-09-17T08:00:00+09:00")
    monkeypatch.setenv("LLM_BASE_URL", "stub")
    monkeypatch.setenv("LLM_API_KEY", "stub")
    monkeypatch.setenv("LLM_MODEL", "stub")

    settings = load_settings()

    assert settings.discord_webhook_urls == (primary, secondary)
    assert settings.additional_webhooks_start_at.isoformat() == "2026-09-17T08:00:00+09:00"


def test_settings_without_additional_webhooks_remains_backward_compatible():
    settings = Settings("https://discord.example/primary", "stub", "stub", "stub")

    assert settings.discord_webhook_urls == ("https://discord.example/primary",)
