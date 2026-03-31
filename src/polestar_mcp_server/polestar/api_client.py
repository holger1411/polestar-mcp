"""
Polestar GraphQL API Client.

Handles all communication with pc-api.polestar.com, including
query execution, response parsing, and error handling.
"""

import logging
from typing import Any, Optional

import httpx

from .auth import PolestarAuth
from .models import (
    BatteryData,
    ChargingStatus,
    HealthData,
    OdometerData,
    TelematicsData,
    VehicleInfo,
)
from ..utils.errors import APIError, AuthenticationError, VehicleNotFoundError

logger = logging.getLogger(__name__)

# Polestar GraphQL endpoint
API_BASE_URL = "https://pc-api.polestar.com/eu-north-1/mystar-v2/"

# Maximum retries for transient errors
MAX_RETRIES = 3

# --------------------------------------------------------------------------
# GraphQL Queries (based on pypolestar reverse-engineering)
# --------------------------------------------------------------------------

QUERY_GET_CONSUMER_CARS_V2 = """
query GetConsumerCarsV2 {
    getConsumerCarsV2 {
        vin
        internalVehicleIdentifier
        registrationNo
        deliveryDate
        currentPlannedDeliveryDate
        hasPerformancePackage
        content {
            model {
                name
            }
        }
    }
}
"""

QUERY_CAR_TELEMATICS_V2 = """
query CarTelematicsV2($vins: [String!]!) {
    carTelematicsV2(vins: $vins) {
        battery {
            vin
            batteryChargeLevelPercentage
            chargingStatus
            estimatedChargingTimeToFullMinutes
            estimatedDistanceToEmptyKm
            timestamp {
                seconds
                nanos
            }
        }
        odometer {
            vin
            odometerMeters
            timestamp {
                seconds
                nanos
            }
        }
        health {
            vin
            brakeFluidLevelWarning
            daysToService
            distanceToServiceKm
            engineCoolantLevelWarning
            oilLevelWarning
            serviceWarning
            timestamp {
                seconds
                nanos
            }
        }
    }
}
"""


