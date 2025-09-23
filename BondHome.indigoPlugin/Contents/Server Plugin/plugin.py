#! /usr/bin/env python
# -*- coding: utf-8 -*-

import indigo  # noqa
import time
import logging
import requests
import json
import socket
from bondhome import BondHome
from zeroconf import IPVersion, ServiceBrowser, ServiceStateChange, Zeroconf

"""Bond type enumeration."""
import re
from enum import Enum

regexes = {
    "bridge_snowbird": r"^[A-C]\w*$",
    "bridge_zermatt": r"^Z(Z|X)\w*$",
    "bridge_pro": r"^ZP\w*$",
    "sbb_lights": r"^T\w*$",
    "sbb_ceiling_fan": r"^K\w*$",
    "sbb_plug": r"^P\w*$",
}


class BondType(Enum):
    """Bond type enumeration."""

    BRIDGE_SNOWBIRD = "bridge_snowbird"
    BRIDGE_ZERMATT = "bridge_zermatt"
    BRIDGE_PRO = "bridge_pro"
    SBB_LIGHTS = "sbb_lights"
    SBB_CEILING_FAN = "sbb_ceiling_fan"
    SBB_PLUG = "sbb_plug"

    def is_sbb(self) -> bool:
        """Checks if BondType is a Smart by Bond product."""
        return self.value.startswith("sbb_")

    def is_bridge(self) -> bool:
        """Checks if BondType is a Bond Bridge/Bond Bridge Pro."""
        return self.value.startswith("bridge_")

    @classmethod
    def from_serial(cls, serial: str):
        """Returns a BondType for a serial number"""
        for (bond_type, regex) in regexes.items():
            if re.search(regex, serial):
                return cls(bond_type)
        return None

    @staticmethod
    def is_sbb_from_serial(serial: str) -> bool:
        """Checks if specified Bond serial number is a Smart by Bond product."""
        bond_type = BondType.from_serial(serial)
        if bond_type:
            return bond_type.is_sbb()
        return False

    @staticmethod
    def is_bridge_from_serial(serial: str) -> bool:
        """Checks if specified Bond serial number is a Bond Bridge."""
        bond_type = BondType.from_serial(serial)
        if bond_type:
            return bond_type.is_bridge()
        return False


class DeviceType(Enum):
    """Bond Device type enumeration."""

    CEILING_FAN = "CF"
    MOTORIZED_SHADES = "MS"
    FIREPLACE = "FP"
    AIR_CONDITIONER = "AC"
    GARAGE_DOOR = "GD"
    BIDET = "BD"
    LIGHT = "LT"
    GENERIC_DEVICE = "GX"

    @staticmethod
    def is_fan(device_type: str) -> bool:
        """Checks if specified device type is a fan."""
        return device_type == DeviceType.CEILING_FAN

    @staticmethod
    def is_shades(device_type: str) -> bool:
        """Checks if specified device type is shades."""
        return device_type == DeviceType.MOTORIZED_SHADES

    @staticmethod
    def is_fireplace(device_type: str) -> bool:
        """Checks if specified device type is fireplace."""
        return device_type == DeviceType.FIREPLACE

    @staticmethod
    def is_air_conditioner(device_type: str) -> bool:
        """Checks if specified device type is air conditioner."""
        return device_type == DeviceType.AIR_CONDITIONER

    @staticmethod
    def is_garage_door(device_type: str) -> bool:
        """Checks if specified device type is garage door."""
        return device_type == DeviceType.GARAGE_DOOR

    @staticmethod
    def is_bidet(device_type: str) -> bool:
        """Checks if specified device type is bidet."""
        return device_type == DeviceType.BIDET

    @staticmethod
    def is_light(device_type: str) -> bool:
        """Checks if specified device type is light."""
        return device_type == DeviceType.LIGHT

    @staticmethod
    def is_generic(device_type: str) -> bool:
        """Checks if specified device type is generic."""
        return device_type == DeviceType.GENERIC_DEVICE


