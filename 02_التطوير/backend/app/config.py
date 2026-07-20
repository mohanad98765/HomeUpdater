r"""
Application configuration.

Settings are loaded with the following precedence (highest first):
  1. Environment variables
  2. Config file in %APPDATA%\HomeUpdater\config.json
  3. Defaults defined here

This follows the recommendation in WINDOWS_FUNDAMENTALS.md:
- User config goes in %APPDATA%
- Sensible defaults so the app works on first run
"""

import json
import os
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_appdata_dir() -> Path:
    """The HomeUpdater data root (DB, config, key, logs live under it).

    ``HOMEUPDATER_DATA_DIR`` overrides the location so an optional headless
    service and the interactive GUI can share ONE store instead of splitting
    across per-user profiles. (Run such a service as the SAME interactive user so
    the per-user DPAPI credential key still decrypts — a LocalSystem service would
    write to the SYSTEM profile and couldn't read the user's encrypted secrets.)
    """
    override = os.environ.get("HOMEUPDATER_DATA_DIR")
    if override:
        appdir = Path(override)
    elif os.name == "nt":  # Windows
        appdir = (
            Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "HomeUpdater"
        )
    else:  # Linux/Mac fallback
        appdir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "HomeUpdater"
    appdir.mkdir(parents=True, exist_ok=True)
    return appdir


def get_logs_dir() -> Path:
    """Get the logs directory."""
    logs = get_appdata_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs


def get_data_dir() -> Path:
    """Get the data directory (SQLite DB lives here)."""
    data = get_appdata_dir() / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data


def find_free_port(preferred: int, host: str = "127.0.0.1", span: int = 64) -> int:
    """Return ``preferred`` if it's bindable, else the next free port after it.

    Prevents the "app fails to load" failure when the default port (8000) is
    already taken by a leftover/old instance or another program — the app just
    moves to 8001, 8002, ... instead of shutting down. If the whole span is busy
    (e.g. a hostile local user squatting the range — availability-only), it logs
    and falls back to ``preferred`` so the caller's normal "backend failed to
    start" path surfaces a clear message rather than a raw bind traceback.
    """
    import socket

    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    for candidate in range(preferred, preferred + max(1, span)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            try:
                sock.bind((bind_host, candidate))
                return candidate
            except OSError:
                continue
    logger.warning(
        f"No free port in {preferred}-{preferred + span - 1}; falling back to {preferred}"
    )
    return preferred


class Settings(BaseSettings):
    """Application settings."""

    # === App identity ===
    app_name: str = "HomeUpdater"
    app_name_ar: str = "محدِّث المنزل"

    # === Build mode ===
    # 'test' = development build (visible TEST MODE banner in UI, verbose logs)
    # 'release' = v1+ build (no test banner). Override with HOMEUPDATER_BUILD_MODE=test
    # for a dev run.
    build_mode: Literal["test", "release"] = "release"

    # === Server ===
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False

    # === CORS ===
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # === Security: allowed Host headers (DNS-rebinding guard) ===
    # Any request whose Host header is not in this list is rejected. Keep this
    # to loopback only. The backend normally sees its own host (:8000) because
    # the Vite proxy rewrites Host (changeOrigin), but the :5173 variants are
    # included in case the proxy is reconfigured without changeOrigin.
    allowed_hosts: list[str] = [
        "127.0.0.1:8000",
        "localhost:8000",
        "127.0.0.1:5173",
        "localhost:5173",
        "127.0.0.1",
        "localhost",
    ]

    # === Logging ===
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_rotation_size_mb: int = 10
    log_retention_days: int = 30

    # === Database ===
    database_url: str = ""  # filled from data dir below

    # === Security ===
    # Optional passphrase for at-rest credential encryption (crypto.py). If set,
    # the Fernet key is derived from it (PBKDF2); if blank, a machine-bound key
    # file is used instead (DPAPI-wrapped on Windows). Set HOMEUPDATER_ENCRYPTION_PASSPHRASE.
    encryption_passphrase: str = ""

    # Per-launch session token (set by the launcher via HOMEUPDATER_SESSION_TOKEN).
    # When non-empty, /api/* requires header X-HomeUpdater-Token == this value, so a
    # different local user / non-browser process can't drive the elevated API. The
    # legitimate UI receives it in its launch URL. Empty (dev/tests) = not enforced.
    session_token: str = ""

    # === AI Advisor (optional) ===
    # Anthropic API key for the AI Advisor feature (app/services/advisor.py). When
    # set, the advisor uses Claude to reason over the network scan + CVEs + pending
    # updates and recommend a prioritized update plan. Empty = feature disabled (the
    # UI shows a "add your key" prompt). Set HOMEUPDATER_ANTHROPIC_API_KEY.
    anthropic_api_key: str = ""
    advisor_model: str = "claude-opus-4-8"

    # === Network scan ===
    scan_interval_minutes: int = 30
    scan_subnet: str = "auto"  # 'auto' = detect from network interface
    # 'auto'   = use nmap if its binary is on PATH, else the pure-Python scanner
    # 'python' = always use the pure-Python scanner (no nmap/Npcap needed)
    # 'nmap'   = always use nmap (requires nmap + Npcap installed)
    scan_method: Literal["auto", "python", "nmap"] = "auto"
    # Warm-start the adaptive network timeouts from disk across restarts so the
    # first scan/connect after a restart starts from the measured value, not the
    # cold guess. Purely a convenience — off just means everything starts cold.
    adaptive_timeout_persistence: bool = True

    model_config = SettingsConfigDict(
        env_prefix="HOMEUPDATER_",
        env_file=".env",
        extra="ignore",
    )

    def model_post_init(self, _context):
        if not self.database_url:
            db_path = get_data_dir() / "homeupdater.db"
            self.database_url = f"sqlite+aiosqlite:///{db_path}"


def load_settings() -> Settings:
    """Load settings, applying user config from %APPDATA% if present."""
    config_file = get_appdata_dir() / "config.json"
    overrides = {}
    if config_file.exists():
        try:
            overrides = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return Settings(**overrides)


settings = load_settings()
