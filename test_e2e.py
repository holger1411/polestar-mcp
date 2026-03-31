#!/usr/bin/env python3
"""Quick end-to-end test for the Polestar MCP Server."""

import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from polestar_mcp_server.polestar.auth import PolestarAuth
from polestar_mcp_server.polestar.api_client import PolestarAPIClient


async def main():
    username = os.environ.get("POLESTAR_USERNAME")
    password = os.environ.get("POLESTAR_PASSWORD")

    if not username or not password:
        print("ERROR: Set POLESTAR_USERNAME and POLESTAR_PASSWORD env vars")
        sys.exit(1)

    print("=== Polestar MCP E2E Test ===\n")

    # 1. Auth
    print("[1] Authenticating...")
    auth = PolestarAuth(username=username, password=password)
    await auth.async_init()
    print(f"    OK — token expires in {auth._tokens.expires_at}")

    # 2. API Client
    print("\n[2] Initializing API client...")
    api = PolestarAPIClient(auth)
    await api.async_init()
    print("    OK")

    # 3. Get vehicles
    print("\n[3] Fetching vehicles...")
    vehicles = await api.get_vehicles()
    for v in vehicles:
        print(f"    {v.model_name} | VIN: {v.vin} | Reg: {v.registration_number}")

    if not vehicles:
        print("    No vehicles found!")
        return

    vin = vehicles[0].vin

    # 4. Get telematics (battery + odometer + health)
    print(f"\n[4] Fetching telematics for {vin[:8]}...")
    telematics = await api.get_telematics(vin)

    print("\n    --- Battery ---")
    if telematics.battery:
        b = telematics.battery
        print(f"    Charge: {b.charge_level_percent}%")
        print(f"    Status: {b.charging_status}")
        print(f"    Range: {b.remaining_range_km} km")
        print(f"    Time to full: {b.estimated_charging_minutes} min")
    else:
        print("    No battery data")

    print("\n    --- Odometer ---")
    if telematics.odometer:
        o = telematics.odometer
        print(f"    Total: {o.total_km} km")
    else:
        print("    No odometer data")

    print("\n    --- Health ---")
    if telematics.health:
        h = telematics.health
        print(f"    Brake fluid warning: {h.brake_fluid_level_warning}")
        print(f"    Coolant warning: {h.coolant_level_warning}")
        print(f"    Oil warning: {h.oil_level_warning}")
        print(f"    Service warning: {h.service_warning}")
        print(f"    Days to service: {h.days_to_service}")
        print(f"    Km to service: {h.km_to_service}")
    else:
        print("    No health data")

    # 5. Serialize check
    print("\n[5] Serialization test...")
    data = telematics.model_dump()
    json_str = json.dumps(data, indent=2, default=str)
    print(f"    OK — {len(json_str)} bytes JSON")

    print("\n=== ALL TESTS PASSED ===")

    await api.close()
    await auth.close()


if __name__ == "__main__":
    asyncio.run(main())
