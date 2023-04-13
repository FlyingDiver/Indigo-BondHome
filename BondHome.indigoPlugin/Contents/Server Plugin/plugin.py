#! /usr/bin/env python
# -*- coding: utf-8 -*-

import indigo  # noqa
import time
import logging
import requests
import json
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

        self.found_devices = {}    # zeroconf discovered devices

        self.bond_bridges = {}  # dict of bridge devices, keyed by BondID, value id BondHome object
        self.bond_devices = {}  # dict of "client" devices, keyed by (bond) device_ID, value is Indigo device.id
        self.known_devices = {}  # nested dict of client devices, keyed by BondID then device_ID, value is dict returned by get_device()

    def startup(self):
        self.logger.info("Starting BondHome")
        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        services = ["_bond._tcp.local."]
        browser = ServiceBrowser(zeroconf, services, handlers=[self.on_service_state_change])

    def on_service_state_change(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        self.logger.debug(f"Service {name} of type {service_type} state changed: {state_change}")

        if state_change in [ServiceStateChange.Added, ServiceStateChange.Updated]:
            info = zeroconf.get_service_info(service_type, name)
            if service_type == "_bond._tcp.local.":
                if name not in self.found_devices:
                    self.found_devices[name] = info.server

        elif state_change is ServiceStateChange.Removed:
            info = zeroconf.get_service_info(service_type, name)
            if service_type == "_bond._tcp.local.":
                if name in self.found_devices:
                    del self.found_devices[name]

        self.logger.debug(f"Found BondBridges: {self.found_devices}")

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.logLevel = int(valuesDict.get("logLevel", logging.INFO))
            self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(f"logLevel = {self.logLevel}")

    def getDeviceConfigUiValues(self, pluginProps, typeId, devId):
        self.logger.debug(f"getDeviceConfigUiValues, typeId = {typeId}, devId = {devId}, pluginProps = {pluginProps}")
        valuesDict = pluginProps
        errorMsgDict = indigo.Dict()

        # Preload the first bridge for any non-bridge device, if not already specified
        if typeId == 'bondDevice' and not valuesDict.get('bridge', None) and len(self.bond_bridges):
            valuesDict['bridge'] = self.bond_bridges.keys()[0]
        return valuesDict, errorMsgDict

    def deviceStartComm(self, device):
        self.logger.info(f"{device.name}: Starting {device.deviceTypeId} Device {device.id}")

        # ensure device definition is up to date
        device.stateListOrDisplayStateIdChanged()

        if device.deviceTypeId == "bondBridge":
            try:
                bridge = BondHome(device.pluginProps['address'], device.pluginProps[u'token'])
            except Exception as err:
                self.logger.debug(f"{device.name}: BondHome __init__ error: {err}")
                device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                return

            try:
                version = bridge.get_bridge_version()
            except (Exception,):
                self.logger.debug(f"{device.name}: Error in get_bridge_version()")
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

            try:
                info = bridge.get_bridge_info()
            except (Exception,):
                self.logger.debug(f"{device.name}: Error in get_bridge_info()")
                return
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

        elif device.deviceTypeId == "smartBond":
            try:
                bridge = BondHome(device.pluginProps['address'], device.pluginProps[u'token'])
            except Exception as err:
                self.logger.debug(f"{device.name}: BondHome __init__ error: {err}")
                device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                return

            version = bridge.get_bridge_version()
            self.logger.debug(f"{device.name}: BondHome version: {version}")
            stateList = [
                {'key': 'fw_ver', 'value': version['fw_ver']},
                {'key': 'fw_date', 'value': version['fw_date']},
                {'key': 'uptime_s', 'value': version['uptime_s']},
                {'key': 'make', 'value': version['make']},
                {'key': 'model', 'value': version['model']},
                {'key': 'bondid', 'value': version['bondid']}
            ]
            device.updateStatesOnServer(stateList)

            bondID = version['bondid']
            self.bond_bridges[bondID] = bridge

            # get all the devices the bridge knows about (usually only one, but it's possible that might change)
            self.known_devices[bondID] = {}
            for bond_dev in bridge.get_device_list():
                self.known_devices[bondID][bond_dev] = bridge.get_device(bond_dev)
            self.logger.debug(f"{device.name}: known_devices:\n{self.known_devices}")

            # start up the BPUP socket connection
            bridge.udp_start(self.receiveBPUP)

        elif device.deviceTypeId == "bondDevice":
            self.bond_devices[device.address] = device.id   # save the device info, do startup later after bridges are started

        else:
            self.logger.error(f"{device.name}: deviceStartComm: Unknown device type: {device.deviceTypeId}")

    # Undocumented API - runs after all devices have been started.  Actually, it's the super._postStartup() call that starts the devices.
    def _postStartup(self):
        super(Plugin, self)._postStartup()  # noqa
        self.doDeviceStartup()

    def doDeviceStartup(self):

        for bondDevID in self.bond_devices.values():

            device = indigo.devices[bondDevID]
            self.logger.debug(f"{device.name}: doDeviceStartup: {device.deviceTypeId} ({device.address})")

            bond_id = device.pluginProps['bridge']
            if bond_id not in self.bond_bridges:
                return
            self.logger.debug(f"{device.name}: doDeviceStartup: using bond_id = {bond_id}")

            bridge = self.bond_bridges[bond_id]
            dev_info = self.known_devices[bond_id].get(device.address, None)
            if not dev_info:
                self.logger.debug(f"{device.name}: doDeviceStartup: no device info for {device.address}")
                return

            bond_type = dev_info.get('type', 'UN')

            if dev_info and not device.pluginProps.get('bond_type', None):
                self.logger.debug(f"{device.name}: Updating Device info:\n{dev_info}")

                name = dev_info.get('name', None)
                if name:
                    device.name = f"{name} ({device.address})"
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
                device.updateStateOnServer(key='flame', value=states['flame'])

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
    # callback for state list changes, called from stateListOrDisplayStateIdChanged()
    ########################################

    def getDeviceStateList(self, device):
        state_list = indigo.PluginBase.getDeviceStateList(self, device)

        # add custom states as needed for bond device type
        if device.pluginProps.get("bond_type", None) == "FP":
            flame_state = self.getDeviceStateDictForNumberType(u"flame", u"Flame", u"Flame")
            state_list.append(flame_state)

        return state_list

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
        if bond_type == 'GX':
            device.updateStateOnServer(key='onOffState', value=bool(data['b']['power']))

        elif bond_type == 'FP':
            device.updateStateOnServer(key='onOffState', value=bool(data['b']['power']))
            device.updateStateOnServer(key='flame', value=data['b']['flame'])

        elif bond_type == 'MS':
            device.updateStateOnServer(key='onOffState', value=bool(data['b']['open']))

    ########################################
    #
    # callbacks from device creation UI
    #
    ########################################

    def found_device_list(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        self.logger.debug(f"found_device_list: filter = {filter}, typeId = {typeId}, targetId = {targetId}, valuesDict = {valuesDict}")
        retList = [("Enter Manual IP address", "Discovered Devices:")]
        if typeId == "bondBridge":
            for name, address in self.found_devices.items():
                retList.append((address, name))
        self.logger.debug(f"found_station_list: retList = {retList}")
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
    def actionControlDevice(self, action, dev):
        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            if dev.deviceTypeId == "bondBridge":
                bondID = dev.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": 255})
                dev.updateStateOnServer(key='brightnessLevel', value=100)
            elif dev.deviceTypeId in ["bondDevice", "smartBond"]:
                bridge = self.bond_bridges[dev.pluginProps["bridge"]]
                bridge.device_action(dev.address, dev.pluginProps["on_command"])

        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            if dev.deviceTypeId == "bondBridge":
                bondID = dev.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": 0})
                dev.updateStateOnServer(key='brightnessLevel', value=0)
            elif dev.deviceTypeId == "bondDevice":
                bridge = self.bond_bridges[dev.pluginProps["bridge"]]
                bridge.device_action(dev.address, dev.pluginProps["off_command"])

        elif action.deviceAction == indigo.kDeviceAction.SetBrightness:
            if dev.deviceTypeId == "bondBridge":
                level = int(action.actionValue * 2.55)  # bluelight scale is 0-255
                bondID = dev.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                dev.updateStateOnServer(key='brightnessLevel', value=action.actionValue)
            elif dev.deviceTypeId == "bondDevice":
                pass

        elif action.deviceAction == indigo.kDeviceAction.BrightenBy:
            newBrightness = dev.brightness + action.actionValue
            if newBrightness > 100:
                newBrightness = 100
            if dev.deviceTypeId == "bondBridge":
                level = int(newBrightness * 2.55)  # bluelight scale is 0-255
                bondID = dev.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                dev.updateStateOnServer(key='brightnessLevel', value=newBrightness)
            elif dev.deviceTypeId == "bondDevice":
                pass

        elif action.deviceAction == indigo.kDeviceAction.DimBy:
            newBrightness = dev.brightness - action.actionValue
            if newBrightness < 0:
                newBrightness = 0
            if dev.deviceTypeId == "bondBridge":
                level = int(newBrightness * 2.55)  # bluelight scale is 0-255
                bondID = dev.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                dev.updateStateOnServer(key='brightnessLevel', value=newBrightness)
            elif dev.deviceTypeId == "bondDevice":
                pass

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
        self.logger.info(f"\n{json.dumps(self.known_devices, sort_keys=True, indent=4, separators=(',', ': '))}")
        return True
