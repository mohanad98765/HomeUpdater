"""Tests for automatic free-port selection (fixes 'app fails to load' when the
default port is busy)."""

from __future__ import annotations

import socket

from app import config
from app.config import find_free_port


def test_data_dir_override(monkeypatch, tmp_path):
    # HOMEUPDATER_DATA_DIR lets a service + the GUI share ONE data root.
    shared = tmp_path / "shared_store"
    monkeypatch.setenv("HOMEUPDATER_DATA_DIR", str(shared))
    root = config.get_appdata_dir()
    assert root == shared and root.exists()
    assert config.get_data_dir() == shared / "data"
    assert config.get_logs_dir() == shared / "logs"


def test_returns_preferred_when_free():
    # Grab an OS-assigned free port, release it, then confirm it's picked.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert find_free_port(free) == free


def test_skips_a_busy_port():
    # Hold a port open, then confirm find_free_port moves past it.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        busy.bind(("127.0.0.1", 0))
        taken = busy.getsockname()[1]
        busy.listen()
        chosen = find_free_port(taken, "127.0.0.1", span=20)
        assert chosen != taken
        assert taken < chosen <= taken + 20
