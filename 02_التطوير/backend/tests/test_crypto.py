"""Tests for at-rest credential encryption (O.5)."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import crypto
from app.models.orm import Base, SSHHostORM, WinRMHostORM


def test_encrypt_roundtrip():
    ct = crypto.encrypt("s3cr3t-pw")
    assert ct != "s3cr3t-pw"
    assert crypto.decrypt(ct) == "s3cr3t-pw"


def test_encrypt_is_nondeterministic_but_decrypts():
    # Fernet embeds a random IV, so two encryptions differ yet both decrypt.
    a, b = crypto.encrypt("same"), crypto.encrypt("same")
    assert a != b
    assert crypto.decrypt(a) == crypto.decrypt(b) == "same"


def test_empty_passthrough():
    assert crypto.encrypt("") == ""
    assert crypto.decrypt("") == ""
    assert crypto.encrypt(None) is None


def test_legacy_plaintext_passthrough():
    # A value written before O.5 isn't a Fernet token -> returned unchanged.
    assert crypto.decrypt("plain-old-password") == "plain-old-password"


async def test_winrm_password_encrypted_at_rest(tmp_path):
    """The DB column holds ciphertext; the ORM hands back plaintext."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'c.db').as_posix()}", poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as s:
        s.add(WinRMHostORM(host="1.2.3.4", username="Admin", password="topsecret"))
        s.add(SSHHostORM(host="1.2.3.5", username="pi", password="lin-pw"))
        await s.commit()

    # Raw column values must not contain the plaintext.
    async with engine.connect() as conn:
        wraw = (await conn.execute(text("SELECT password FROM winrm_hosts"))).scalar_one()
        sraw = (await conn.execute(text("SELECT password FROM ssh_hosts"))).scalar_one()
    assert wraw != "topsecret" and "topsecret" not in wraw
    assert sraw != "lin-pw" and "lin-pw" not in sraw
    assert wraw.startswith("gAAAAA")  # Fernet token marker

    # The ORM transparently decrypts back to plaintext for the service layer.
    async with Session() as s:
        w = (await s.execute(select(WinRMHostORM))).scalar_one()
        assert w.password == "topsecret"

    await engine.dispose()
