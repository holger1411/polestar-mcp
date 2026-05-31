"""
DTO-Modelle + reine Builder für die MCP-Tool-Ausgaben.

camelCase-Feldnamen, damit FastMCP `structuredContent` 1:1 zu den
TypeScript-Interfaces im cp30-Frontend passt (PolestarStatus etc.).
Netzwerkfrei und ohne FastMCP-Abhängigkeit → unit-testbar.
"""

from typing import Optional

from pydantic import BaseModel


# --------------------------------------------------------------------------
# Charging-Status: exakt die alte _format_status-Darstellung reproduzieren
# --------------------------------------------------------------------------

def display_charging_status(raw) -> str:
    """'CHARGING_STATUS_SMART_CHARGING' -> 'Smart Charging'. None -> 'Unknown'.

    Reproduziert bewusst die frühere Markdown-Formatierung (inkl. der Eigenheit,
    dass DONE zu 'Done' und nicht 'Fully Charged' wird), damit die Label-Maps
    im Frontend unverändert greifen.
    """
    if raw is None:
        return "Unknown"
    raw_str = raw.value if hasattr(raw, "value") else str(raw)
    return raw_str.replace("CHARGING_STATUS_", "").replace("_", " ").title()


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------

class StatusResult(BaseModel):
    """Spiegelt PolestarStatus (ohne timestamp/fallback — die setzt die Route)."""
    chargeLevelPercent: Optional[float] = None
    chargingStatus: str = "Unknown"
    remainingRangeKm: Optional[float] = None
    estimatedChargingMinutes: Optional[int] = None
    chargingPowerKw: Optional[float] = None
    totalKm: Optional[float] = None
    averageSpeedKmh: Optional[float] = None


def build_status_result(data: dict) -> StatusResult:
    """data = telematics.model_dump() (oder Cache-Variante davon)."""
    battery = data.get("battery") or {}
    odometer = data.get("odometer") or {}
    return StatusResult(
        chargeLevelPercent=battery.get("charge_level_percent"),
        chargingStatus=display_charging_status(battery.get("charging_status")),
        remainingRangeKm=battery.get("remaining_range_km"),
        estimatedChargingMinutes=battery.get("estimated_charging_minutes"),
        chargingPowerKw=None,   # GraphQL-Quelle liefert keine Ladeleistung
        totalKm=odometer.get("total_km"),
        averageSpeedKmh=None,   # Quelle liefert keine Durchschnittsgeschwindigkeit
    )
