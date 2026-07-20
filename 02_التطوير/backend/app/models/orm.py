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

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from ..crypto import decrypt, encrypt


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
    """A winget package that has an upgrade available."""

    __tablename__ = "software_packages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
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

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # "windows" or "driver" — added Phase 1.5
    kind: Mapped[str] = mapped_column(String(16), default="windows", index=True)

    # Microsoft's stable identifier
    update_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

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
