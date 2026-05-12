"""Service-wide settings loaded once at startup from ``EXTRACTION_*`` env vars.

Per docs/plan.md §4.7. ``run_config`` is required and points to the YAML file
parsed by ``config.run_config.load_run_config`` (Task 1.7). All numeric fields
are constrained; validation failures raise at boot so the service never starts
in a broken configuration. Defaults match the Mac Mini M4 / 16 GB budget in
§3.4 (two LLM lanes, 8K context, 20-job intake queue).
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="EXTRACTION_",
        env_file=".env",
        # Pin UTF-8 explicitly: pydantic-settings defaults to the locale charset
        # (None → platform-dependent), and a non-UTF-8 server locale would mis-decode
        # any non-ASCII byte in the .env file. UTF-8 is the only sensible default
        # for env files containing model names, paths, or comments.
        env_file_encoding="utf-8",
    )

    mode: Literal["development", "production"] = "production"
    port: PositiveInt = 8765
    model: str = "gemma4:e2b-it-q4_K_M"
    num_parallel: PositiveInt = 2
    num_ctx: PositiveInt = 8192
    intake_queue_size: PositiveInt = 20
    interstage_queue_size: PositiveInt = 4
    idle_shutdown_seconds: PositiveInt = 600
    max_retries: int = Field(default=1, ge=0, le=5)
    run_config: Path
