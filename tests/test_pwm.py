"""The tests for the PWM controller."""

import pytest

from custom_components.sat.boiler import BoilerState
from custom_components.sat.const import BoilerStatus, HEATING_SYSTEM_UNDERFLOOR, PWMStatus
from custom_components.sat.flame import FlameState
from custom_components.sat.heating_curve import HeatingCurve
from custom_components.sat.pwm import PWM, CycleConfig

CONTROL_LOOP_SECONDS = 20


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr("custom_components.sat.pwm.monotonic", clock)
    return clock


def create_pwm() -> PWM:
    heating_curve = HeatingCurve(HEATING_SYSTEM_UNDERFLOOR, 1.0)
    heating_curve.update(target_temperature=19.5, outside_temperature=9.0)

    pwm = PWM(CycleConfig(maximum_time=900, maximum_count=4), heating_curve, True, True)
    pwm.enable()

    return pwm


def burning_boiler(flow_temperature: float) -> BoilerState:
    return BoilerState(
        is_active=True, is_inactive=False, status=BoilerStatus.HEATING_UP,
        flame_active=True, hot_water_active=False,
        setpoint=30.0, flow_temperature=flow_temperature, return_temperature=24.0, relative_modulation_level=0,
    )


def burning_flame() -> FlameState:
    return FlameState(
        is_active=True, is_inactive=False, health_status="HEALTHY",
        latest_on_time_seconds=600, average_on_time_seconds=600, last_cycle_duration_seconds=600,
        sample_count_4h=10, cycles_last_hour=2, duty_ratio_last_15m=1.0, median_on_duration_seconds_4h=600,
    )


async def run(pwm: PWM, clock: Clock, seconds: int, requested_setpoint: float, flow_temperature: float) -> list[PWMStatus]:
    statuses = []

    for _ in range(seconds // CONTROL_LOOP_SECONDS):
        await pwm.update(burning_boiler(flow_temperature), burning_flame(), requested_setpoint)
        statuses.append(pwm.status)
        clock.now += CONTROL_LOOP_SECONDS

    return statuses


async def test_full_duty_cycle_stays_on(hass, clock: Clock) -> None:
    pwm = create_pwm()

    # A requested setpoint above the flow temperature asks for a full duty cycle
    statuses = await run(pwm, clock, 3 * 3600, requested_setpoint=31.0, flow_temperature=30.0)

    assert pwm.duty_cycle == (1800, 0)
    assert set(statuses) == {PWMStatus.ON}


async def test_partial_duty_cycle_switches_off(hass, clock: Clock) -> None:
    pwm = create_pwm()

    statuses = await run(pwm, clock, 3600, requested_setpoint=27.0, flow_temperature=30.0)

    on_time, off_time = pwm.duty_cycle
    assert off_time > 0

    first_off = statuses.index(PWMStatus.OFF)
    assert first_off * CONTROL_LOOP_SECONDS >= on_time
    assert PWMStatus.ON in statuses[first_off:]
