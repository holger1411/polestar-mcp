import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from polestar_mcp_server.results import (
    HealthResult,
    StatusResult,
    VehicleInfoResult,
    build_health_result,
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


def test_build_health_result_warnings():
    data = {
        "brake_fluid_level_warning": True,
        "coolant_level_warning": False,
        "oil_level_warning": None,
        "service_warning": True,
        "days_to_service": 185,
        "km_to_service": 12400.0,
    }
    r = build_health_result(data)
    assert isinstance(r, HealthResult)
    assert r.brakeFluidWarning is True
    assert r.coolantWarning is False
    assert r.oilWarning is False          # None -> False
    assert r.serviceWarning is True
    assert r.daysToService == 185
    assert r.kmToService == 12400.0


def test_build_health_result_empty():
    r = build_health_result({})
    assert r.brakeFluidWarning is False
    assert r.coolantWarning is False
    assert r.oilWarning is False
    assert r.serviceWarning is False
    assert r.daysToService is None
    assert r.kmToService is None
