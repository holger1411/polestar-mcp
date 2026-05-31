#!/usr/bin/env python3
"""
Polestar MCP Server — unofficial MCP integration for Polestar 2.

Backend: pypolestar (GraphQL telematics + gRPC live charging data).
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field, ConfigDict
from pypolestar import PolestarApi

from .utils.errors import PolestarMCPError, VehicleNotFoundError
from .results import (
    StatusResult,
    VehicleInfoResult,
    HealthResult,
    build_status_result,
    build_vehicle_info_result,
    build_health_result,
)

logger = logging.getLogger(__name__)

_init_lock = asyncio.Lock()


# --------------------------------------------------------------------------
# pypolestar API construction
# --------------------------------------------------------------------------

def _build_api(default_vin: str) -> PolestarApi:
    """Create a PolestarApi from environment credentials."""
    return PolestarApi(
        username=os.environ.get("POLESTAR_USERNAME", ""),
        password=os.environ.get("POLESTAR_PASSWORD", ""),
        vins=[default_vin] if default_vin else None,
        enable_grpc=True,
    )


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize the pypolestar API on startup; start anyway if auth fails."""
    logger.info("Polestar MCP Server starting (pypolestar backend)...")

    default_vin = os.environ.get("POLESTAR_VIN", "")
    api: Optional[PolestarApi] = None

    try:
        api = _build_api(default_vin)
        await api.async_init()
        available = api.get_available_vins()
        if not default_vin and available:
            default_vin = available[0]
        logger.info(
            "Connected. VIN(s): %d, default: %s",
            len(available),
            default_vin[:8] + "..." if default_vin else "NONE",
        )
    except Exception as exc:
        logger.error("pypolestar init failed: %s — server starts anyway", exc)
        api = None

    yield {"api": api, "default_vin": default_vin}

    if api:
        try:
            await api.async_logout()
        except Exception:
            pass
    logger.info("Polestar MCP Server stopped.")


mcp = FastMCP("polestar_mcp", lifespan=app_lifespan)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _get_state(ctx: Context) -> dict:
    return ctx.request_context.lifespan_context


def _resolve_vin(ctx: Context, vin: Optional[str]) -> str:
    if vin:
        return vin
    return _get_state(ctx)["default_vin"]


async def _ensure_api(state: dict) -> PolestarApi:
    """Return the live PolestarApi, retrying init once if it failed at startup."""
    if state["api"] is not None:
        return state["api"]
    async with _init_lock:
        if state["api"] is not None:        # re-check after acquiring the lock
            return state["api"]
        try:
            api = _build_api(state["default_vin"])
            await api.async_init()
            state["api"] = api
            if not state["default_vin"]:
                available = api.get_available_vins()
                if available:
                    state["default_vin"] = available[0]
            return api
        except Exception as exc:
            raise PolestarMCPError(f"Polestar API init failed: {exc}")


# --------------------------------------------------------------------------
# Tool: polestar_get_status
# --------------------------------------------------------------------------

class GetStatusInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    vin: Optional[str] = Field(
        default=None,
        description="Vehicle Identification Number. Leave empty to use default vehicle.",
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
async def polestar_get_status(params: GetStatusInput, ctx: Context) -> StatusResult:
    """Get current vehicle status: battery level, charging state, range, and odometer.

    Battery/range/odometer come from telematics; live charging status and charging
    power come from the gRPC API.
    """
    state = _get_state(ctx)
    api = await _ensure_api(state)
    vin = _resolve_vin(ctx, params.vin)
    if not vin:
        raise ValueError("No vehicle VIN available. Set POLESTAR_VIN or provide a VIN.")

    try:
        await api.update_latest_data(vin, update_vehicle=False, update_telematics=True, update_grpc=True)
        telematics = api.get_car_telematics(vin)
        grpc_battery = api.get_grpc_battery(vin)
    except KeyError:
        raise VehicleNotFoundError(vin)
    except ValueError as exc:
        raise PolestarMCPError(f"Polestar data error: {exc}")

    battery = telematics.battery if telematics else None
    odometer = telematics.odometer if telematics else None
    return build_status_result(
        charge_percent=battery.battery_charge_level_percentage if battery else None,
        range_km=battery.estimated_distance_to_empty_km if battery else None,
        charge_minutes=battery.estimated_charging_time_to_full_minutes if battery else None,
        total_meters=odometer.odometer_meters if odometer else None,
        grpc_status=grpc_battery.charging_status if grpc_battery else None,
        grpc_power_watts=grpc_battery.charging_power_watts if grpc_battery else None,
    )


# --------------------------------------------------------------------------
# Tool: polestar_get_vehicle_info
# --------------------------------------------------------------------------

class GetVehicleInfoInput(BaseModel):
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
async def polestar_get_vehicle_info(params: GetVehicleInfoInput, ctx: Context) -> VehicleInfoResult:
    """Get static vehicle information: model, model year, VIN, registration."""
    state = _get_state(ctx)
    api = await _ensure_api(state)
    vin = _resolve_vin(ctx, params.vin)
    if not vin:
        raise ValueError("No vehicle VIN available.")

    try:
        await api.update_latest_data(vin, update_vehicle=True, update_telematics=False, update_grpc=False)
        info = api.get_car_information(vin)
    except KeyError:
        raise VehicleNotFoundError(vin)
    except ValueError as exc:
        raise PolestarMCPError(f"Polestar data error: {exc}")
    if info is None:
        raise VehicleNotFoundError(vin)
    return build_vehicle_info_result(
        model_name=info.model_name,
        vin=info.vin or vin,
        registration_no=info.registration_no,
        model_year=info.model_year,
    )


# --------------------------------------------------------------------------
# Tool: polestar_get_health
# --------------------------------------------------------------------------

class GetHealthInput(BaseModel):
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
async def polestar_get_health(params: GetHealthInput, ctx: Context) -> HealthResult:
    """Get vehicle health and maintenance status: fluid levels, service warnings."""
    state = _get_state(ctx)
    api = await _ensure_api(state)
    vin = _resolve_vin(ctx, params.vin)
    if not vin:
        raise ValueError("No vehicle VIN available.")

    try:
        await api.update_latest_data(vin, update_vehicle=False, update_telematics=True, update_grpc=False)
        telematics = api.get_car_telematics(vin)
    except KeyError:
        raise VehicleNotFoundError(vin)
    except ValueError as exc:
        raise PolestarMCPError(f"Polestar data error: {exc}")
    health = telematics.health if telematics else None
    return build_health_result(
        brake=health.brake_fluid_level_warning if health else None,
        coolant=health.engine_coolant_level_warning if health else None,
        oil=health.oil_level_warning if health else None,
        service=health.service_warning if health else None,
        days=health.days_to_service if health else None,
        km=health.distance_to_service_km if health else None,
    )


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
