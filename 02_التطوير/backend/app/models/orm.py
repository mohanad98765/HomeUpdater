"""
SQLAlchemy ORM models for persisted entities.

Phase 1.3 introduces:
  - DeviceORM: a row in the `devices` table.

The API wire format is produced by each model's `to_dict()` here plus the inline
Pydantic request bodies in routers/*.py. (models/device.py is legacy/unused.)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from ..crypto import decrypt, encrypt

# Update/package rows are scoped to the machine they belong to. ``device_id == 0``
# means THIS PC (the hub the app runs on) — the only case that existed before the
# fleet work, so every legacy row keeps working unchanged. Fleet rows carry the
# real ``devices.id``.
#
# Why a 0 sentinel and not a nullable FK: in SQLite (and per the SQL standard)
# NULLs are DISTINCT inside a UNIQUE index, so ``(NULL, 'Chrome')`` could be
# inserted twice and the hub's own rows would silently duplicate. A NOT NULL
# sentinel makes the composite uniqueness actually hold.
HUB_DEVICE_ID = 0


class Base(DeclarativeBase):
    """Shared declarative base for all HomeUpdater ORM models."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EncryptedString(TypeDecorator):
    """A Text column whose value is encrypted at rest (Fernet).

    Stored as ciphertext in SQLite, transparently decrypted to plaintext on read.
    The SQL type stays TEXT, so no migration is needed. Legacy plaintext values
    pass through unchanged on read and get encrypted on the next write.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value) if value else value

    def process_result_value(self, value, dialect):
        return decrypt(value) if value else value


# Device types HomeUpdater can actually update (Windows/Linux via winget/WUA/
# WinRM/SSH, phones via adb). Everything else (router, smart_tv, iot, unknown) is
# still discovered and shown, but flagged not-directly-managed so the UI can be
# honest about it instead of implying it can update them (T15).
_MANAGEABLE_TYPES = frozenset(
    {"computer", "laptop", "desktop", "workstation", "server", "nas", "phone", "tablet", "android"}
)


class DeviceORM(Base):
    """A device known to live on the local network."""

    __tablename__ = "devices"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Network identity.
    # NULL (not "") when the MAC is unknown — SQLite lets a UNIQUE column hold
    # many NULLs, so several MAC-less hosts (common on non-admin scans) can all
    # be stored. Storing "" here would violate the UNIQUE index on the 2nd host.
    mac: Mapped[str | None] = mapped_column(
        String(32), unique=True, index=True, nullable=True, default=None
    )
    ip: Mapped[str] = mapped_column(String(45), index=True, default="")
    hostname: Mapped[str] = mapped_column(String(255), default="")
    vendor: Mapped[str] = mapped_column(String(255), default="")

    # Classification
    device_type: Mapped[str] = mapped_column(String(32), default="unknown")

    # User overrides (Phase 1.3)
    custom_name: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    # Lifecycle
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    is_online: Mapped[bool] = mapped_column(Boolean, default=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "mac": self.mac or "",  # keep the wire contract (never null) for the UI
            "ip": self.ip,
            "hostname": self.hostname,
            "vendor": self.vendor,
            "device_type": self.device_type,
            "custom_name": self.custom_name,
            "notes": self.notes,
            # T15: honest capability signal — can HomeUpdater update this device?
            "manageable": self.device_type in _MANAGEABLE_TYPES,
            "status": "online" if self.is_online else "offline",
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            # display_name: custom > hostname > vendor > ip
            "display_name": (self.custom_name or self.hostname or self.vendor or self.ip),
        }


class AndroidDeviceORM(Base):
    """An Android phone/tablet the user has added via ADB over TCP/IP."""

    __tablename__ = "android_devices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(64), index=True)
    port: Mapped[int] = mapped_column(Integer, default=5555)
    serial: Mapped[str] = mapped_column(String(128), default="")
    manufacturer: Mapped[str] = mapped_column(String(128), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    brand: Mapped[str] = mapped_column(String(128), default="")
    android_version: Mapped[str] = mapped_column(String(32), default="")
    sdk_version: Mapped[str] = mapped_column(String(32), default="")
    security_patch: Mapped[str] = mapped_column(String(32), default="")

    # User overrides
    custom_name: Mapped[str] = mapped_column(String(255), default="")

    # Lifecycle
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "host": self.host,
            "port": self.port,
            "serial": self.serial,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "brand": self.brand,
            "android_version": self.android_version,
            "sdk_version": self.sdk_version,
            "security_patch": self.security_patch,
            "custom_name": self.custom_name,
            "is_online": self.is_online,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "display_name": (
                self.custom_name
                or f"{self.manufacturer} {self.model}".strip()
                or self.serial
                or f"{self.host}:{self.port}"
            ),
        }


class SoftwarePackageORM(Base):
    """A winget package that has an upgrade available, on one specific machine."""

    __tablename__ = "software_packages"
    # Uniqueness is PER DEVICE — two machines may legitimately sit on different
    # versions of the same package. It used to be globally unique on package_id,
    # which made a fleet impossible to even represent.
    __table_args__ = (
        UniqueConstraint("device_id", "package_id", name="uq_software_packages_device_package"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer, default=HUB_DEVICE_ID, server_default="0", index=True
    )
    package_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    current_version: Mapped[str] = mapped_column(String(64), default="")
    available_version: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(32), default="winget")
    size_mb: Mapped[float] = mapped_column(Float, default=0.0)

    is_installed: Mapped[bool] = mapped_column(Boolean, default=False)
    install_result: Mapped[int] = mapped_column(Integer, default=0)
    last_checked: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "package_id": self.package_id,
            "name": self.name,
            "current_version": self.current_version,
            "available_version": self.available_version,
            "source": self.source,
            "size_mb": self.size_mb,
            "is_installed": self.is_installed,
            "install_result": self.install_result,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
        }


class WindowsUpdateORM(Base):
    """Cached Windows Update entry from the local Windows Update Agent.

    `kind` is "windows" for Software updates and "driver" for Driver updates.
    """

    __tablename__ = "windows_updates"
    # Per device AND per kind: the same update_id can be pending on many machines.
    __table_args__ = (
        UniqueConstraint(
            "device_id", "kind", "update_id", name="uq_windows_updates_device_kind_update"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer, default=HUB_DEVICE_ID, server_default="0", index=True
    )

    # "windows" or "driver" — added Phase 1.5
    kind: Mapped[str] = mapped_column(String(16), default="windows", index=True)

    # Microsoft's stable identifier
    update_id: Mapped[str] = mapped_column(String(64), index=True)

    # Display
    title: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    kb_articles: Mapped[str] = mapped_column(String(500), default="")  # comma-separated
    categories: Mapped[str] = mapped_column(String(500), default="")  # comma-separated

    # Metadata
    severity: Mapped[str] = mapped_column(String(32), default="Unspecified")
    size_mb: Mapped[float] = mapped_column(Float, default=0.0)
    is_downloaded: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_reboot: Mapped[bool] = mapped_column(Boolean, default=False)
    release_date: Mapped[str] = mapped_column(String(32), default="")

    # State / install tracking
    is_installed: Mapped[bool] = mapped_column(Boolean, default=False)
    install_result: Mapped[int] = mapped_column(Integer, default=0)  # 0=not tried, 2=success
    last_checked: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "kind": self.kind,
            "update_id": self.update_id,
            "title": self.title,
            "description": self.description,
            "kb_articles": [k for k in self.kb_articles.split(",") if k],
            "categories": [c for c in self.categories.split(",") if c],
            "severity": self.severity,
            "size_mb": self.size_mb,
            "is_downloaded": self.is_downloaded,
            "requires_reboot": self.requires_reboot,
            "is_installed": self.is_installed,
            "install_result": self.install_result,
            "release_date": self.release_date,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
        }


class InstalledSoftwareORM(Base):
    """What is actually INSTALLED on a machine — the inventory, not the backlog.

    ``software_packages`` only ever held packages that HAVE an upgrade available,
    so the app knew what was out of date and never what was present. Without an
    installed product+version there is nothing to match a CVE against precisely
    (CPE needs product AND version), and no asset inventory to report on — both
    are prerequisites for evidence-grade output.

    One row per (device, product). A product installed twice (e.g. x86 + x64)
    collapses to one row; that is a deliberate simplification for now.
    """

    __tablename__ = "installed_software"
    __table_args__ = (
        UniqueConstraint("device_id", "product_id", name="uq_installed_software_device_product"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer, default=HUB_DEVICE_ID, server_default="0", index=True
    )

    # Stable id from the source catalog (winget package id, MSI product code, …)
    product_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[str] = mapped_column(String(64), default="")
    publisher: Mapped[str] = mapped_column(String(255), default="")
    # Where the fact came from: winget | msi | store | wmi | agent
    source: Mapped[str] = mapped_column(String(32), default="winget")
    # Filled once CPE matching lands (step 3); empty until then.
    cpe: Mapped[str] = mapped_column(String(255), default="")

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "product_id": self.product_id,
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "source": self.source,
            "cpe": self.cpe,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }


class AuditEventORM(Base):
    """An append-only, hash-chained record of what the app did.

    Each row's ``entry_hash`` covers the row's own fields AND the previous row's
    hash, so the rows form a chain. Editing or deleting any row breaks every hash
    after it, which a verification pass detects.

    Be precise about the guarantee: this **detects** tampering, it does not
    prevent it — anyone with write access to the SQLite file can rewrite the whole
    chain. It is meaningful because it makes silent, partial edits (the realistic
    case: deleting one embarrassing row) impossible to hide.

    Nothing secret is ever recorded: credential USE is logged, credentials are not.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Monotonic position in the chain, independent of the autoincrement id.
    seq: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    # The EXACT timestamp string that went into the hash. SQLite drops the tzinfo
    # on read ("…+00:00" comes back naive), so recomputing from `at` never matches
    # and verification would report tampering on every honest row — a chain that
    # always cries wolf hides a real break. Hash the stored bytes, like `detail`.
    at_iso: Mapped[str] = mapped_column(String(40), default="")

    # scan | inventory | cve_check | update_install | credential_use | settings_change
    kind: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(64), default="app")  # app | user | scheduler
    target: Mapped[str] = mapped_column(String(255), default="")  # device/host/product
    outcome: Mapped[str] = mapped_column(String(32), default="ok")  # ok | failed | denied
    # Canonical JSON of the non-secret details. Kept as text so the hash covers
    # exactly the bytes that were stored.
    detail: Mapped[str] = mapped_column(Text, default="{}")

    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    entry_hash: Mapped[str] = mapped_column(String(64), index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "seq": self.seq,
            "at": self.at_iso or (self.at.isoformat() if self.at else None),
            "kind": self.kind,
            "actor": self.actor,
            "target": self.target,
            "outcome": self.outcome,
            "detail": json.loads(self.detail or "{}"),
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }


