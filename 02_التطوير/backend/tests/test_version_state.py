"""Post-upgrade detection (services/version_state).

Persist the running version each launch; on the next launch, a strictly-newer
current version means the signed installer upgraded us between runs -> one-time
"upgraded from X to Y" notice. First run, equal, and downgrade must NOT report an
upgrade, and every disk failure must be swallowed.
"""

from __future__ import annotations

import pytest

from app.services import version_state as vs


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    # Redirect the state file into a per-test temp dir.
    monkeypatch.setattr(vs, "get_data_dir", lambda: tmp_path)
    # Reset the session notice between tests.
    monkeypatch.setattr(vs, "_notice", {"upgraded": False, "previous": None, "current": None})
    return tmp_path


def test_first_run_records_without_upgrade():
    notice = vs.detect_and_record("1.4.7")
    assert notice == {"upgraded": False, "previous": None, "current": "1.4.7"}
    assert vs.read_last_seen() == "1.4.7"  # seeded for next time


def test_upgrade_is_detected():
    vs.write_last_seen("1.4.6")
    notice = vs.detect_and_record("1.4.7")
    assert notice == {"upgraded": True, "previous": "1.4.6", "current": "1.4.7"}
    assert vs.read_last_seen() == "1.4.7"  # advanced
    assert vs.get_notice() == notice


def test_equal_version_is_not_an_upgrade():
    vs.write_last_seen("1.4.7")
    notice = vs.detect_and_record("1.4.7")
    assert notice["upgraded"] is False
    assert notice["previous"] is None


def test_downgrade_is_not_an_upgrade():
    vs.write_last_seen("1.5.0")
    notice = vs.detect_and_record("1.4.7")
    assert notice["upgraded"] is False
    assert vs.read_last_seen() == "1.4.7"  # still records the now-current version


def test_multi_component_version_compare():
    vs.write_last_seen("1.4.9")
    assert vs.detect_and_record("1.4.10")["upgraded"] is True  # 10 > 9, not string compare


def test_corrupt_state_file_reads_as_first_run(_tmp_data_dir):
    (_tmp_data_dir / "version_state.json").write_text("{ not json", encoding="utf-8")
    assert vs.read_last_seen() is None
    assert vs.detect_and_record("1.4.7")["upgraded"] is False


def test_write_never_raises(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(vs.json, "dumps", boom)
    vs.write_last_seen("1.4.7")  # must not raise


def test_upgrade_notice_endpoint(client, monkeypatch):
    # The UI reads this once on load; it reflects the startup-detected notice.
    monkeypatch.setattr(vs, "_notice", {"upgraded": True, "previous": "1.4.6", "current": "1.4.7"})
    r = client.get("/api/system/upgrade-notice")
    assert r.status_code == 200
    assert r.json() == {"upgraded": True, "previous": "1.4.6", "current": "1.4.7"}
