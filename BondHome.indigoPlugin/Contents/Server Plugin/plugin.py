#! /usr/bin/env python
# -*- coding: utf-8 -*-
from ipaddress import ip_address

import indigo  # noqa
import time
import logging
import requests
import json
import socket
from bondhome import BondHome
from zeroconf import IPVersion, ServiceBrowser, ServiceStateChange, Zeroconf

bond_device_types = {
    'CF': "Ceiling Fan",
    'FP': "Fireplace",
    'MS': "Motorized Shades",
    'LT': "Light",
    'BD': "Bidet",
    'GX': "Generic Device",
    'UN': "Unknown Device"
}


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
        self.logger.info("Starting Bond Bridge")
        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        services = ["_bond._tcp.local."]
        browser = ServiceBrowser(zeroconf, services, handlers=[self.on_service_state_change])

    def on_service_state_change(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        self.logger.debug(f"Service {name} of type {service_type} state changed: {state_change}")
        info = zeroconf.get_service_info(service_type, name)
        self.logger.debug(f"Service info: {info}")
        if state_change in [ServiceStateChange.Added, ServiceStateChange.Updated]:
            if service_type == "_bond._tcp.local." and name not in self.found_devices:
                ipaddr = ".".join([f"{x}" for x in info.addresses[0]])  # address as string (xx.xx.xx.xx)
                try:
                    bridge = BondHome(ipaddr, "")
                    bridge_version = bridge.get_bridge_version()
                    del bridge
                except Exception as err:
                    self.logger.debug(f"Error creating BondHome object for {name}: {err}")
                    return
                self.found_devices[name] = {"hostname": info.server, "ip_address": ipaddr, "make": bridge_version['make'], "model": bridge_version['model'], "bondid": bridge_version['bondid']}

        elif state_change is ServiceStateChange.Removed:
            if service_type == "_bond._tcp.local." and name in self.found_devices:
                del self.found_devices[name]

        self.logger.debug(f"Found Bond Bridges: {self.found_devices}")

        ########################################

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")

        ########################################

    def getDeviceConfigUiValues(self, pluginProps, typeId, devId):
        self.logger.debug(f"getDeviceConfigUiValues, typeId = {typeId}, devId = {devId}, pluginProps = {pluginProps}")
        valuesDict = pluginProps
        errorMsgDict = indigo.Dict()

        # Preload the first bridge for any non-bridge device, if not already specified
        if typeId == 'bondDevice' and not valuesDict.get('bridge', None) and len(self.bond_bridges):
            valuesDict['bridge'] = list(self.bond_bridges.keys())[0]
        return valuesDict, errorMsgDict

        ########################################

    def getDeviceFactoryUiValues(self, devIdList):
        self.logger.debug(f"getDeviceFactoryUiValues: devIdList = {devIdList}")

        valuesDict = indigo.Dict()
        errorMsgDict = indigo.Dict()

        # change default to creating devices if there's at least one bridge defined

        if len(self.bond_bridges) > 0:
            valuesDict["deviceType"] = "bondDevice"
            valuesDict["bridge"] = self.bond_bridges[list(self.bond_bridges.keys())[0]].devID

        return valuesDict, errorMsgDict

    def validateDeviceFactoryUi(self, valuesDict, devIdList):
        self.logger.threaddebug(f"validateDeviceFactoryUi: valuesDict = {valuesDict}, devIdList = {devIdList}")
        errorsDict = indigo.Dict()
        valid = True

        if valuesDict["deviceType"] == "bondBridge":
            if valuesDict["ip_address"] == "":
                errorsDict["bridge"] = "No Bond Bridge Specified"
                self.logger.warning("validateDeviceFactoryUi - No Bond Bridge Specified")
                valid = False

        elif valuesDict["deviceType"] == "bondRelay":
            if valuesDict["account"] == 0:
                errorsDict["account"] = "No Ecobee Account Specified"
                self.logger.warning("validateDeviceFactoryUi - No Ecobee Account Specified")
                valid = False

            if len(valuesDict["address"]) == 0:
                errorsDict["address"] = "No Sensor Specified"
                self.logger.warning("validateDeviceFactoryUi - No Sensor Specified")
                valid = False

        elif valuesDict["deviceType"] == "bondDimmer":
            if valuesDict["account"] == 0:
                errorsDict["account"] = "No Ecobee Account Specified"
                self.logger.warning("validateDeviceFactoryUi - No Ecobee Account Specified")
                valid = False

            if len(valuesDict["address"]) == 0:
                errorsDict["address"] = "No Sensor Specified"
                self.logger.warning("validateDeviceFactoryUi - No Sensor Specified")
                valid = False

        return valid, valuesDict, errorsDict

    def closedDeviceFactoryUi(self, valuesDict, userCancelled, devIdList):

        if userCancelled:
            self.logger.debug("closedDeviceFactoryUi: user cancelled")
            return

        self.logger.debug(f"closedDeviceFactoryUi: valuesDict =\n{valuesDict}\ndevIdList =\n{devIdList}")

        if valuesDict["deviceType"] == "bondBridge":

            address = valuesDict["ip_address"]

            dev = indigo.device.create(indigo.kProtocol.Plugin, address=address, deviceTypeId="bondBridge")
            dev.model = "Bond Bridge"
            dev.name = f"Bond Bridge ({dev.id})"
            dev.replaceOnServer()

            self.logger.info(f"Created Bond Bridge '{dev.name}'")

        elif valuesDict["deviceType"] == "bondRelay":

            address = valuesDict["address"]

            ecobee = self.ecobee_accounts[int(valuesDict["account"])]
            thermostat = ecobee.thermostats.get(address)
            name = f"Ecobee {thermostat.get('name')}"
            device_type = thermostat.get('modelNumber', 'Unknown')

            dev = indigo.device.create(indigo.kProtocol.Plugin, address=address, name=name, deviceTypeId="EcobeeThermostat")
            dev.model = "Ecobee Thermostat"
            dev.subModel = ECOBEE_MODELS.get(device_type, 'Unknown')
            dev.replaceOnServer()

            self.logger.info(f"Created EcobeeThermostat device '{dev.name}'")

            newProps = dev.pluginProps
            newProps["account"] = valuesDict["account"]
            newProps["holdType"] = valuesDict["holdType"]
            newProps["device_type"] = device_type
            newProps["NumHumidityInputs"] = 1
            newProps["ShowCoolHeatEquipmentStateUI"] = True

            dev.replacePluginPropsOnServer(newProps)

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

    def found_device_list(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        self.logger.debug(f"found_device_list: filter = {filter}, typeId = {typeId}, targetId = {targetId}, valuesDict = {valuesDict}")
        retList = [("Enter Manual IP address", "Discovered Devices:")]
        if typeId == "bondBridge":
            for name, data in self.found_devices.items():
                retList.append((data['hostname'], f"{data['make']} {data['model']} ({data['bondid']} @ {data['ip_address']})"))
        self.logger.debug(f"found_device_list: retList = {retList}")
        return retList

    def menuChanged(self, valuesDict, typeId, devId):
        self.logger.debug(f"menuChanged: typeId = {typeId}, devId = {devId}, valuesDict = {valuesDict}")
        if typeId == "bondBridge" or typeId == "smartBond":
            valuesDict['address'] = valuesDict['found_list']
        return valuesDict

    @staticmethod
    def get_bridge_list(filter="", valuesDict=None, typeId="", targetId=0):
        retList = []
        for dev in indigo.devices.iter("self.bondBridge"):
            retList.append((dev.states['bondid'], dev.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_device_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        retList = []
        bondid = valuesDict.get("bridge", None)
        if not bondid:
            return retList
        for dev_key, dev_info in self.known_devices[bondid].items():
            retList.append((dev_key, dev_info["name"]))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_action_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        retList = []
        bondid = valuesDict.get("bridge", None)
        if not bondid:
            return retList
        if targetId:
            try:
                address = indigo.devices[targetId].address
            except (Exception,):
                address = None
            if not address:
                address = valuesDict.get("address", None)
        elif valuesDict.get("device", None):
            address = valuesDict.get('device', None)
        else:
            address = None
        if not address:
            return retList
        try:
            dev_info = self.known_devices[bondid][address]
        except (Exception,):
            return retList

        for cmd in dev_info['actions']:
            retList.append((cmd, cmd))
        return retList

    ########################################
    # Relay Action callback
    ########################################
    def actionControlDevice(self, pluginAction, device):
        self.logger.debug(f"{device.name}: actionControlDevice pluginAction:{pluginAction}")

        if pluginAction.deviceAction == indigo.kDeviceAction.TurnOn:
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
                self.logger.warning(f"actionControlDevice: Device type {device.deviceTypeId} does not support On command")

        elif pluginAction.deviceAction == indigo.kDeviceAction.TurnOff:
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
                self.logger.warning(f"actionControlDevice: Device type {device.deviceTypeId} does not support Off command")

        elif pluginAction.deviceAction == indigo.kDeviceAction.Toggle:
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
                self.logger.warning(f"actionControlDevice: Device type {device.deviceTypeId} does not support Toggle command")

        elif pluginAction.deviceAction == indigo.kDeviceAction.SetBrightness:
            if device.deviceTypeId == "bondBridge" and device.states['make'] == 'Olibra':
                level = int(action.actionValue * 2.55)  # bluelight scale is 0-255
                bondID = device.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                device.updateStateOnServer(key='brightnessLevel', value=action.actionValue)
            else:
                self.logger.warning(f"actionControlDevice: Device type {device.deviceTypeId} does not support SetBrightness command")

        elif pluginAction.deviceAction == indigo.kDeviceAction.BrightenBy:
            newBrightness = device.brightness + action.actionValue
            if newBrightness > 100:
                newBrightness = 100
            if device.deviceTypeId == "bondBridge" and device.states['make'] == 'Olibra':
                level = int(newBrightness * 2.55)  # bluelight scale is 0-255
                bondID = device.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                device.updateStateOnServer(key='brightnessLevel', value=newBrightness)
            else:
                self.logger.warning(f"actionControlDevice: Device type {device.deviceTypeId} does not support BrightenBy command")

        elif pluginAction.deviceAction == indigo.kDeviceAction.DimBy:
            newBrightness = device.brightness - action.actionValue
            if newBrightness < 0:
                newBrightness = 0
            if device.deviceTypeId == "bondBridge" and device.states['make'] == 'Olibra':
                level = int(newBrightness * 2.55)  # bluelight scale is 0-255
                bondID = device.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                device.updateStateOnServer(key='brightnessLevel', value=newBrightness)
            else:
                self.logger.warning(f"actionControlDevice: Device type {device.deviceTypeId} does not support DimBy command")

    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ########################################

    def getActionConfigUiValues(self, actionProps, typeId, devId):
        self.logger.debug(f"getActionConfigUiValues, typeId = {typeId}, devId = {devId}, actionProps = {actionProps}")
        valuesDict = actionProps
        errorMsgDict = indigo.Dict()

        self.logger.debug(f"getActionConfigUiValues, bond_bridges = {self.bond_bridges}")

        # Preload the first bridge device, if not already specified
        if not valuesDict.get('bridge', None) and len(self.bond_bridges):
            valuesDict['bridge'] = list(self.bond_bridges.keys())[0]
        return valuesDict, errorMsgDict

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