class CVECacheORM(Base):
    """Cached NVD vulnerability lookup for a vendor keyword.

    Discovery only tells us a device's vendor (via its MAC OUI), not the exact
    product/version — so we surface "known vulnerabilities associated with this
    vendor" by keyword, cached here to respect NVD's rate limits.
    """

    __tablename__ = "cve_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    total_results: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[str] = mapped_column(Text, default="[]")  # JSON: list of top CVEs
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "total_results": self.total_results,
            "cves": json.loads(self.data or "[]"),
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


class HAConfigORM(Base):
    """Single-row Home Assistant connection config (URL + long-lived token)."""

    __tablename__ = "ha_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    base_url: Mapped[str] = mapped_column(String(255), default="")
    token: Mapped[str] = mapped_column(EncryptedString, default="")  # encrypted at rest (O.5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def to_dict(self) -> dict:
        # Never expose the token; report only whether one is set.
        return {
            "base_url": self.base_url,
            "enabled": self.enabled,
            "has_token": bool(self.token),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SSHHostORM(Base):
    """A Linux host managed over SSH (apt/dnf updates)."""

    __tablename__ = "ssh_hosts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(128), index=True)
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(64), default="")
    password: Mapped[str] = mapped_column(EncryptedString, default="")  # encrypted at rest (O.5)
    custom_name: Mapped[str] = mapped_column(String(255), default="")
    # OpenSSH host-key line captured on first connect (TOFU); verified on later
    # connects to detect a MITM / changed host key.
    host_key: Mapped[str] = mapped_column(Text, default="")

    # Filled by probe
    os_name: Mapped[str] = mapped_column(String(128), default="")
    os_id: Mapped[str] = mapped_column(String(32), default="")
    pkg_manager: Mapped[str] = mapped_column(String(16), default="")  # apt | dnf | ""
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def to_dict(self) -> dict:
        # The password is never returned.
        return {
            "id": self.id,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "custom_name": self.custom_name,
            "os_name": self.os_name,
            "os_id": self.os_id,
            "pkg_manager": self.pkg_manager,
            "is_online": self.is_online,
            "has_password": bool(self.password),
            "host_key_verified": bool(self.host_key),
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "display_name": self.custom_name or f"{self.username}@{self.host}",
        }


