#! /usr/bin/env python
# -*- coding: utf-8 -*-

import time
import logging
import requests
import json
from bondhome import BondHome

bond_types = {
    'CF': u"Ceiling Fan",
    'FP': u"Fireplace",
    'MS': u"Motorized Shades",
    'GX': u"Generic Device",
    'UN': u"Unknown Device"
}

################################################################################

class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = {}".format(self.logLevel))
        
        
    def startup(self):
        self.logger.info(u"Starting BondHome")

        self.bond_bridges = {}          # dict of bridge devices, keyed by Indigo DevID, value id BondHome object
        self.bond_devices = {}          # dict of "client" devices, keyed by Bond ID, value is Indigo device.id        
        self.known_devices = {}         # dict of client devices, keyed by device address, value is dict returned by get_device()

    def shutdown(self):
        self.logger.info(u"Stopping BondHome")
        
        
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"closedPrefsConfigUi, logLevel = {}".format(self.logLevel))        


    ########################################
         
    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        self.logger.debug(u"validateDeviceConfigUi, typeId = {}, valuesDict = {}".format(typeId, valuesDict))
        errorsDict = indigo.Dict()
            
        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

       
    def deviceStartComm(self, device):
        self.logger.info(u"{}: Starting {} Device {}".format(device.name, device.deviceTypeId, device.id))

        device.stateListOrDisplayStateIdChanged()
        self.logger.debug(u"{}: Is configured: {}".format(device.name, device.configured))

        if device.deviceTypeId == "bondBridge":

            try:
                bridge = BondHome(device.pluginProps['address'], device.pluginProps[u'token'])
            except Exception as err:
                self.logger.debug(u"{}: BondHome __init__ error: {}".format(device.name,  err))
                device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            else:
                self.bond_bridges[device.id] = bridge
                version = bridge.get_bridge_version()
                self.logger.debug(u"{}: BondHome version: {}".format(device.name,  version))
                info = bridge.get_bridge_info()
                self.logger.debug(u"{}: BondHome info: {}".format(device.name,  info))

                stateList = [
                    { 'key':'status',           'value':'OK'},
                    { 'key':'fw_ver',           'value':version['fw_ver']},
                    { 'key':'fw_date',          'value':version['fw_date']},
                    { 'key':'uptime_s',         'value':version['uptime_s']},
                    { 'key':'make',             'value':version['make']},
                    { 'key':'model',            'value':version['model']},
                    { 'key':'bondid',           'value':version['bondid']},
                    { 'key':'name',             'value':info['name']},
                    { 'key':'location',         'value':info['location']},
                    { 'key':'brightnessLevel',  'value':info['bluelight']},
               ]
                device.updateStatesOnServer(stateList)
                device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

                # get all the devices the bridge knows about
                
                for bdev in bridge.get_device_list():
                    self.known_devices[bdev] = bridge.get_device(bdev)
                self.logger.debug(u"{}: known_devices:\n{}".format(device.name, self.known_devices))
            
                # start up the BPUP socket connection
                bridge.udp_start(self.receiveBPUP)
        
                        
        elif device.deviceTypeId == "bondDevice":
            self.bond_devices[device.address] = device.id
            self.logger.debug(u"{}: Updated self.bond_devices:\n{}".format(device.name, self.bond_devices))
            
            info = self.known_devices.get(device.address, None)
            if info and not device.pluginProps.get('bond_type', None):
                self.logger.debug(u"{}: Updating Device info:\n{}".format(device.name, info))

                type = info.get('type', 'UN')
                name = info.get('name', None)
                if name:
                    device.name = "{} ({})".format(name, device.address)
                device.subModel = bond_types[type]
                device.replaceOnServer()

                newProps = device.pluginProps
                newProps.update( {'bond_type' : type} )
                device.replacePluginPropsOnServer(newProps)

                        
        else:
            self.logger.error(u"{}: deviceStartComm: Unknown device type: {}".format(device.name, device.deviceTypeId))

            
    def deviceStopComm(self, device):
        self.logger.info(u"{}: Stopping {} Device {}".format(device.name, device.deviceTypeId, device.id))

        if device.deviceTypeId == "bondBridge":
            del self.bond_bridges[device.id]
            device.updateStateOnServer("status", "Stopped")
            device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        elif device.deviceTypeId == "bondDevice":
            self.logger.debug(u"{}: Skipping {} device".format(device.name,  device.deviceTypeId))
            pass
            
        else:
            self.logger.error(u"{}: deviceStopComm: Unknown device type: {}".format(device.name, device.deviceTypeId))

    ########################################
    #
    # Process callback from BondHome devices
    #
    ########################################
 
    def receiveBPUP(self, data):
        self.logger.threaddebug("receiveBPUP: {}".format(data))
    
        bondID = data.get('id', None)
        self.logger.threaddebug("Bond device id: {}".format(bondID))
        if not bondID:
            self.logger.warning("receiveBPUP: no Bond device ID in {}".format(data))
            return
        
        devID = self.bond_devices.get(bondID, None)
        self.logger.threaddebug("Indigo device id: {}".format(devID))
        if not devID:
            self.logger.threaddebug("receiveBPUP: no Indigo device for {}".format(bondID))
            return
            
        device = indigo.devices.get(devID, None)
        self.logger.threaddebug("{}: Device ID: {}".format(device.name, device.id))
        if not device:
            self.logger.warning("receiveBPUP: No Indigo device for {}".format(devID))
            return
        
        bond_type = device.pluginProps['bond_type']
        self.logger.threaddebug("{}: bond_type: {}".format(device.name, bond_type))
        if bond_type == 'GX':
            isOn = bool(data['b']['power'])
            device.updateStateOnServer(key='onOffState', value=isOn)

        elif bond_type == 'FP':
            isOn = bool(data['b']['power'])
            device.updateStateOnServer(key='onOffState', value=isOn)

            flame = data['b']['flame']
            self.logger.debug("{}: Flame = {}".format(device.name, flame))
            
        elif bond_type == 'MS':
            isOpen = bool(data['b']['open'])
            device.updateStateOnServer(key='onOffState', value=isOn)
       
    ########################################
    #
    # callbacks from device creation UI
    #
    ########################################

    def get_bridge_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_bridge_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []
        for dev in indigo.devices.iter("self.bondBridge"):
            self.logger.threaddebug(u"get_bridge_list adding: {}".format(dev.name))         
            retList.append((dev.id, dev.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_device_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_device_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []
        
        for dev_key, dev_info in self.known_devices.iteritems():
            retList.append((dev_key, dev_info["name"]))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_action_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_action_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []
        if targetId:
            
            address = indigo.devices[targetId].address
            if not address:
                address = valuesDict.get("address", None)
                if not address:
                    return retList

        elif valuesDict.get("device", None):
            address = valuesDict['device']
            
        else:
            return retList
            
        action_list = self.known_devices[address]['actions']
        for cmd in action_list:
            retList.append((cmd, cmd))
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict
    
    ########################################
    # Relay Action callback
    ########################################
    def actionControlDevice(self, action, dev):
    
        if action.deviceAction == indigo.kDeviceAction.TurnOn:

            if device.deviceTypeId == "bondBridge":
                self.bond_bridges[dev.id].set_bridge_info({"bluelight": 255})

            elif device.deviceTypeId == "bondDevice":
                self.doDeviceCommand(dev, dev.pluginProps["on_command"])


        elif action.deviceAction == indigo.kDeviceAction.TurnOff:

            if device.deviceTypeId == "bondBridge":
                self.bond_bridges[dev.id].set_bridge_info({"bluelight": 0})

            elif device.deviceTypeId == "bondDevice":
                self.doDeviceCommand(dev, dev.pluginProps["off_command"])


        elif action.deviceAction == indigo.kDeviceAction.SetBrightness:
        
            if device.deviceTypeId == "bondBridge":
                level = int(action.actionValue * 2.55)      # bluelight scale is 0-255
                self.bond_bridges[dev.id].set_bridge_info({"bluelight": level})

            elif device.deviceTypeId == "bondDevice":
                pass


        elif action.deviceAction == indigo.kDeviceAction.BrightenBy:            
            newBrightness = device.brightness + action.actionValue
            if newBrightness > 100:
                newBrightness = 100

            if device.deviceTypeId == "bondBridge":
                level = int(newBrightness * 2.55)      # bluelight scale is 0-255
                self.bond_bridges[dev.id].set_bridge_info({"bluelight": level})

            elif device.deviceTypeId == "bondDevice":
                pass
                


        elif action.deviceAction == indigo.kDeviceAction.DimBy:
            newBrightness = device.brightness - action.actionValue
            if newBrightness < 0:
                newBrightness = 0

            if device.deviceTypeId == "bondBridge":
                level = int(newBrightness * 2.55)      # bluelight scale is 0-255
                self.bond_bridges[dev.id].set_bridge_info({"bluelight": level})

            elif device.deviceTypeId == "bondDevice":
                pass
                

 
    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ########################################

    def sendDeviceCommand(self, pluginAction, dev):
        command = pluginAction.props["command"]
        argument =  indigo.activePlugin.substitute(pluginAction.props["argument"])
        self.logger.debug(u"{}: sendDeviceCommand: {}, argument: {}".format(dev.name, command, argument))
        
        if len(argument):
            self.doDeviceCommand(dev, command, payload={"argument" : int(argument)})
        else:
            self.doDeviceCommand(dev, command, payload={})
        
            
    def doDeviceCommand(self, dev, command, payload):
        self.logger.debug(u"{}: doDeviceCommand: {}".format(dev.name, command))
        bridge = indigo.devices[int(dev.pluginProps["bridge"])]
        bridge.device_action(dev.address, command, payload)
        dev.updateStateOnServer(key="last_command", value=command)

    ########################################
    # Plugin Menu object callbacks
    ########################################

    def setCommandRepeatMenu(self, valuesDict, typeId):
        self.logger.debug(u"setCommandRepeatMenu: typeId: {},  valuesDict: {}".format(typeId, valuesDict))

        device  = valuesDict["device"]
        command = valuesDict["command"]
        try:
            repeats = int(valuesDict["repeats"])
        except:
            return False

        devID = self.bond_devices.get(device, None)
        self.logger.threaddebug("setCommandRepeatMenu: Indigo device id: {}".format(devID))
        if not devID:
            self.logger.threaddebug("setCommandRepeatMenu: no Indigo device for {}".format(bondID))
            return
            
        idev = indigo.devices.get(devID, None)
        self.logger.threaddebug("{}: Device ID: {}".format(idev.name, idev.id))
        if not idev:
            self.logger.warning("setCommandRepeatMenu: No Indigo device for {}".format(devID))
            return
        
        # now to find the action_id that goes with that command.  There's a glaring hole in the API
        # in that the action list returned for the device is only names, not action_ids.

        bridge = indigo.devices[int(idev.pluginProps["bridge"])]
        command_list = bridge.get_device_command_list(device)
        self.logger.threaddebug("setCommandRepeatMenu: command_list: {}".format(command_list))
        for cmd in command_list:
            if cmd == "_":
                continue
            cmd_info = bridge.get_device_command(cmd)
            self.logger.threaddebug("setCommandRepeatMenu: cmd: {} command_info: {}".format(cmd, cmd_info))
            if cmd_info['action'] == command:
                self.logger.threaddebug("setCommandRepeatMenu: found it!")
            
        

            
        return True
        
        bridge = indigo.devices[int(device.pluginProps["bridge"])]
        
        command_list = bridge.get_device_command_list(dev.address)
        self.logger.debug(u"{}: get_device_command_list: {}".format(dev.name, command_list))
        for cmd_id in command_list:
            cmd_info = bridge.get_device_command(dev.address, cmd_id)
            self.logger.debug(u"{}: get_device_command: {}".format(dev.name, cmd_info))

