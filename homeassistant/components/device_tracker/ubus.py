"""
Support for OpenWRT (ubus) routers.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/device_tracker.ubus/
"""
import logging
import attr
from pprint import pformat as pf
from typing import Dict, List

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.device_tracker import (
    DOMAIN, PLATFORM_SCHEMA, DeviceScanner)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME


_LOGGER = logging.getLogger(__name__)

#REQUIREMENTS = ['git+https://github.com/rytilahti/python-ubus.git#ubus']

CONF_LEASE_FILE = "lease_file"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Optional(CONF_LEASE_FILE, default=None): cv.string,
})


@attr.s
class Lease:
    """Represents dnsmasq lease."""
    expires = attr.ib(repr=False)
    mac = attr.ib()
    ip = attr.ib()
    hostname = attr.ib()
    client_id = attr.ib(repr=False)


def get_scanner(hass, config):
    """Validate the configuration and return an ubus scanner."""
    scanner = UbusDeviceScanner(config[DOMAIN])

    return scanner if scanner.success_init else None


class UbusDeviceScanner(DeviceScanner):
    """
    This class queries a wireless router running OpenWrt or LEDE firmware
    over ubus' JSON-RPC interface.

    Adapted (long ago) from Tomato scanner.
    """

    def __init__(self, config):
        """Initialize the scanner."""
        from ubus import Ubus
        host = config[CONF_HOST]
        self.username = config[CONF_USERNAME]
        self.password = config[CONF_PASSWORD]
        self.lease_file = config[CONF_LEASEFILE]

        self.ubus = Ubus(host, self.username, self.password)  # type: Ubus

        self._wlan_ifaces = self._get_network_interfaces()  # NOTE: this does I/O, is it ok?
        self.success_init = self.ubus.is_valid_session()

    def _get_network_interfaces(self):
        from ubus import UbusException

        try:
            with self.ubus as ubus:
                return ubus["iwinfo"]["devices"]()
        except UbusException as ex:
            _LOGGER.error("Unable to read network interfaces from ubus,"
                          "check your configuration: %s", ex)

        return []

    def _get_connected_devices(self) -> Dict[str, Dict]:
        from ubus import UbusException

        clients = {}
        try:
            with self.ubus as ubus:
                for iface in self._wlan_ifaces:
                    clients_for_iface = ubus["iwinfo"]["assoclist"](device=iface)
                    clients.update({x["mac"]: x for x in clients_for_iface})

            _LOGGER.debug("Total %s connected devices: %s", len(clients), pf(clients))
        except UbusException as ex:
            _LOGGER.error("Unable to read connected devices: %s", ex)

        return clients

    def _get_odhcpd_leases(self, ubus) -> Dict[str, Lease]:
        leases = {}
        _LOGGER.warning("odhcpd not supported, please report the lines below")
        lease_methods = ["ipv4leases", "ipv6leases"]
        for lease_method in lease_methods:
            for dev in ubus["dhcp"][lease_method]().values():
                _LOGGER.warning("RAW lease: %s", dev)
                for iface, leases in dev.items():
                    for vlist in leases.values():
                        for lease in vlist:
                            _LOGGER.warning("odhcpd lease: %s", lease)

        return leases

    def _get_lease_files(self, ubus) -> List[str]:
        dhcp_config = ubus["uci"]["get"](config="dhcp", type="dnsmasq")
        lease_files = [x["leasefile"] for x in dhcp_config["values"]]
        return lease_files

    def _get_dnsmasq_leases(self, ubus, lease_file) -> Dict[str, Lease]:
        leases = {}
        currently_leased = ubus["file"]["read"](path=lease_file)["data"]
        for lease_line in currently_leased.splitlines():
            lease = Lease(*lease_line.split(" "))
            leases[lease.mac.upper()] = lease

        return leases

    def _get_leases(self) -> Dict[str, Lease]:
        """Return"""
        from ubus import UbusException

        leases = {}
        try:
            with self.ubus as ubus:
                if "dhcp" in ubus:
                    leases.update(self._get_odhcpd_leases(ubus))
                    _LOGGER.warning("Report the lease format as shown above")

                if self.lease_file is None:
                    lease_files = self._get_lease_files(ubus)
                else:
                    lease_files = [self.lease_file]
                for lease_file in lease_files:
                    leases.update(self._get_dnsmasq_leases(ubus, lease_file))

                _LOGGER.debug("Found %s leases: %s", len(leases), pf(leases))
        except UbusException as ex:
            _LOGGER.error("Unable to read leases from ubus: %s", ex)

        return leases

    def scan_devices(self) -> List[str]:
        """Scan for new devices and return a list with found device IDs."""
        return self._get_connected_devices().keys()

    def get_device_name(self, mac) -> str:
        """Return the name of the given device or None if we don't know."""
        leases = self._get_leases()
        if mac in leases:
            return leases[mac].hostname