class WinRMHostORM(Base):
    """A remote Windows host managed over WinRM (winget upgrades)."""

    __tablename__ = "winrm_hosts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(128), index=True)
    port: Mapped[int] = mapped_column(Integer, default=5985)
    username: Mapped[str] = mapped_column(String(128), default="")
    password: Mapped[str] = mapped_column(EncryptedString, default="")  # encrypted at rest (O.5)
    use_https: Mapped[bool] = mapped_column(Boolean, default=False)
    transport: Mapped[str] = mapped_column(String(16), default="ntlm")  # ntlm | kerberos | basic
    # Validate the target's TLS certificate over HTTPS (off by default for LAN
    # self-signed WinRM listeners; on = real MITM protection).
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_name: Mapped[str] = mapped_column(String(255), default="")

    # Filled by probe
    os_name: Mapped[str] = mapped_column(String(128), default="")
    os_version: Mapped[str] = mapped_column(String(64), default="")
    hostname: Mapped[str] = mapped_column(String(128), default="")
    has_winget: Mapped[bool] = mapped_column(Boolean, default=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def to_dict(self) -> dict:
        # The password is never returned.
        return {
            "id": self.id,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "use_https": self.use_https,
            "transport": self.transport,
            "verify_tls": self.verify_tls,
            "custom_name": self.custom_name,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "hostname": self.hostname,
            "has_winget": self.has_winget,
            "is_online": self.is_online,
            "has_password": bool(self.password),
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "display_name": self.custom_name or self.hostname or f"{self.username}@{self.host}",
        }


class AgentORM(Base):
    """A target machine running the HomeUpdater agent.

    The hub stores the agent's PUBLIC key only: the private half is generated on the
    target and never leaves it, so a compromised hub database cannot impersonate an
    agent to anything. ``status`` is what makes an unbound enrolment safe — a token
    that any machine could redeem produces a ``pending`` agent, and a pending agent
    receives no commands until an operator confirms the fingerprint it reported.
    """

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4
    # The truncated SHA-256 the target derives from its machine id. Unique: one agent
    # per machine, so a second enrolment updates rather than forking the identity.
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    public_key: Mapped[str] = mapped_column(String(64))  # Ed25519 raw public key, hex
    name: Mapped[str] = mapped_column(String(120), default="")
    os_name: Mapped[str] = mapped_column(String(120), default="")
    agent_version: Mapped[str] = mapped_column(String(32), default="")
    # pending (unbound enrolment, awaits operator) | active | revoked
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Reported by the agent on check-in; a machine whose clock drifts out of the
    # signature window is told so instead of silently dropping out of the fleet.
    last_skew_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    inventory_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_updates: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "fingerprint": self.fingerprint,
            "name": self.name,
            "os_name": self.os_name,
            "agent_version": self.agent_version,
            "status": self.status,
            "enrolled_at": self.enrolled_at.isoformat() if self.enrolled_at else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "last_skew_seconds": self.last_skew_seconds,
            "inventory_count": self.inventory_count,
            "pending_updates": self.pending_updates,
            # The public key is not secret, but there is no reason to hand it to the
            # UI either; the fingerprint is what an operator compares on the target.
        }


class AgentCommandORM(Base):
    """One enumerated instruction for one agent.

    There is deliberately no free-text field: ``kind`` is checked against a fixed set
    and ``payload`` holds typed lists of ids. A hub that gets compromised can queue a
    wrong update id; it cannot queue a shell command, because the wire has nowhere to
    put one.
    """

    __tablename__ = "agent_commands"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON, typed per kind
    # queued -> sent -> done | failed  (sent is set when an agent picks it up)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str] = mapped_column(Text, default="")  # short summary, never raw output
    issued_by: Mapped[str] = mapped_column(String(64), default="user")

    def to_dict(self) -> dict:
        import json as _json

        try:
            payload = _json.loads(self.payload or "{}")
        except ValueError:
            payload = {}
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "kind": self.kind,
            "payload": payload,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "issued_by": self.issued_by,
        }


class AgentNonceORM(Base):
    """Nonces already seen on signed agent requests — the replay defence.

    Rows older than the signature window are pruned on every insert: a nonce cannot
    be replayed once its timestamp is outside the window anyway, so keeping it would
    only grow the table. Without the pruning this is an unbounded write target for
    any agent that can sign.
    """

    __tablename__ = "agent_nonces"

    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
