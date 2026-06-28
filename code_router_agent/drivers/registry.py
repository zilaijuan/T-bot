from __future__ import annotations

from code_router_agent.drivers.base import Driver
from code_router_agent.drivers.amumu_jiema import AmumuJiemaDriver
from code_router_agent.drivers.noop import NoopDriver
from code_router_agent.drivers.qq_coder import QQCoderDriver
from code_router_agent.drivers.zyxfids import ZyxFidsDriver
from code_router_agent.drivers.unknown import UnknownDriver


DRIVER_FACTORIES = {
    "default": NoopDriver,
    "noop": NoopDriver,
    "qq_coder": QQCoderDriver,
    "zyxfids": ZyxFidsDriver,
    "amumu_jiema": AmumuJiemaDriver,
}


def create_driver(driver_name: str) -> Driver:
    factory = DRIVER_FACTORIES.get(driver_name)
    if factory is None:
        return UnknownDriver(driver_name)
    return factory()


def create_auto_registered_drivers() -> tuple[Driver, ...]:
    drivers: list[Driver] = []
    for factory in DRIVER_FACTORIES.values():
        if getattr(factory, "auto_register", False):
            drivers.append(factory())
    return tuple(drivers)