################################################################################
class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)
        self.logLevel = int(self.pluginPrefs.get("logLevel", logging.INFO))
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(f"logLevel = {self.logLevel}")

        self.found_devices = {}         # zeroconf discovered devices

        self.bond_bridges = {}          # dict of bridge devices, keyed by BondID, value id BondHome object
        self.bond_devices = {}          # dict of "client" devices, keyed by (bond) device_ID, value is Indigo device.id
        self.deferred_start = {}        # devices that need to be started after the bridges are all running
        self.known_devices = {}         # nested dict of client devices, keyed by BondID then device_ID, value is dict returned by get_device()

    def startup(self):
        self.logger.info("Starting Bond Home plugin")
        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        services = ["_bond._tcp.local."]
        browser = ServiceBrowser(zeroconf, services, handlers=[self.on_service_state_change])

    def on_service_state_change(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        self.logger.debug(f"Service {name} of type {service_type} state changed: {state_change}")
        if state_change in [ServiceStateChange.Added, ServiceStateChange.Updated]:
            if service_type == "_bond._tcp.local." and name not in self.found_devices:
                info = zeroconf.get_service_info(service_type, name)
                ip_address = ".".join([f"{x}" for x in info.addresses[0]])  # address as string (xx.xx.xx.xx)
                try:
                    bridge = BondHome(ip_address)
                    bridge_version = bridge.get_bridge_version()
                    del bridge
                except Exception as err:
                    self.logger.debug(f"on_service_state_change: Error creating BondHome object for {name}: {err}")
                    return
                self.logger.debug(f"Device {info.server}: version info: {bridge_version}")
                self.found_devices[info.server] = bridge_version

        elif state_change is ServiceStateChange.Removed:
            if service_type == "_bond._tcp.local." and name in self.found_devices:
                del self.found_devices[name]

        self.logger.debug(f"Found Bond Bridges: {self.found_devices}")

        ########################################

    def validate_prefs_config_ui(self, valuesDict):
        self.logger.debug(f"validate_prefs_config_ui: valuesDict = {valuesDict}")
        errorsDict = indigo.Dict()
        valid = True

        logLevel = int(valuesDict.get("logLevel", logging.INFO))
        if logLevel < logging.DEBUG or logLevel > logging.CRITICAL:
            errorsDict["logLevel"] = "Log Level must be between 10 (DEBUG) and 50 (CRITICAL)"
            valid = False

        return valid, valuesDict, errorsDict

    def closed_prefs_config_ui(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")

        ########################################

    def get_device_factory_ui_values(self, dev_id_list):
        self.logger.debug(f"get_device_factory_ui_values: {list(dev_id_list)=}")

        values_dict = indigo.Dict()
        error_msg_dict = indigo.Dict()

        # # change default to creating devices if there's at least one bridge defined
        #
        # if len(self.bond_bridges):
        #     values_dict["deviceType"] = "bondDevice"
        #     values_dict['bridge'] = list(self.bond_bridges.keys())[0]

        self.logger.debug(f"get_device_factory_ui_values: {dict(values_dict)=}")
        return values_dict, error_msg_dict

    def validate_device_factory_ui(self, values_dict, dev_id_list):
        self.logger.threaddebug(f"validate_device_factory_ui: {dev_id_list=}, {values_dict=}")
        errors_dict = indigo.Dict()
        valid = True

        if values_dict["deviceType"] in ["bondBridge", "bondSmart"]:
            if values_dict["address"] == "":
                errors_dict["bridge"] = "Device IP Address Required"
                self.logger.warning("validate_device_factory_ui - Device IP Address Required")
                valid = False
            if values_dict["token"] == "":
                errors_dict["token"] = "Device Token Required"
                self.logger.warning("validate_device_factory_ui - Device Token Required")
                valid = False

        # add more validation as needed

        return valid, values_dict, errors_dict

    def closed_device_factory_ui(self, values_dict, user_cancelled, dev_id_list):

        if user_cancelled:
            self.logger.debug("closed_device_factory_ui: user cancelled")
            return

        self.logger.debug(f"closed_device_factory_ui: {dict(values_dict)=}, {dev_id_list=}")

        if values_dict["deviceType"] in ["bondBridge", "bondSmart"]:

            bridge_info = self.found_devices.get(values_dict['address'])

            self.logger.debug(f"{BondType.from_serial(bridge_info['bondid'])}")

            stateList = [
                {'key': 'fw_ver', 'value': bridge_info['fw_ver']},
                {'key': 'fw_date', 'value': bridge_info['fw_date']},
                {'key': 'uptime_s', 'value': bridge_info['uptime_s']},
                {'key': 'make', 'value': bridge_info['make']},
                {'key': 'model', 'value': bridge_info['model']},
                {'key': 'bondid', 'value': bridge_info['bondid']},
            ]

            dev = indigo.device.create(indigo.kProtocol.Plugin, address=address, deviceTypeId="bondBridge")
            dev.model = "Bond Bridge"
            dev.name = f"Bond Bridge ({dev.id})"
            dev.replaceOnServer()

            self.logger.info(f"Created Bond Bridge '{dev.name}'")

        elif values_dict["deviceType"] == "bondDevice":

            dev = indigo.device.create(indigo.kProtocol.Plugin, address=values_dict['bond_device_id'], deviceTypeId="bondDevice")

        return

    ########################################
    # callback for state list changes, called from stateListOrDisplayStateIdChanged()
    ########################################

    def getDeviceStateList(self, device):

        state_list = indigo.PluginBase.getDeviceStateList(self, device)
        device_type = device.pluginProps.get("device_type", None)

        if device_type == 'bondBridge':
            state_list.append(self.getDeviceStateDictForStringType("fw_ver", "Firmware Version", "Firmware Version"))
            state_list.append(self.getDeviceStateDictForStringType("fw_date", "Firmware Date", "Firmware Date"))
            state_list.append(self.getDeviceStateDictForStringType("uptime_s", "Uptime", "Uptime"))
            state_list.append(self.getDeviceStateDictForStringType("make", "Make", "Make"))
            state_list.append(self.getDeviceStateDictForStringType("model", "Model", "Model"))
            state_list.append(self.getDeviceStateDictForStringType("bondid", "Bond ID", "Bond ID"))
            state_list.append(self.getDeviceStateDictForStringType("name", "Name", "Name"))
            state_list.append(self.getDeviceStateDictForStringType("location", "Location", "Location"))

        elif device_type == 'bondDevice':

            if device.pluginProps.get("bond_type") == "FP":
                flame_state = self.getDeviceStateDictForNumberType("flame", "Flame", "Flame")
                state_list.append(flame_state)

        return state_list

        ########################################

    def deviceStartComm(self, device):
        self.logger.info(f"{device.name}: Starting {device.deviceTypeId} Device {device.id}")

        # ensure device definition is up to date
        device.stateListOrDisplayStateIdChanged()

        if device.deviceTypeId == "bondBridge":
            try:
                # using hostname when creating the Bond device causes all operations to be very slow, so use the IP address
                bridge = BondHome(socket.gethostbyname(device.pluginProps['address']), device.pluginProps['token'])

            except Exception as err:
                self.logger.debug(f"{device.name}: BondHome __init__ error: {err}")
                device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                return

            try:
                version = bridge.get_bridge_version()
            except Exception as err:
                self.logger.debug(f"{device.name}: Error in get_bridge_version(): {err}")
                return

            self.logger.debug(f"{device.name}: Bond version: {version}")
            stateList = [
                {'key': 'fw_ver', 'value': version['fw_ver']},
                {'key': 'fw_date', 'value': version['fw_date']},
                {'key': 'uptime_s', 'value': version['uptime_s']},
                {'key': 'make', 'value': version['make']},
                {'key': 'model', 'value': version['model']},
                {'key': 'bondid', 'value': version['bondid']},
            ]
            device.updateStatesOnServer(stateList)

            # Smart by Bond devices don't implement get_bridge_info(), so skip this if not an actual Bond device
            if version['make'] == 'Olibra':
                try:
                    info = bridge.get_bridge_info()
                except Exception as err:
                    self.logger.debug(f"{device.name}: Error in get_bridge_info(): {err}")
                else:
                    self.logger.debug(f"{device.name}: Bond info: {info}")
                    stateList = [
                        {'key': 'name', 'value': info['name']},
                        {'key': 'location', 'value': info['location']},
                        {'key': 'brightnessLevel', 'value': info['bluelight']}
                    ]
                    device.updateStatesOnServer(stateList)

            bondID = version['bondid']
            self.bond_bridges[bondID] = bridge

            # get all the devices the bridge knows about
            self.known_devices[bondID] = {}
            for bond_dev in bridge.get_device_list():
                self.known_devices[bondID][bond_dev] = bridge.get_device(bond_dev)
            self.logger.debug(f"{device.name}: known_devices:\n{self.known_devices}")

            # start up the BPUP socket connection
            bridge.udp_start(self.receiveBPUP)

        elif device.deviceTypeId == "bondSmart":
            try:
                # using hostname when creating the Bond device causes all operations to be very slow, so use the IP address
                bridge = BondHome(socket.gethostbyname(device.pluginProps['address']), device.pluginProps['token'])

            except Exception as err:
                self.logger.debug(f"{device.name}: BondHome __init__ error: {err}")
                device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                return

            try:
                version = bridge.get_bridge_version()
            except Exception as err:
                self.logger.debug(f"{device.name}: Error in get_bridge_version(): {err}")
                return

            self.logger.debug(f"{device.name}: Smart by Bond version: {version}")
            stateList = [
                {'key': 'fw_ver', 'value': version['fw_ver']},
                {'key': 'fw_date', 'value': version['fw_date']},
                {'key': 'uptime_s', 'value': version['uptime_s']},
                {'key': 'make', 'value': version['make']},
                {'key': 'model', 'value': version['model']},
                {'key': 'bondid', 'value': version['bondid']},
            ]
            device.updateStatesOnServer(stateList)

            bondID = version['bondid']
            self.bond_bridges[bondID] = bridge

            # start up the BPUP socket connection
            bridge.udp_start(self.receiveBPUP)

            # get all the devices the bridge knows about
            self.known_devices[bondID] = {}
            for bond_dev in bridge.get_device_list():
                self.known_devices[bondID][bond_dev] = bridge.get_device(bond_dev)
            self.logger.debug(f"{device.name}: known_devices:\n{self.known_devices}")

        elif device.deviceTypeId == "bondDevice":
            bridge_id = device.pluginProps['bridge']
            if bridge_id not in self.bond_bridges:
                self.logger.debug(f"{device.name}: Deferring device start until bridge is started")
                self.deferred_start[device.address] = device.id  # save the device info, do startup later after bridges are started
                return
            else:
                self.do_device_startup(device)
        else:
            self.logger.error(f"{device.name}: Unknown device type: {device.deviceTypeId}")

    # Undocumented API - runs after all devices have been started.  Actually, it's the super._postStartup() call that starts the devices.
    def _postStartup(self):
        super(Plugin, self)._postStartup()  # noqa
        self.logger.debug(f"_postStartup: starting deferred devices: {self.deferred_start}")
        for device_id in self.deferred_start.values():
            self.do_device_startup(indigo.devices[device_id])

    def do_device_startup(self, device):

        bridge_id = device.pluginProps['bridge']
        if bridge_id not in self.bond_bridges:
            self.logger.warning(f"{device.name}: Can't start device, bridge not active: {bridge_id}")
            return

        self.logger.debug(f"{device.name}: do_device_startup: {device.deviceTypeId} ({device.address}) with Bridge {bridge_id}")

        bridge = self.bond_bridges[bridge_id]
        dev_info = self.known_devices[bridge_id].get(device.address, None)
        if not dev_info:
            self.logger.debug(f"{device.name}: do_device_startup: no device info for {device.address}")
            return

        self.bond_devices[device.address] = device.id
        self.logger.debug(f"{device.name}: Device Info: {dev_info}")
        bond_type = dev_info.get('type', 'UN')

        if dev_info and not device.pluginProps.get('bond_type', None):
            self.logger.debug(f"{device.name}: Updating Device info:\n{dev_info}")
            device.subModel = bond_device_types.get(bond_type, f"Unknown Device ({bond_type})")
            device.replaceOnServer()

            newProps = device.pluginProps
            newProps.update({'bond_type': bond_type})
            device.replacePluginPropsOnServer(newProps)

        states = bridge.get_device_state(device.address)
        self.logger.debug(f"{device.name}: Device states: {states}")
        device.stateListOrDisplayStateIdChanged()

        if bond_type == 'GX':
            device.updateStateOnServer(key='onOffState', value=bool(states['power']))

        elif bond_type == 'FP':
            device.updateStateOnServer(key='onOffState', value=bool(states['power']))
            device.updateStateOnServer(key='flame', value=states.get('flame', 0))

        elif bond_type == 'MS':
            device.updateStateOnServer(key='onOffState', value=bool(states['open']))

    def deviceStopComm(self, device):
        self.logger.info(f"{device.name}: Stopping {device.deviceTypeId} Device {device.id}")

        if device.deviceTypeId == "bondBridge":
            bondID = device.states['bondid']
            if bondID in self.bond_bridges:
                self.bond_bridges[bondID].udp_stop()
                del self.bond_bridges[bondID]

        elif device.deviceTypeId == "smartBond":
            bondID = device.states['bondid']
            if bondID in self.bond_bridges:
                del self.bond_bridges[bondID]

        elif device.deviceTypeId == "bondDevice":
            if device.address in self.bond_devices:
                del self.bond_devices[device.address]

        else:
            self.logger.error(f"{device.name}: deviceStopComm: Unknown device type: {device.deviceTypeId}")

    ########################################
    # Process callback from BondHome devices
    ########################################

    def receiveBPUP(self, data):
        self.logger.threaddebug(f"receiveBPUP: {data}")

        bondID = data.get('B', None)
        self.logger.threaddebug(f"Bond Bridge id: {bondID}")
        if not bondID:
            self.logger.warning(f"receiveBPUP: no Bond Bridge ID in {data}")
            return

        deviceID = data.get('id', None)
        self.logger.threaddebug(f"Bond device id: {deviceID}")
        if not deviceID:
            self.logger.warning(f"receiveBPUP: no Bond device ID in {data}")
            return

        iDevID = self.bond_devices.get(deviceID, None)
        self.logger.threaddebug(f"Indigo device id: {iDevID}")
        if not iDevID:
            self.logger.threaddebug(f"receiveBPUP: no Indigo device for {deviceID}")
            return

        device = indigo.devices.get(iDevID, None)
        self.logger.threaddebug(f"{device.name}: Device ID: {device.id}")
        if not device:
            self.logger.warning(f"receiveBPUP: No Indigo device for {iDevID}")
            return

        bond_type = device.pluginProps['bond_type']
        self.logger.threaddebug(f"{device.name}: bond_type: {bond_type}")
        if bond_type in ['CF', 'GX']:
            state = data.get('b').get('power')
            device.updateStateOnServer(key='onOffState', value=bool(state))

        elif bond_type == 'FP':
            state = data.get('b').get('power')
            device.updateStateOnServer(key='onOffState', value=bool(state))
            flame = data.get('b').get('flame')
            device.updateStateOnServer(key='flame', value=flame)

        elif bond_type == 'MS':
            state = data.get('b').get('open')
            device.updateStateOnServer(key='onOffState', value=bool(state))

    ########################################
    #
    # callbacks from device creation UI
    #
    ########################################

    def found_bridge_list(self, filter=None, values_dict=None, type_id=0, target_id=0):
        self.logger.debug(f"found_bridge_list: {filter=}, {type_id=}, {target_id=}, {values_dict=}")
        retList = [("Enter Manual IP address", "Discovered Bridge Devices:")]
        if values_dict.get('deviceType') == "bondBridge":
            for name, data in self.found_devices.items():
                if BondType.is_bridge_from_serial(data['bondid']):
                    retList.append((data.get('hostname'), f"{data.get('make')} {data.get('model')} ({data.get('bondid')} @ {data.get('ip_address')})"))
        elif values_dict.get('deviceType') == "smartBond":
            for name, data in self.found_devices.items():
                if BondType.is_sbb_from_serial(data['bondid']):
                    retList.append((data.get('hostname'), f"{data.get('make')} {data.get('model')} ({data.get('bondid')} @ {data.get('ip_address')})"))
        self.logger.debug(f"found_bridge_list: {retList=}")
        return retList

    def menuChanged(self, values_dict, type_id, dev_id):
        self.logger.debug(f"menuChanged: {type_id=}, {dev_id=}, values_dict = {values_dict}")
        if values_dict.get('deviceType') == "bondBridge" or values_dict.get('deviceType') == "smartBond":
            values_dict['address'] = values_dict['found_bridge_list']
        self.logger.debug(f"menuChanged: {values_dict=}")
        return values_dict

    def get_bridge_list(self, filter="", values_dict=None, type_id="", target_id=0):
        self.logger.debug(f"get_bridge_list: {target_id=}, {target_id=}, {values_dict=}")
        ret_list = []
        for device in indigo.devices.iter("self.bondBridge"):
            ret_list.append((device.states['bondid'], device.name))
        ret_list.sort(key=lambda tup: tup[1])
        self.logger.debug(f"get_bridge_list: {ret_list=}")
        return ret_list

    def get_device_list(self, filter="", values_dict=None, type_id="", target_id=0):
        self.logger.debug(f"get_device_list: {target_id=}, {type_id=}, {values_dict=}")
        ret_list = []
        bind_id = values_dict.get("bridge", None)
        if not bind_id:
            return ret_list
        for dev_key, dev_info in self.known_devices[bind_id].items():
            ret_list.append((dev_key, dev_info["name"]))
        ret_list.sort(key=lambda tup: tup[1])
        self.logger.debug(f"get_device_list: {ret_list=}")
        return ret_list

    def get_action_list(self, filter="", values_dict=None, type_id="", target_id=0):
        self.logger.debug(f"get_action_list: {target_id=}, {type_id=}, {values_dict=}")
        ret_list = []
        bond_id = values_dict.get("bridge", None)
        if not bond_id:
            return ret_list
        if target_id:
            try:
                address = indigo.devices[target_id].address
            except (Exception,):
                address = None
            if not address:
                address = values_dict.get("address", None)
        elif values_dict.get("device", None):
            address = values_dict.get('device', None)
        else:
            address = None
        if not address:
            return ret_list
        try:
            dev_info = self.known_devices[bond_id][address]
        except (Exception,):
            return ret_list

        for cmd in dev_info['actions']:
            ret_list.append((cmd, cmd))
        self.logger.debug(f"get_action_list: {ret_list=}")
        return ret_list

    ########################################
    # Relay Action callback
    ########################################
    def action_control_device(self, plugin_action, device):
        self.logger.debug(f"{device.name}: action_control_device pluginAction:{plugin_action}")

        if plugin_action.deviceAction == indigo.kDeviceAction.TurnOn:
            if device.deviceTypeId == "bondBridge" and device.states['make'] == 'Olibra':
                bondID = device.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": 255})
                device.updateStateOnServer(key='brightnessLevel', value=100)
            elif device.deviceTypeId == "bondDevice":
                bridge = self.bond_bridges[device.pluginProps["bridge"]]
                try:
                    parameter = indigo.activePlugin.substitute(device.pluginProps["on_parameter"])
                except Exception as err:
                    parameter = ""
                if len(parameter):
                    payload = {"argument": int(parameter)}
                else:
                    payload = {}
                bridge.device_action(device.address, device.pluginProps["on_command"], payload)
            else:
                self.logger.warning(f"action_control_device: Device type {device.deviceTypeId} does not support On command")

        elif plugin_action.deviceAction == indigo.kDeviceAction.TurnOff:
            if device.deviceTypeId == "bondBridge" and device.states['make'] == 'Olibra':
                bondID = device.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": 0})
                device.updateStateOnServer(key='brightnessLevel', value=0)
            elif device.deviceTypeId == "bondDevice":
                bridge = self.bond_bridges[device.pluginProps["bridge"]]
                try:
                    parameter = indigo.activePlugin.substitute(device.pluginProps["off_parameter"])
                except Exception as err:
                    parameter = ""
                if len(parameter):
                    payload = {"argument": int(parameter)}
                else:
                    payload = {}
                bridge.device_action(device.address, device.pluginProps["off_command"], payload)
            else:
                self.logger.warning(f"action_control_device: Device type {device.deviceTypeId} does not support Off command")

        elif plugin_action.deviceAction == indigo.kDeviceAction.Toggle:
            if device.deviceTypeId == "bondBridge" and device.states['make'] == 'Olibra':
                bondID = device.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": 0})
                device.updateStateOnServer(key='brightnessLevel', value=0)
            elif device.deviceTypeId == "bondDevice":
                bridge = self.bond_bridges[device.pluginProps["bridge"]]
                try:
                    parameter = indigo.activePlugin.substitute(device.pluginProps["off_parameter"])
                except Exception as err:
                    parameter = ""
                if len(parameter):
                    payload = {"argument": int(parameter)}
                else:
                    payload = {}
                bridge.device_action(device.address, device.pluginProps["off_command"], payload)
            else:
                self.logger.warning(f"action_control_device: Device type {device.deviceTypeId} does not support Toggle command")

        elif plugin_action.deviceAction == indigo.kDeviceAction.SetBrightness:
            if device.deviceTypeId == "bondBridge" and device.states['make'] == 'Olibra':
                level = int(action.actionValue * 2.55)  # bluelight scale is 0-255
                bondID = device.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                device.updateStateOnServer(key='brightnessLevel', value=action.actionValue)
            else:
                self.logger.warning(f"action_control_device: Device type {device.deviceTypeId} does not support SetBrightness command")

        elif plugin_action.deviceAction == indigo.kDeviceAction.BrightenBy:
            newBrightness = device.brightness + action.actionValue
            if newBrightness > 100:
                newBrightness = 100
            if device.deviceTypeId == "bondBridge" and device.states['make'] == 'Olibra':
                level = int(newBrightness * 2.55)  # bluelight scale is 0-255
                bondID = device.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                device.updateStateOnServer(key='brightnessLevel', value=newBrightness)
            else:
                self.logger.warning(f"action_control_device: Device type {device.deviceTypeId} does not support BrightenBy command")

        elif plugin_action.deviceAction == indigo.kDeviceAction.DimBy:
            newBrightness = device.brightness - action.actionValue
            if newBrightness < 0:
                newBrightness = 0
            if device.deviceTypeId == "bondBridge" and device.states['make'] == 'Olibra':
                level = int(newBrightness * 2.55)  # bluelight scale is 0-255
                bondID = device.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                device.updateStateOnServer(key='brightnessLevel', value=newBrightness)
            else:
                self.logger.warning(f"action_control_device: Device type {device.deviceTypeId} does not support DimBy command")

    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ########################################

    def get_action_config_ui_values(self, action_props, type_id, dev_id):
        self.logger.debug(f"get_action_config_ui_values, {type_id=}, {dev_id=}, {action_props=}")
        values_dict = action_props
        error_msg_dict = indigo.Dict()

        self.logger.debug(f"get_action_config_ui_values, bond_bridges = {self.bond_bridges}")

        # Preload the first bridge device, if not already specified
        if not values_dict.get('bridge', None) and len(self.bond_bridges):
            values_dict['bridge'] = list(self.bond_bridges.keys())[0]
        return values_dict, error_msg_dict

    def doDeviceAction(self, pluginAction):
        self.logger.debug(f"doDeviceAction, pluginAction = {pluginAction}")
        bridge = self.bond_bridges[pluginAction.props["bridge"]]
        argument = indigo.activePlugin.substitute(pluginAction.props["argument"])
        if len(argument):
            payload = {"argument": int(argument)}
        else:
            payload = {}
        bridge.device_action(pluginAction.props["device"], pluginAction.props["command"], payload)

    def updateStateBeliefAction(self, pluginAction):
        self.logger.debug(f"updateStateBeliefAction, pluginAction = {pluginAction}")
        bridge = self.bond_bridges[pluginAction.props["bridge"]]
        state = pluginAction.props["state"]
        value = indigo.activePlugin.substitute(pluginAction.props["value"])

        if len(state) and len(value):
            payload = {state: value}
        else:
            return

        bridge.update_device_state(pluginAction.props["device"], pluginAction.props["command"], payload)

    def setCommandRepeatAction(self, pluginAction):
        self.logger.threaddebug(f"setCommandRepeatAction: pluginAction: {pluginAction}")

        bridge = self.bond_bridges[pluginAction.props["bridge"]]
        device = pluginAction.props["device"]
        command = pluginAction.props["command"]
        try:
            repeats = int(indigo.activePlugin.substitute(pluginAction.props["repeats"]))
        except ValueError:
            self.logger.warning(f"setCommandRepeatAction: invalid repeat value: {pluginAction.props['repeats']}")
            return False

        # now to find the action_id that goes with that command.  There's a glaring hole in the API in that the
        # action list returned for the device is only names, not action_ids.

        cmd_id = None
        command_list = bridge.get_device_command_list(device)
        for cmd_id in command_list:
            cmd_info = bridge.get_device_command(device, cmd_id)
            if cmd_info['action'] == command:
                break

        # send the change command and check the result
        payload = {"reps": int(repeats)}
        result = bridge.set_device_command_signal(device, cmd_id, payload)
        if result['reps'] != repeats:
            self.logger.warning("setCommandRepeatAction: setting repeat value failed")
        else:
            self.logger.debug(f"setCommandRepeatAction: repeat value = {result['reps']}")

    ########################################
    # Plugin Menu object callbacks
    ########################################

    def dumpConfig(self):
        self.logger.info(f"\n{json.dumps(self.found_devices, sort_keys=True, indent=4, separators=(',', ': '))}")
        self.logger.info(f"\n{json.dumps(self.known_devices, sort_keys=True, indent=4, separators=(',', ': '))}")
        return True