class PolestarAPIClient:
    """
    Async GraphQL client for the Polestar API.

    Usage:
        auth = PolestarAuth(username="...", password="...")
        await auth.async_init()
        client = PolestarAPIClient(auth)
        vehicles = await client.get_vehicles()
        telematics = await client.get_telematics(vin="YS3...")
    """

    def __init__(self, auth: PolestarAuth):
        self.auth = auth
        self._http: Optional[httpx.AsyncClient] = None

    async def async_init(self) -> None:
        """Initialize the HTTP client."""
        self._http = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # Low-level GraphQL execution
    # ------------------------------------------------------------------

    async def _execute_query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a GraphQL query against the Polestar API.

        Handles authentication headers, retries on transient errors,
        and parses the GraphQL response.
        """
        if not self._http:
            await self.async_init()

        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = await self.auth.get_auth_headers()
                headers["Content-Type"] = "application/json"

                payload: dict[str, Any] = {"query": query}
                if variables:
                    payload["variables"] = variables

                logger.debug(
                    "GraphQL request (attempt %d/%d)", attempt, MAX_RETRIES
                )

                resp = await self._http.post(
                    API_BASE_URL,
                    json=payload,
                    headers=headers,
                )

                if resp.status_code == 401:
                    logger.warning("Got 401, re-authenticating")
                    await self.auth._refresh_or_reauthenticate()
                    continue

                if resp.status_code == 429:
                    raise APIError("Rate limit exceeded", status_code=429)

                resp.raise_for_status()

                data = resp.json()

                # Check for GraphQL-level errors
                if "errors" in data:
                    error_msgs = [e.get("message", "Unknown") for e in data["errors"]]
                    raise APIError(
                        f"GraphQL errors: {'; '.join(error_msgs)}",
                        details={"errors": data["errors"]},
                    )

                return data.get("data", {})

            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in (500, 502, 503, 504):
                    logger.warning(
                        "Server error %d (attempt %d/%d)",
                        exc.response.status_code,
                        attempt,
                        MAX_RETRIES,
                    )
                    continue
                raise APIError(
                    f"HTTP {exc.response.status_code}",
                    status_code=exc.response.status_code,
                ) from exc

            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning("Timeout (attempt %d/%d)", attempt, MAX_RETRIES)
                continue

        raise APIError(
            f"Failed after {MAX_RETRIES} attempts: {last_error}",
        )

    # ------------------------------------------------------------------
    # High-level data methods
    # ------------------------------------------------------------------

    async def get_vehicles(self) -> list[VehicleInfo]:
        """
        Fetch all vehicles associated with the Polestar account.

        Returns a list of VehicleInfo models.
        """
        data = await self._execute_query(QUERY_GET_CONSUMER_CARS_V2)
        cars = data.get("getConsumerCarsV2", [])

        vehicles = []
        for car in cars:
            content = car.get("content", {})
            model_info = content.get("model", {})

            vehicle = VehicleInfo(
                vin=car["vin"],
                registration_number=car.get("registrationNo"),
                model_name=model_info.get("name"),
                delivery_date=car.get("deliveryDate"),
                has_performance_package=car.get("hasPerformancePackage"),
            )
            vehicles.append(vehicle)

        logger.info("Found %d vehicle(s)", len(vehicles))
        return vehicles

    async def get_telematics(self, vin: str) -> TelematicsData:
        """
        Fetch current telematics data for a vehicle.

        Uses the carTelemeticsV2 query which returns battery, odometer,
        and health data for one or more VINs.

        Args:
            vin: Vehicle Identification Number

        Returns:
            TelematicsData with battery, odometer, and health data.
        """
        data = await self._execute_query(
            QUERY_CAR_TELEMATICS_V2,
            variables={"vins": [vin]},
        )

        raw = data.get("carTelematicsV2", {})
        if not raw:
            raise VehicleNotFoundError(vin)

        # Each sub-field (battery, odometer, health) is a list — find
        # the entry matching our VIN (or take the first one).
        battery_list = raw.get("battery") or []
        odometer_list = raw.get("odometer") or []
        health_list = raw.get("health") or []

        battery_raw = self._find_by_vin(battery_list, vin)
        odometer_raw = self._find_by_vin(odometer_list, vin)
        health_raw = self._find_by_vin(health_list, vin)

        return TelematicsData(
            battery=self._parse_battery(battery_raw),
            odometer=self._parse_odometer(odometer_raw),
            health=self._parse_health(health_raw),
        )

    # ------------------------------------------------------------------
    # Response parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_by_vin(items: list[dict], vin: str) -> dict:
        """Find the entry matching a VIN in a list, or return first entry."""
        for item in items:
            if item.get("vin") == vin:
                return item
        return items[0] if items else {}

    @staticmethod
    def _parse_battery(raw: dict) -> BatteryData | None:
        """Parse battery data from GraphQL response."""
        if not raw:
            return None

        charging_status = None
        raw_status = raw.get("chargingStatus")
        if raw_status:
            try:
                charging_status = ChargingStatus(raw_status)
            except ValueError:
                charging_status = ChargingStatus.CHARGING_STATUS_UNSPECIFIED

        return BatteryData(
            charge_level_percent=raw.get("batteryChargeLevelPercentage"),
            charging_status=charging_status,
            estimated_charging_minutes=raw.get("estimatedChargingTimeToFullMinutes"),
            remaining_range_km=raw.get("estimatedDistanceToEmptyKm"),
        )

    @staticmethod
    def _parse_odometer(raw: dict) -> OdometerData | None:
        """Parse odometer data from GraphQL response."""
        if not raw:
            return None

        total_meters = raw.get("odometerMeters")
        total_km = total_meters / 1000.0 if total_meters is not None else None

        return OdometerData(
            total_km=total_km,
        )

    @staticmethod
    def _is_warning_active(value: str | bool | None) -> bool | None:
        """Convert warning string/bool to boolean. Returns None if unavailable."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        # Polestar returns strings like 'BRAKE_FLUID_LEVEL_WARNING_NO_WARNING'
        # or 'SERVICE_WARNING_WARNING' etc.
        if isinstance(value, str):
            return "NO_WARNING" not in value.upper()
        return None

    @classmethod
    def _parse_health(cls, raw: dict) -> HealthData | None:
        """Parse health data from GraphQL response."""
        if not raw:
            return None

        return HealthData(
            brake_fluid_level_warning=cls._is_warning_active(raw.get("brakeFluidLevelWarning")),
            coolant_level_warning=cls._is_warning_active(raw.get("engineCoolantLevelWarning")),
            oil_level_warning=cls._is_warning_active(raw.get("oilLevelWarning")),
            service_warning=cls._is_warning_active(raw.get("serviceWarning")),
            days_to_service=raw.get("daysToService"),
            km_to_service=raw.get("distanceToServiceKm"),
        )
