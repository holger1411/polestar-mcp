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
from .utils.errors import APIError, AuthenticationError, PolestarMCPError, VehicleNotFoundError
from .results import (
    StatusResult,
    VehicleInfoResult,
    HealthResult,
    build_status_result,
    build_vehicle_info_result,
    build_health_result,
)

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
async def polestar_get_status(params: GetStatusInput, ctx: Context) -> StatusResult:
    """Get current vehicle status: battery level, charging state, range, and odometer.

    Returns real-time data including battery charge percentage, charging status,
    estimated remaining range in km, and total distance driven.
    """
    state = _get_state(ctx)
    api, error = await _ensure_connected(state)
    if error:
        raise PolestarMCPError(error)

    cache: CacheManager = state["cache"]
    vin = _resolve_vin(ctx, params.vin)
    if not vin:
        raise ValueError("No vehicle VIN available. Set POLESTAR_VIN or provide a VIN.")

    cache_key = cache.make_key("status", vin=vin)
    cached = cache.get(cache_key)
    if cached:
        return build_status_result(cached)

    telematics = await api.get_telematics(vin)
    data = telematics.model_dump()
    cache.set(cache_key, data, data_type="status")
    return build_status_result(data)


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
async def polestar_get_vehicle_info(params: GetVehicleInfoInput, ctx: Context) -> VehicleInfoResult:
    """Get static vehicle information: model, year, VIN, battery specs, software version.

    This data changes rarely (only after OTA updates) and is heavily cached.
    """
    state = _get_state(ctx)
    api, error = await _ensure_connected(state)
    if error:
        raise PolestarMCPError(error)

    cache: CacheManager = state["cache"]
    vehicles: list[VehicleInfo] = state["vehicles"]
    vin = _resolve_vin(ctx, params.vin)
    if not vin:
        raise ValueError("No vehicle VIN available.")

    cache_key = cache.make_key("vehicle_info", vin=vin)
    cached = cache.get(cache_key)
    if cached:
        return build_vehicle_info_result(cached)

    for v in vehicles:
        if v.vin == vin:
            data = v.model_dump()
            cache.set(cache_key, data, data_type="vehicle_info")
            return build_vehicle_info_result(data)

    fresh_vehicles = await api.get_vehicles()
    for v in fresh_vehicles:
        if v.vin == vin:
            data = v.model_dump()
            cache.set(cache_key, data, data_type="vehicle_info")
            return build_vehicle_info_result(data)

    raise VehicleNotFoundError(vin)


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
async def polestar_get_health(params: GetHealthInput, ctx: Context) -> HealthResult:
    """Get vehicle health and maintenance status: fluid levels, service warnings, next service date.

    Checks brake fluid, coolant, oil levels and reports on upcoming service needs.
    """
    state = _get_state(ctx)
    api, error = await _ensure_connected(state)
    if error:
        raise PolestarMCPError(error)

    cache: CacheManager = state["cache"]
    vin = _resolve_vin(ctx, params.vin)
    if not vin:
        raise ValueError("No vehicle VIN available.")

    cache_key = cache.make_key("health", vin=vin)
    cached = cache.get(cache_key)
    if cached:
        return build_health_result(cached)

    telematics = await api.get_telematics(vin)
    health_data = telematics.health.model_dump() if telematics.health else {}
    cache.set(cache_key, health_data, data_type="health")
    return build_health_result(health_data)


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
