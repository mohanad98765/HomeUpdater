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

from pydantic_settings import BaseSettings, SettingsConfigDict


def get_appdata_dir() -> Path:
    """Get the per-user AppData directory for HomeUpdater."""
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:  # Linux/Mac fallback
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    appdir = base / "HomeUpdater"
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


class Settings(BaseSettings):
    """Application settings."""

    # === App identity ===
    app_name: str = "HomeUpdater"
    app_name_ar: str = "محدِّث المنزل"

    # === Build mode ===
    # 'test' = development build (visible TEST MODE banner in UI, verbose logs)
    # 'release' = v1+ build (set this when the user signs off on v1)
    build_mode: Literal["test", "release"] = "test"

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

    # === Network scan ===
    scan_interval_minutes: int = 30
    scan_subnet: str = "auto"  # 'auto' = detect from network interface
    # 'auto'   = use nmap if its binary is on PATH, else the pure-Python scanner
    # 'python' = always use the pure-Python scanner (no nmap/Npcap needed)
    # 'nmap'   = always use nmap (requires nmap + Npcap installed)
    scan_method: Literal["auto", "python", "nmap"] = "auto"

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
