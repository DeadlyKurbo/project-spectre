"""Persistent fleet manifest for the owner portal."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Tuple

from storage_spaces import read_json, write_json

FLEET_MANIFEST_KEY = "owner/fleet-manifest.json"


@dataclass(slots=True)
class FleetVessel:
    """Describes a single vessel entry in the fleet manifest."""

    vessel_id: str
    name: str
    vessel_type: str = ""
    armaments: str = ""
    speed: str = ""
    assignment: str = ""
    registry_id: str = ""
    shipyard: str = ""
    commission_date: str = ""
    assigned_squadron: str = ""
    clearance_level: str = ""
    status: str = ""
    vessel_motto: str | None = None
    notes: str | None = None

    def copy(self) -> "FleetVessel":
        return FleetVessel(
            vessel_id=self.vessel_id,
            name=self.name,
            vessel_type=self.vessel_type,
            armaments=self.armaments,
            speed=self.speed,
            assignment=self.assignment,
            registry_id=self.registry_id,
            shipyard=self.shipyard,
            commission_date=self.commission_date,
            assigned_squadron=self.assigned_squadron,
            clearance_level=self.clearance_level,
            status=self.status,
            vessel_motto=self.vessel_motto,
            notes=self.notes,
        )

    def to_payload(self) -> dict[str, str]:
        payload: dict[str, str] = {
            "vessel_id": self.vessel_id,
            "name": self.name,
            "vessel_type": self.vessel_type,
            "armaments": self.armaments,
            "speed": self.speed,
            "assignment": self.assignment,
            "registry_id": self.registry_id,
            "shipyard": self.shipyard,
            "commission_date": self.commission_date,
            "assigned_squadron": self.assigned_squadron,
            "clearance_level": self.clearance_level,
            "status": self.status,
            "vessel_motto": self.vessel_motto or "",
        }
        if self.notes:
            payload["notes"] = self.notes
        return payload

    @classmethod
    def from_data(cls, value: dict | None) -> "FleetVessel" | None:
        if not isinstance(value, dict):
            return None
        vessel_id = str(value.get("vessel_id") or value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        if not vessel_id or not name:
            return None
        vessel_type = str(value.get("vessel_type") or "").strip()
        armaments = str(value.get("armaments") or "").strip()
        speed = str(value.get("speed") or "").strip()
        assignment = str(value.get("assignment") or "").strip()
        registry_id = str(value.get("registry_id") or "").strip()
        shipyard = str(value.get("shipyard") or "").strip()
        commission_date = str(value.get("commission_date") or "").strip()
        assigned_squadron = str(value.get("assigned_squadron") or "").strip()
        clearance_level = str(value.get("clearance_level") or "").strip()
        status = str(value.get("status") or "").strip()
        if status:
            status = status.title()
        notes = value.get("notes")
        if notes is not None:
            notes = str(notes).strip() or None
        vessel_motto = value.get("vessel_motto")
        if vessel_motto is not None:
            vessel_motto = str(vessel_motto).strip() or None
        return cls(
            vessel_id=vessel_id,
            name=name,
            vessel_type=vessel_type,
            armaments=armaments,
            speed=speed,
            assignment=assignment,
            registry_id=registry_id,
            shipyard=shipyard,
            commission_date=commission_date,
            assigned_squadron=assigned_squadron,
            clearance_level=clearance_level,
            status=status,
            vessel_motto=vessel_motto,
            notes=notes,
        )


@dataclass(slots=True)
class FleetManifest:
    """Collection of vessels along with metadata."""

    vessels: list[FleetVessel]
    last_updated: str

    def copy(self) -> "FleetManifest":
        return FleetManifest(
            vessels=[v.copy() for v in self.vessels],
            last_updated=self.last_updated,
        )

    def touch(self) -> None:
        """Update ``last_updated`` to the current UTC timestamp."""

        self.last_updated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_payload(self) -> dict:
        return {
            "last_updated": self.last_updated,
            "vessels": [v.to_payload() for v in self.vessels],
        }


_DEFAULT_MANIFEST = FleetManifest(vessels=[], last_updated="")


def _coerce_manifest(data: dict | None) -> FleetManifest:
    if not isinstance(data, dict):
        return _DEFAULT_MANIFEST.copy()

    last_updated = str(data.get("last_updated") or "").strip()
    vessels: list[FleetVessel] = []
    for entry in data.get("vessels") or []:
        vessel = FleetVessel.from_data(entry)
        if vessel is not None:
            vessels.append(vessel)
    return FleetManifest(vessels=vessels, last_updated=last_updated)


def load_fleet_manifest(*, with_etag: bool = False) -> Tuple[FleetManifest, str | None]:
    """Load the fleet manifest, optionally returning the storage ETag."""

    data: dict | None = None
    etag: str | None = None
    try:
        if with_etag:
            data, etag = read_json(FLEET_MANIFEST_KEY, with_etag=True)
        else:
            data = read_json(FLEET_MANIFEST_KEY)
    except FileNotFoundError:
        data = None
        etag = None
    manifest = _coerce_manifest(data)
    return manifest, etag


def save_fleet_manifest(manifest: FleetManifest, *, etag: str | None = None) -> bool:
    """Persist ``manifest`` enforcing the optional ``etag`` guard."""

    payload = manifest.to_payload()
    return write_json(FLEET_MANIFEST_KEY, payload, etag=etag)
