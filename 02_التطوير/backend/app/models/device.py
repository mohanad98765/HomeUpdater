"""
Pydantic models for devices and scan results.

In Phase 1.2 we keep devices in memory (a dict in the router).
In Phase 1.3 we'll replace this with SQLAlchemy + SQLite persistence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


DeviceType = Literal["router", "phone", "computer", "smart_tv", "iot", "unknown"]
DeviceStatus = Literal["online", "offline"]


class Device(BaseModel):
    """A single device discovered on the home network."""

    ip: str
    mac: str = ""
    hostname: str = ""
    vendor: str = ""
    device_type: DeviceType = "unknown"
    status: DeviceStatus = "online"
    first_seen: datetime
    last_seen: datetime
    notes: str = ""  # user-editable, not yet wired up

    @property
    def display_name(self) -> str:
        return self.hostname or self.vendor or self.ip


class ScanResponse(BaseModel):
    """Response payload from POST /api/devices/scan."""

    subnet: str
    devices: list[Device]
    total: int
    new: int = 0
    duration_seconds: float = Field(ge=0)
    timestamp: datetime
