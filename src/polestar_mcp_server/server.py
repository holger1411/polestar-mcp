#!/usr/bin/env python3
"""
Polestar MCP Server — unofficial MCP integration for Polestar 2.

Exposes vehicle data (battery, odometer, health, specs) via MCP tools.
Uses the reverse-engineered Polestar GraphQL API.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field, ConfigDict

from .polestar.auth import PolestarAuth
from .polestar.api_client import PolestarAPIClient
from .polestar.models import VehicleInfo
from .cache.manager import CacheManager
from .utils.errors import APIError, AuthenticationError, PolestarMCPError

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Lifespan: start the server, try auth — but don't crash if it fails
# --------------------------------------------------------------------------

@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize Polestar API connection on startup, clean up on shutdown."""
    logger.info("Polestar MCP Server starting...")

    cache = CacheManager()
    auth = None
    api = None
    vehicles = []
    default_vin = os.environ.get("POLESTAR_VIN", "")
    auth_error = None

    try:
        auth = PolestarAuth()
        await auth.async_init()

        api = PolestarAPIClient(auth)
        await api.async_init()

        # Pre-fetch available VINs
        vehicles = await api.get_vehicles()
        vin_list = [v.vin for v in vehicles]
        if not default_vin and vin_list:
            default_vin = vin_list[0]

        logger.info(
            "Connected. Found %d vehicle(s). Default VIN: %s",
            len(vin_list),
            default_vin[:8] + "..." if default_vin else "NONE",
        )

        # Cache vehicle info (rarely changes)
        for v in vehicles:
            key = cache.make_key("vehicle_info", vin=v.vin)
            cache.set(key, v.model_dump(), data_type="vehicle_info")

    except Exception as exc:
        auth_error = str(exc)
        logger.error("Auth failed on startup: %s — server will start anyway", exc)
        logger.error("Tools will attempt to reconnect when called.")

    yield {
        "auth": auth,
        "api": api,
        "cache": cache,
        "vehicles": vehicles,
        "default_vin": default_vin,
        "auth_error": auth_error,
    }

    # Cleanup
    if api:
        await api.close()
    if auth:
        await auth.close()
    logger.info("Polestar MCP Server stopped.")


# --------------------------------------------------------------------------
# MCP Server
# --------------------------------------------------------------------------

