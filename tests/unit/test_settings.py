"""Unit tests for the Settings class (Task 1.6).

Settings is constructed once at service startup (docs/plan.md §4.7) and read by
every later phase via dependency injection. Validation failures must crash the
service at boot, not at first request — tests assert that missing required
values raise immediately and that field constraints are enforced.

All tests pass ``_env_file=None`` to disable .env discovery so they don't pick
up a developer's local .env file. The ``isolated_env`` fixture clears all
EXTRACTION_* env vars at test entry so each test starts from a clean slate.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from extraction_service.settings import Settings

_EXTRACTION_ENV_VARS = (
    "EXTRACTION_MODE",
    "EXTRACTION_PORT",
    "EXTRACTION_MODEL",
    "EXTRACTION_NUM_PARALLEL",
    "EXTRACTION_NUM_CTX",
    "EXTRACTION_INTAKE_QUEUE_SIZE",
    "EXTRACTION_INTERSTAGE_QUEUE_SIZE",
    "EXTRACTION_IDLE_SHUTDOWN_SECONDS",
    "EXTRACTION_MAX_RETRIES",
    "EXTRACTION_RUN_CONFIG",
)


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for var in _EXTRACTION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _set_run_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cfg = tmp_path / "run.yaml"
    cfg.write_text("placeholder: true\n")
    monkeypatch.setenv("EXTRACTION_RUN_CONFIG", str(cfg))
    return cfg


def test_settings_raises_when_run_config_env_var_missing(
    isolated_env: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_loads_documented_defaults_when_only_run_config_set(
    isolated_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = _set_run_config(isolated_env, tmp_path)

    settings = Settings(_env_file=None)

    assert settings.mode == "production"
    assert settings.port == 8765
    assert settings.model == "gemma4:e2b-it-q4_K_M"
    assert settings.num_parallel == 2
    assert settings.num_ctx == 8192
    assert settings.intake_queue_size == 20
    assert settings.interstage_queue_size == 4
    assert settings.idle_shutdown_seconds == 600
    assert settings.max_retries == 1
    assert settings.run_config == cfg


def test_settings_overrides_via_extraction_prefixed_env_vars(
    isolated_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_run_config(isolated_env, tmp_path)
    isolated_env.setenv("EXTRACTION_MODE", "development")
    isolated_env.setenv("EXTRACTION_PORT", "9000")
    isolated_env.setenv("EXTRACTION_NUM_CTX", "16384")

    settings = Settings(_env_file=None)

    assert settings.mode == "development"
    assert settings.port == 9000
    assert settings.num_ctx == 16384


def test_settings_rejects_invalid_mode(isolated_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_run_config(isolated_env, tmp_path)
    isolated_env.setenv("EXTRACTION_MODE", "staging")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_rejects_max_retries_above_five(
    isolated_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_run_config(isolated_env, tmp_path)
    isolated_env.setenv("EXTRACTION_MAX_RETRIES", "10")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_rejects_negative_max_retries(
    isolated_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_run_config(isolated_env, tmp_path)
    isolated_env.setenv("EXTRACTION_MAX_RETRIES", "-1")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_rejects_non_positive_port(
    isolated_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_run_config(isolated_env, tmp_path)
    isolated_env.setenv("EXTRACTION_PORT", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
