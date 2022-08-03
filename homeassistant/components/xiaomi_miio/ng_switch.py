from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.components.xiaomi_miio.device import XiaomiCoordinatedMiioEntity
from homeassistant.core import callback
from homeassistant.util import slugify


class XiaomiSwitch(XiaomiCoordinatedMiioEntity, SwitchEntity):
    """Representation of a Xiaomi Plug Generic."""

    entity_description: SwitchEntityDescription
    _attr_has_entity_name = True

    def __init__(self, device, switch, entry, coordinator):
        """Initialize the plug switch."""
        self._name = name = switch.name
        self._property = switch.property
        self._setter = switch.setter

        unique_id = f"{entry.unique_id}_switch_{slugify(name)}"
        super().__init__(device, entry, unique_id, coordinator)

        description = SwitchEntityDescription(
            key=switch.id,
            name=name,
            icon=switch.icon,
        )

        self._attr_is_on = self._extract_value_from_attribute(
            self.coordinator.data, description.key
        )
        self.entity_description = description

    @callback
    def _handle_coordinator_update(self):
        """Fetch state from the device."""
        # On state change the device doesn't provide the new state immediately.
        self._attr_is_on = self._extract_value_from_attribute(
            self.coordinator.data, self.entity_description.key
        )
        self.async_write_ha_state()

    @property
    def available(self):
        """Return true when state is known."""
        """
        # TODO re-enable availability checks, requires metadata from python-miio
        if (
            super().available
            and not self.coordinator.data.is_on
            and not self.entity_description.available_with_device_off
        ):
            return False
        """
        return super().available

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on an option of the miio device."""
        if await self._try_command("Turning %s on failed", self._setter, True):
            # Write state back to avoid switch flips with a slow response
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off an option of the miio device."""
        if await self._try_command("Turning off failed", self._setter, False):
            # Write state back to avoid switch flips with a slow response
            self._attr_is_on = False
            self.async_write_ha_state()