mcp = FastMCP(
    "polestar_mcp",
    lifespan=app_lifespan,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _get_state(ctx: Context) -> dict:
    """Get the lifespan state from context."""
    return ctx.request_context.lifespan_context


def _resolve_vin(ctx: Context, vin: Optional[str]) -> str:
    """Resolve VIN: use provided value or fall back to default."""
    if vin:
        return vin
    state = _get_state(ctx)
    return state["default_vin"]


async def _ensure_connected(state: dict) -> tuple[PolestarAPIClient, str | None]:
    """
    Ensure we have an active API connection.
    If auth failed on startup, retry now.
    Returns (api_client, error_message).
    """
    if state["api"] is not None and state["auth_error"] is None:
        return state["api"], None

    # Try to (re-)connect
    try:
        logger.info("Attempting (re-)connection to Polestar API...")
        auth = PolestarAuth()
        await auth.async_init()

        api = PolestarAPIClient(auth)
        await api.async_init()

        # Update state
        state["auth"] = auth
        state["api"] = api
        state["auth_error"] = None

        # Fetch vehicles
        vehicles = await api.get_vehicles()
        state["vehicles"] = vehicles
        if not state["default_vin"] and vehicles:
            state["default_vin"] = vehicles[0].vin

        # Cache vehicle info
        cache = state["cache"]
        for v in vehicles:
            key = cache.make_key("vehicle_info", vin=v.vin)
            cache.set(key, v.model_dump(), data_type="vehicle_info")

        logger.info("Reconnected successfully!")
        return api, None

    except AuthenticationError as exc:
        error = f"Authentication failed: {exc}"
        state["auth_error"] = error
        logger.error(error)
        return None, error

    except APIError as exc:
        # GraphQL / transport errors reach the server but are not auth failures.
        error = f"Polestar API error: {exc}"
        state["auth_error"] = error
        logger.error(error)
        return None, error

    except Exception as exc:
        error = f"Unexpected error while connecting: {type(exc).__name__}: {exc}"
        state["auth_error"] = error
        logger.error(error)
        return None, error


# --------------------------------------------------------------------------
# Tool: polestar_get_status
# --------------------------------------------------------------------------

class GetStatusInput(BaseModel):
    """Input for retrieving current vehicle status."""
    model_config = ConfigDict(str_strip_whitespace=True)

    vin: Optional[str] = Field(
        default=None,
        description=(
            "Vehicle Identification Number. Leave empty to use default vehicle. "
            "Example: 'YSMYKEAE3PA012345'"
        ),
    )


@mcp.tool(
    name="polestar_get_status",
    annotations={
        "title": "Get Polestar Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def polestar_get_status(params: GetStatusInput, ctx: Context) -> str:
    """Get current vehicle status: battery level, charging state, range, and odometer.

    Returns real-time data including battery charge percentage, charging status,
    estimated remaining range in km, and total distance driven.
    """
    try:
        state = _get_state(ctx)
        api, error = await _ensure_connected(state)
        if error:
            return f"Error: {error}"

        cache: CacheManager = state["cache"]
        vin = _resolve_vin(ctx, params.vin)

        if not vin:
            return "Error: No vehicle VIN available. Set POLESTAR_VIN or provide a VIN."

        # Check cache
        cache_key = cache.make_key("status", vin=vin)
        cached = cache.get(cache_key)
        if cached:
            return _format_status(cached, vin, from_cache=True)

        # Fetch fresh data
        telematics = await api.get_telematics(vin)
        data = telematics.model_dump()
        cache.set(cache_key, data, data_type="status")

        return _format_status(data, vin)

    except PolestarMCPError as exc:
        return f"Error: {exc.error_code} — {exc}"
    except Exception as exc:
        logger.exception("Unexpected error in polestar_get_status")
        return f"Error: {type(exc).__name__}: {exc}"


def _format_status(data: dict, vin: str, from_cache: bool = False) -> str:
    """Format telematics data as readable Markdown."""
    battery = data.get("battery") or {}
    odometer = data.get("odometer") or {}

    lines = [f"# Polestar Status — {vin[:8]}..."]
    if from_cache:
        lines.append("*(cached)*")
    lines.append("")

    # Battery
    charge = battery.get("charge_level_percent")
    status = battery.get("charging_status")
    range_km = battery.get("remaining_range_km")
    charge_min = battery.get("estimated_charging_minutes")
    power_w = battery.get("charging_power_watts")

    lines.append("## Battery & Charging")
    if charge is not None:
        lines.append(f"- **Charge**: {charge:.0f}%")
    if status:
        display = status.replace("CHARGING_STATUS_", "").replace("_", " ").title()
        lines.append(f"- **Status**: {display}")
    if range_km is not None:
        lines.append(f"- **Range**: {range_km:.0f} km")
    if charge_min is not None and charge_min > 0:
        hours = charge_min // 60
        mins = charge_min % 60
        lines.append(f"- **Time to full**: {hours}h {mins}min")
    if power_w is not None and power_w > 0:
        lines.append(f"- **Charging power**: {power_w / 1000:.1f} kW")

    # Odometer
    total_km = odometer.get("total_km")
    avg_speed = odometer.get("average_speed_kmh")

    lines.append("")
    lines.append("## Odometer")
    if total_km is not None:
        lines.append(f"- **Total**: {total_km:,.0f} km")
    if avg_speed is not None:
        lines.append(f"- **Avg speed**: {avg_speed:.1f} km/h")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Tool: polestar_get_vehicle_info
# --------------------------------------------------------------------------

class GetVehicleInfoInput(BaseModel):
    """Input for retrieving vehicle specifications."""
    model_config = ConfigDict(str_strip_whitespace=True)

    vin: Optional[str] = Field(
        default=None,
        description="Vehicle Identification Number. Leave empty for default vehicle.",
    )


@mcp.tool(
    name="polestar_get_vehicle_info",
    annotations={
        "title": "Get Polestar Vehicle Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def polestar_get_vehicle_info(params: GetVehicleInfoInput, ctx: Context) -> str:
    """Get static vehicle information: model, year, VIN, battery specs, software version.

    This data changes rarely (only after OTA updates) and is heavily cached.
    """
    try:
        state = _get_state(ctx)
        api, error = await _ensure_connected(state)
        if error:
            return f"Error: {error}"

        cache: CacheManager = state["cache"]
        vehicles: list[VehicleInfo] = state["vehicles"]
        vin = _resolve_vin(ctx, params.vin)

        if not vin:
            return "Error: No vehicle VIN available."

        # Check cache first
        cache_key = cache.make_key("vehicle_info", vin=vin)
        cached = cache.get(cache_key)
        if cached:
            return _format_vehicle_info(cached, from_cache=True)

        # Find in pre-fetched vehicle list
        for v in vehicles:
            if v.vin == vin:
                data = v.model_dump()
                cache.set(cache_key, data, data_type="vehicle_info")
                return _format_vehicle_info(data)

        # Re-fetch
        fresh_vehicles = await api.get_vehicles()
        for v in fresh_vehicles:
            if v.vin == vin:
                data = v.model_dump()
                cache.set(cache_key, data, data_type="vehicle_info")
                return _format_vehicle_info(data)

        return f"Error: Vehicle with VIN '{vin}' not found in your account."

    except PolestarMCPError as exc:
        return f"Error: {exc.error_code} — {exc}"
    except Exception as exc:
        logger.exception("Unexpected error in polestar_get_vehicle_info")
        return f"Error: {type(exc).__name__}: {exc}"


def _format_vehicle_info(data: dict, from_cache: bool = False) -> str:
    """Format vehicle info as readable Markdown."""
    lines = [f"# Vehicle Info — {data.get('vin', 'Unknown')[:8]}..."]
    if from_cache:
        lines.append("*(cached)*")
    lines.append("")

    if data.get("model_name"):
        lines.append(f"- **Model**: {data['model_name']}")
    lines.append(f"- **VIN**: {data.get('vin', 'N/A')}")
    if data.get("registration_number"):
        lines.append(f"- **Registration**: {data['registration_number']}")
    if data.get("delivery_date"):
        lines.append(f"- **Delivered**: {data['delivery_date']}")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Tool: polestar_get_health
# --------------------------------------------------------------------------

class GetHealthInput(BaseModel):
    """Input for retrieving vehicle health and maintenance status."""
    model_config = ConfigDict(str_strip_whitespace=True)

    vin: Optional[str] = Field(
        default=None,
        description="Vehicle Identification Number. Leave empty for default vehicle.",
    )


@mcp.tool(
    name="polestar_get_health",
    annotations={
        "title": "Get Polestar Health Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def polestar_get_health(params: GetHealthInput, ctx: Context) -> str:
    """Get vehicle health and maintenance status: fluid levels, service warnings, next service date.

    Checks brake fluid, coolant, oil levels and reports on upcoming service needs.
    """
    try:
        state = _get_state(ctx)
        api, error = await _ensure_connected(state)
        if error:
            return f"Error: {error}"

        cache: CacheManager = state["cache"]
        vin = _resolve_vin(ctx, params.vin)

        if not vin:
            return "Error: No vehicle VIN available."

        # Check cache
        cache_key = cache.make_key("health", vin=vin)
        cached = cache.get(cache_key)
        if cached:
            return _format_health(cached, vin, from_cache=True)

        # Fetch fresh
        telematics = await api.get_telematics(vin)
        health_data = (telematics.health.model_dump() if telematics.health else {})
        cache.set(cache_key, health_data, data_type="health")

        return _format_health(health_data, vin)

    except PolestarMCPError as exc:
        return f"Error: {exc.error_code} — {exc}"
    except Exception as exc:
        logger.exception("Unexpected error in polestar_get_health")
        return f"Error: {type(exc).__name__}: {exc}"


def _format_health(data: dict, vin: str, from_cache: bool = False) -> str:
    """Format health data as readable Markdown."""
    lines = [f"# Health Report — {vin[:8]}..."]
    if from_cache:
        lines.append("*(cached)*")
    lines.append("")

    if not data:
        lines.append("No health data available for this vehicle.")
        return "\n".join(lines)

    # Fluid levels
    lines.append("## Fluid Levels")
    warnings = {
        "brake_fluid_level_warning": "Brake Fluid",
        "coolant_level_warning": "Coolant",
        "oil_level_warning": "Oil",
    }
    any_warning = False
    for key, label in warnings.items():
        val = data.get(key)
        if val is True:
            lines.append(f"- **{label}**: WARNING — Low level!")
            any_warning = True
        elif val is False:
            lines.append(f"- **{label}**: OK")

    if not any_warning:
        lines.append("")
        lines.append("All fluid levels normal.")

    # Service
    lines.append("")
    lines.append("## Service")
    service_warning = data.get("service_warning")
    days = data.get("days_to_service")
    km = data.get("km_to_service")

    if service_warning is True:
        lines.append("- **Service required!**")
    elif service_warning is False:
        lines.append("- No service warnings")

    if days is not None:
        lines.append(f"- **Next service in**: {days} days")
    if km is not None:
        lines.append(f"- **Next service in**: {km:,.0f} km")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main():
    """Run the Polestar MCP server (stdio transport)."""
    logging.basicConfig(
        level=os.environ.get("POLESTAR_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
