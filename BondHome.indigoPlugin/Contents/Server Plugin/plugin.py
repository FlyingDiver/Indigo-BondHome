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
                    { 'key':'status',    'value':'OK'},
                    { 'key':'fw_ver',    'value':version['fw_ver']},
                    { 'key':'fw_date',   'value':version['fw_date']},
                    { 'key':'uptime_s',  'value':version['uptime_s']},
                    { 'key':'make',      'value':version['make']},
                    { 'key':'model',     'value':version['model']},
                    { 'key':'bondid',    'value':version['bondid']},
                    { 'key':'name',      'value':info['name']},
                    { 'key':'location',  'value':info['location']},
                    { 'key':'bluelight', 'value':info['bluelight']},
                ]
                device.updateStatesOnServer(stateList)
                device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

                # get all the devices the bridge knows about
                
                for bdev in bridge.get_device_list():
                    self.known_devices[bdev] = bridge.get_device(bdev)
                self.logger.debug(u"{}: known_devices:\n{}".format(device.name, self.known_devices))
            
                # start up the BPUP socket connection, after confirming connection
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
        if not targetId:
            return retList
            
        address = indigo.devices[targetId].address
        if not address:
            address = valuesDict.get("address", None)
            if not address:
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
        ###### TURN ON ######
        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            for i in range(int(dev.pluginProps.get("repeat", "1"))):
                self.doDeviceCommand(dev, dev.pluginProps["on_command"])
                self.sleep(1.0)    
            dev.updateStateOnServer("onOffState", True)

        ###### TURN OFF ######
        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            for i in range(int(dev.pluginProps.get("repeat", "1"))):
                self.doDeviceCommand(dev, dev.pluginProps["off_command"])
                self.sleep(1.0)    
            dev.updateStateOnServer("onOffState", False)
 
    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ########################################

    def sendDeviceCommand(self, pluginAction, dev):
        bridge = indigo.devices[int(dev.pluginProps["bridge"])]
        argument =  indigo.activePlugin.substitute(pluginAction.props["argument"])
        self.logger.debug(u"{}: sendDeviceCommand: {}, argument: {}".format(dev.name, pluginAction.props["command"], argument))
        if len(argument):
            payload
            try:
                bridge.deviceAction(dev.address, pluginAction.props["command"], {"argument" : int(argument)})
            except:
                self.logger.error(u"{}: sendDeviceCommand: {}, argument: {} - cannot convert to integer".format(dev.name, pluginAction.props["command"], argument))        
        else:
            bridge = indigo.devices[int(dev.pluginProps["bridge"])]
            bridge.bridge(dev.address, pluginAction.props["command"])
        dev.updateStateOnServer(key="last_command", value=command)
            
    def doDeviceCommand(self, dev, command):
        self.logger.debug(u"{}: doDeviceCommand: {}".format(dev.name, command))
        bridge = indigo.devices[int(dev.pluginProps["bridge"])]
        bridge.deviceAction(dev.address, command)
        dev.updateStateOnServer(key="last_command", value=command)

    ########################################
    # Plugin Menu object callbacks
    ########################################

    def setCommandRepeatMenu(self, valuesDict, typeId):
        self.logger.debug(u"{}: setCommandRepeatMenu: typeId: {},  valuesDict: {}".format(dev.name, typeId, valuesDict))

        device = pluginAction.props["device"]
        command = pluginAction.props["command"]
        repeats = pluginAction.props["repeats"]
        return
        
        bridge = indigo.devices[int(dev.pluginProps["bridge"])]
        
        command_list = bridge.get_device_command_list(dev.address)
        self.logger.debug(u"{}: get_device_command_list: {}".format(dev.name, command_list))
        for cmd_id in command_list:
            cmd_info = bridge.get_device_command(dev.address, cmd_id)
            self.logger.debug(u"{}: get_device_command: {}".format(dev.name, cmd_info))

