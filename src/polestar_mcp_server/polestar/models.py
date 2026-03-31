"""
Pydantic data models for Polestar vehicle data.

These models represent the data returned by the Polestar GraphQL API.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ChargingStatus(str, Enum):
    """Charging states reported by the Polestar API."""
    CHARGING_STATUS_IDLE = "CHARGING_STATUS_IDLE"
    CHARGING_STATUS_CHARGING = "CHARGING_STATUS_CHARGING"
    CHARGING_STATUS_SMART_CHARGING = "CHARGING_STATUS_SMART_CHARGING"
    CHARGING_STATUS_DONE = "CHARGING_STATUS_DONE"
    CHARGING_STATUS_FAULT = "CHARGING_STATUS_FAULT"
    CHARGING_STATUS_SCHEDULED = "CHARGING_STATUS_SCHEDULED"
    CHARGING_STATUS_DISCHARGING = "CHARGING_STATUS_DISCHARGING"
    CHARGING_STATUS_UNSPECIFIED = "CHARGING_STATUS_UNSPECIFIED"
    CHARGING_STATUS_ERROR = "CHARGING_STATUS_ERROR"

    @property
    def display_name(self) -> str:
        """Human-readable charging status."""
        names = {
            "CHARGING_STATUS_IDLE": "Idle",
            "CHARGING_STATUS_CHARGING": "Charging",
            "CHARGING_STATUS_SMART_CHARGING": "Smart Charging",
            "CHARGING_STATUS_DONE": "Fully Charged",
            "CHARGING_STATUS_FAULT": "Fault",
            "CHARGING_STATUS_SCHEDULED": "Scheduled",
            "CHARGING_STATUS_DISCHARGING": "Discharging",
            "CHARGING_STATUS_UNSPECIFIED": "Unknown",
            "CHARGING_STATUS_ERROR": "Error",
        }
        return names.get(self.value, self.value)


class BatteryData(BaseModel):
    """Real-time battery and charging information."""
    charge_level_percent: Optional[float] = Field(None, description="Battery state of charge (0-100%)")
    charging_status: Optional[ChargingStatus] = Field(None, description="Current charging state")
    estimated_charging_minutes: Optional[int] = Field(None, description="Estimated minutes until fully charged")
    remaining_range_km: Optional[float] = Field(None, description="Estimated remaining range in km")
    timestamp: Optional[datetime] = None


class OdometerData(BaseModel):
    """Odometer information."""
    total_km: Optional[float] = Field(None, description="Total distance driven in km")
    timestamp: Optional[datetime] = None


class HealthData(BaseModel):
    """Vehicle health and maintenance warnings."""
    brake_fluid_level_warning: Optional[bool] = Field(None, description="Brake fluid low warning")
    coolant_level_warning: Optional[bool] = Field(None, description="Coolant level low warning")
    oil_level_warning: Optional[bool] = Field(None, description="Oil level warning (if applicable)")
    service_warning: Optional[bool] = Field(None, description="Service required warning")
    days_to_service: Optional[int] = Field(None, description="Days until next scheduled service")
    km_to_service: Optional[float] = Field(None, description="Kilometers until next scheduled service")
    timestamp: Optional[datetime] = None


class VehicleInfo(BaseModel):
    """Static vehicle identification and specs."""
    vin: str = Field(..., description="Vehicle Identification Number")
    registration_number: Optional[str] = Field(None, description="License plate number")
    model_name: Optional[str] = Field(None, description="Model name (e.g. Polestar 2)")
    delivery_date: Optional[str] = Field(None, description="Delivery date (YYYY-MM-DD)")
    has_performance_package: Optional[bool] = Field(None, description="Performance package installed")


class TelematicsData(BaseModel):
    """Combined telematics snapshot — battery + odometer + health."""
    battery: Optional[BatteryData] = None
    odometer: Optional[OdometerData] = None
    health: Optional[HealthData] = None
