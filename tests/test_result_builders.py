import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pypolestar.models import (
    BrakeFluidLevelWarning,
    ChargingStatus,
    ServiceWarning,
)

from polestar_mcp_server.results import (
    HealthResult,
    StatusResult,
    VehicleInfoResult,
    _charging_status_str,
    _warning_active,
    build_health_result,
    build_status_result,
    build_vehicle_info_result,
)


# ---- _charging_status_str -------------------------------------------------

def test_charging_status_smart():
    assert _charging_status_str(ChargingStatus.CHARGING_STATUS_SMART_CHARGING) == "Smart Charging"


def test_charging_status_idle():
    assert _charging_status_str(ChargingStatus.CHARGING_STATUS_IDLE) == "Idle"


def test_charging_status_done():
    assert _charging_status_str(ChargingStatus.CHARGING_STATUS_DONE) == "Done"


def test_charging_status_unspecified_maps_to_unknown():
    assert _charging_status_str(ChargingStatus.CHARGING_STATUS_UNSPECIFIED) == "Unknown"


def test_charging_status_none_maps_to_unknown():
    assert _charging_status_str(None) == "Unknown"


# ---- _warning_active ------------------------------------------------------

def test_warning_active_no_warning_is_false():
    assert _warning_active(BrakeFluidLevelWarning.BRAKE_FLUID_LEVEL_WARNING_NO_WARNING) is False


def test_warning_active_too_low_is_true():
    assert _warning_active(BrakeFluidLevelWarning.BRAKE_FLUID_LEVEL_WARNING_TOO_LOW) is True


def test_warning_active_none_is_false():
    assert _warning_active(None) is False


def test_warning_active_service_required_is_true():
    assert _warning_active(ServiceWarning.SERVICE_WARNING_SERVICE_REQUIRED) is True


# ---- build_status_result --------------------------------------------------

def test_build_status_result_full():
    r = build_status_result(
        charge_percent=68.0,
        range_km=290.0,
        charge_minutes=0,
        total_meters=41149904,
        grpc_status=ChargingStatus.CHARGING_STATUS_CHARGING,
        grpc_power_watts=11000,
    )
    assert isinstance(r, StatusResult)
    assert r.chargeLevelPercent == 68.0
    assert r.chargingStatus == "Charging"
    assert r.remainingRangeKm == 290.0
    assert r.estimatedChargingMinutes == 0
    assert r.chargingPowerKw == 11.0          # 11000 W -> 11.0 kW
    assert r.totalKm == 41149.904             # 41149904 m -> km
    assert r.averageSpeedKmh is None


def test_build_status_result_grpc_missing():
    # gRPC nicht verfügbar -> Ladefelder degradieren, Kernwerte bleiben
    r = build_status_result(
        charge_percent=68.0,
        range_km=290.0,
        charge_minutes=None,
        total_meters=41149904,
        grpc_status=None,
        grpc_power_watts=None,
    )
    assert r.chargeLevelPercent == 68.0
    assert r.totalKm == 41149.904
    assert r.chargingStatus == "Unknown"
    assert r.chargingPowerKw is None


def test_build_status_result_empty():
    r = build_status_result()
    assert r.chargeLevelPercent is None
    assert r.totalKm is None
    assert r.chargingStatus == "Unknown"
    assert r.chargingPowerKw is None


# ---- build_vehicle_info_result --------------------------------------------

def test_build_vehicle_info_result():
    r = build_vehicle_info_result(
        model_name="Polestar 2",
        vin="LPSV...",
        registration_no="H ER 233E",
        model_year="2022",
    )
    assert isinstance(r, VehicleInfoResult)
    assert r.modelName == "Polestar 2"
    assert r.vin == "LPSV..."
    assert r.registrationNumber == "H ER 233E"
    assert r.modelYear == "2022"
    # via pypolestar nicht verfügbar -> None
    assert r.deliveryDate is None
    assert r.edition is None
    assert r.market is None
    assert r.hasPerformancePackage is None


def test_build_vehicle_info_result_defaults():
    r = build_vehicle_info_result(model_name=None, vin=None, registration_no=None, model_year=None)
    assert r.modelName == "Polestar 2"
    assert r.vin == "N/A"


# ---- build_health_result --------------------------------------------------

def test_build_health_result_warnings():
    r = build_health_result(
        brake=BrakeFluidLevelWarning.BRAKE_FLUID_LEVEL_WARNING_TOO_LOW,
        coolant=None,
        oil=BrakeFluidLevelWarning.BRAKE_FLUID_LEVEL_WARNING_NO_WARNING,
        service=ServiceWarning.SERVICE_WARNING_SERVICE_REQUIRED,
        days=185,
        km=12400.0,
    )
    assert isinstance(r, HealthResult)
    assert r.brakeFluidWarning is True
    assert r.coolantWarning is False
    assert r.oilWarning is False
    assert r.serviceWarning is True
    assert r.daysToService == 185
    assert r.kmToService == 12400.0


def test_build_health_result_empty():
    r = build_health_result()
    assert r.brakeFluidWarning is False
    assert r.serviceWarning is False
    assert r.daysToService is None
    assert r.kmToService is None
