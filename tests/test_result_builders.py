import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from polestar_mcp_server.results import (
    StatusResult,
    VehicleInfoResult,
    build_status_result,
    build_vehicle_info_result,
    display_charging_status,
)


def test_display_charging_status_smart():
    assert display_charging_status("CHARGING_STATUS_SMART_CHARGING") == "Smart Charging"


def test_display_charging_status_idle():
    assert display_charging_status("CHARGING_STATUS_IDLE") == "Idle"


def test_display_charging_status_done():
    # title() von "DONE" ergibt "Done" — bewusst identisch zum alten _format_status
    assert display_charging_status("CHARGING_STATUS_DONE") == "Done"


def test_display_charging_status_none():
    assert display_charging_status(None) == "Unknown"


def test_build_status_result_full():
    data = {
        "battery": {
            "charge_level_percent": 78.0,
            "charging_status": "CHARGING_STATUS_SMART_CHARGING",
            "remaining_range_km": 385.0,
            "estimated_charging_minutes": 90,
        },
        "odometer": {"total_km": 24830.0},
    }
    r = build_status_result(data)
    assert isinstance(r, StatusResult)
    assert r.chargeLevelPercent == 78.0
    assert r.chargingStatus == "Smart Charging"
    assert r.remainingRangeKm == 385.0
    assert r.estimatedChargingMinutes == 90
    assert r.totalKm == 24830.0
    # Quelle liefert diese beiden nie → immer None
    assert r.chargingPowerKw is None
    assert r.averageSpeedKmh is None


def test_build_status_result_empty():
    r = build_status_result({})
    assert r.chargeLevelPercent is None
    assert r.chargingStatus == "Unknown"
    assert r.totalKm is None


def test_build_vehicle_info_result_full():
    data = {
        "vin": "LPSVSEGEKNL074271",
        "registration_number": "H ER 233E",
        "model_name": "Polestar 2",
        "delivery_date": "2022-05-30",
    }
    r = build_vehicle_info_result(data)
    assert isinstance(r, VehicleInfoResult)
    assert r.modelName == "Polestar 2"
    assert r.vin == "LPSVSEGEKNL074271"
    assert r.registrationNumber == "H ER 233E"
    assert r.deliveryDate == "2022-05-30"
    assert r.hasPerformancePackage is None


def test_build_vehicle_info_result_defaults_model_name():
    data = {"vin": "XYZ", "model_name": None}
    r = build_vehicle_info_result(data)
    assert r.modelName == "Polestar 2"
    assert r.registrationNumber is None
