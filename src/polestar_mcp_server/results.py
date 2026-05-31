"""
DTO-Modelle + reine Builder für die MCP-Tool-Ausgaben.

camelCase-Feldnamen, damit FastMCP `structuredContent` 1:1 zu den
TypeScript-Interfaces im cp30-Frontend passt (PolestarStatus etc.).
Die Builder nehmen Primitive + pypolestar-Enums (keine pypolestar-Objekte) →
netzwerkfrei und unit-testbar; die Tool-Handler extrahieren die Werte.
"""

from typing import Optional

from pydantic import BaseModel

_UNKNOWN = "Unknown"
_UNSPECIFIED = "Unspecified"
# pypolestar-Warn-Enums: diese Werte bedeuten "kein Warnzustand".
_NO_WARNING_VALUES = {"No Warning", _UNSPECIFIED}


def _enum_value(enum_or_none) -> Optional[str]:
    """String-Wert eines pypolestar-StrEnum (oder None)."""
    if enum_or_none is None:
        return None
    return getattr(enum_or_none, "value", str(enum_or_none))


def _charging_status_str(status) -> str:
    """pypolestar ChargingStatus-Enum (oder None) -> Frontend-Display-String.

    pypolestars Enum-Werte ('Idle', 'Charging', 'Smart Charging', 'Done', ...)
    entsprechen exakt der bisherigen Display-Form. None/'Unspecified' -> 'Unknown'.
    """
    value = _enum_value(status)
    if value is None or value == _UNSPECIFIED:
        return _UNKNOWN
    return value


def _warning_active(warning) -> bool:
    """pypolestar Warn-Enum (oder None) -> True, wenn ein echter Warnzustand vorliegt."""
    value = _enum_value(warning)
    if value is None:
        return False
    return value not in _NO_WARNING_VALUES


def _enum_str_or_none(enum_or_none) -> Optional[str]:
    """Enum-Wert; None bei None/'Unspecified' (für Kontextfelder wie Steckerstatus/Typ)."""
    value = _enum_value(enum_or_none)
    if value is None or value == _UNSPECIFIED:
        return None
    return value


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


def build_status_result(
    *,
    charge_percent: Optional[float] = None,
    range_km: Optional[float] = None,
    charge_minutes: Optional[int] = None,
    total_meters: Optional[float] = None,
    grpc_status=None,
    grpc_power_watts: Optional[float] = None,
) -> StatusResult:
    """Kernwerte aus der Telematik, Ladestatus/-leistung aus gRPC."""
    return StatusResult(
        chargeLevelPercent=charge_percent,
        chargingStatus=_charging_status_str(grpc_status),
        remainingRangeKm=range_km,
        estimatedChargingMinutes=charge_minutes,
        chargingPowerKw=(grpc_power_watts / 1000.0) if grpc_power_watts is not None else None,
        totalKm=(total_meters / 1000.0) if total_meters is not None else None,
        averageSpeedKmh=None,  # Quelle liefert keine Durchschnittsgeschwindigkeit
    )


# --------------------------------------------------------------------------
# Vehicle Info
# --------------------------------------------------------------------------

class VehicleInfoResult(BaseModel):
    """Spiegelt PolestarVehicleInfo."""
    modelName: str = "Polestar 2"
    vin: str
    registrationNumber: Optional[str] = None
    deliveryDate: Optional[str] = None
    hasPerformancePackage: Optional[bool] = None
    modelYear: Optional[str] = None
    edition: Optional[str] = None
    market: Optional[str] = None


def build_vehicle_info_result(
    *,
    model_name: Optional[str] = None,
    vin: Optional[str] = None,
    registration_no: Optional[str] = None,
    model_year: Optional[str] = None,
) -> VehicleInfoResult:
    return VehicleInfoResult(
        modelName=model_name or "Polestar 2",
        vin=vin or "N/A",
        registrationNumber=registration_no,
        deliveryDate=None,         # via pypolestar nicht verfügbar
        hasPerformancePackage=None,
        modelYear=model_year,
        edition=None,              # via pypolestar nicht verfügbar
        market=None,               # via pypolestar nicht verfügbar
    )


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------

class HealthResult(BaseModel):
    """Spiegelt PolestarHealth."""
    brakeFluidWarning: bool = False
    coolantWarning: bool = False
    oilWarning: bool = False
    serviceWarning: bool = False
    daysToService: Optional[int] = None
    kmToService: Optional[float] = None


def build_health_result(
    *,
    brake=None,
    coolant=None,
    oil=None,
    service=None,
    days: Optional[int] = None,
    km: Optional[float] = None,
) -> HealthResult:
    return HealthResult(
        brakeFluidWarning=_warning_active(brake),
        coolantWarning=_warning_active(coolant),
        oilWarning=_warning_active(oil),
        serviceWarning=_warning_active(service),
        daysToService=days,
        kmToService=km,
    )


# --------------------------------------------------------------------------
# Charge Limit (Target SOC)
# --------------------------------------------------------------------------

class ChargeLimitResult(BaseModel):
    """Spiegelt PolestarChargeLimit."""
    chargeLimitPercent: Optional[int] = None
    settingType: Optional[str] = None
    pendingLimitPercent: Optional[int] = None
    pendingSettingType: Optional[str] = None


def build_charge_limit_result(
    *,
    limit_percent: Optional[int] = None,
    setting_type=None,
    pending_limit: Optional[int] = None,
    pending_setting=None,
) -> ChargeLimitResult:
    return ChargeLimitResult(
        chargeLimitPercent=limit_percent,
        settingType=_enum_str_or_none(setting_type),
        pendingLimitPercent=pending_limit,
        pendingSettingType=_enum_str_or_none(pending_setting),
    )


# --------------------------------------------------------------------------
# Charging detail (gRPC battery)
# --------------------------------------------------------------------------

class ChargingResult(BaseModel):
    """Spiegelt PolestarCharging."""
    chargingStatus: str = "Unknown"
    chargerConnectionStatus: Optional[str] = None
    chargingType: Optional[str] = None
    chargingPowerKw: Optional[float] = None
    chargingCurrentAmps: Optional[int] = None
    chargingVoltageVolts: Optional[int] = None
    averageConsumptionKwhPer100Km: Optional[float] = None
    estimatedMinutesToTargetDistance: Optional[int] = None
    estimatedMinutesToMinimumSoc: Optional[int] = None


def build_charging_result(
    *,
    charging_status=None,
    connection_status=None,
    charging_type=None,
    power_watts: Optional[float] = None,
    current_amps: Optional[int] = None,
    voltage_volts: Optional[int] = None,
    avg_consumption: Optional[float] = None,
    minutes_to_target: Optional[int] = None,
    minutes_to_min_soc: Optional[int] = None,
) -> ChargingResult:
    return ChargingResult(
        chargingStatus=_charging_status_str(charging_status),
        chargerConnectionStatus=_enum_str_or_none(connection_status),
        chargingType=_enum_str_or_none(charging_type),
        chargingPowerKw=(power_watts / 1000.0) if power_watts is not None else None,
        chargingCurrentAmps=current_amps,
        chargingVoltageVolts=voltage_volts,
        averageConsumptionKwhPer100Km=avg_consumption,
        estimatedMinutesToTargetDistance=minutes_to_target,
        estimatedMinutesToMinimumSoc=minutes_to_min_soc,
    )
