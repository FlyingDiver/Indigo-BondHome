#! /usr/bin/env python
# -*- coding: utf-8 -*-

import time
import logging
from bondhome import BondHome

kCurDevVersCount = 0        # current version of plugin devices

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

        self.bonds = {} 


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

    def runConcurrentThread(self):

        try:
            while True:
                
                # Process any updates data from bonds
                
                for bond in self.bonds.values():
                    bond.udp_receive()

#                    if (time.time() > bond.next_poll):
#                        bond.getUpdate()
                         
                self.sleep(1.0)

        except self.StopThread:
            pass        


    ########################################
                
    def deviceStartComm(self, device):
        self.logger.info(u"{}: Starting {} Device {}".format(device.name, device.deviceTypeId, device.id))

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        if instanceVers == kCurDevVersCount:
            self.logger.threaddebug(u"{}: Device is current version: {}".format(device.name ,instanceVers))
        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps
            newProps["devVersCount"] = kCurDevVersCount
            device.replacePluginPropsOnServer(newProps)
            self.logger.debug(u"{}: Updated device version: {} -> {}".format(device.name,  instanceVers, kCurDevVersCount))
        else:
            self.logger.warning(u"{}: Invalid device version: {}".format(device.name, instanceVers))

        device.stateListOrDisplayStateIdChanged()

        if device.deviceTypeId == "bondBridge":

            self.bonds[device.id] = BondHome(device)
            device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
            self.bonds[device.id].getUpdate()

                        
        elif device.deviceTypeId in ["bondDevice", "bondRelay"]:
            self.logger.debug(u"{}: Skipping {} device".format(device.name,  device.deviceTypeId))
            pass
            
        else:
            self.logger.error(u"{}: deviceStartComm: Unknown device type: {}".format(device.name, device.deviceTypeId))

            
    def deviceStopComm(self, device):
        self.logger.info(u"{}: Stopping {} Device {}".format(device.name, device.deviceTypeId, device.id))

        if device.deviceTypeId == "bondBridge":
            del self.bonds[device.id]
            device.updateStateOnServer("status", "Stopped")

        elif device.deviceTypeId in ["bondDevice", "bondRelay"]:
            self.logger.debug(u"{}: Skipping {} device".format(device.name,  device.deviceTypeId))
            pass
            
        else:
            self.logger.error(u"{}: deviceStopComm: Unknown device type: {}".format(device.name, device.deviceTypeId))

    def dumpDeviceData(self):
        self.logger.info(u"Device Data:\n")
        for bond in self.bonds.values():
            bond.dumpDeviceData()
        
        
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
        bridge = valuesDict.get("bridge", None)
        self.logger.threaddebug("get_device_list: bridge = {}".format(bridge))
        if not bridge:
            return retList
            
        bridge_info = self.bridge_data[int(bridge)]
        for dev_key, dev_info in bridge_info.iteritems():
            self.logger.threaddebug("get_device_list: adding dev_key = {}, dev_info = {}".format(dev_key, dev_info))
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
        bridge = indigo.devices[targetId].pluginProps.get("bridge", None)
        if not bridge:
            bridge = valuesDict.get("bridge", None)
            if not bridge:
                return retList
        action_list = self.bridge_data[int(bridge)][address]['actions']
        self.logger.threaddebug("get_action_list: action_list = {}".format(action_list))
        for cmd in action_list:
            retList.append((cmd, cmd))
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        return valuesDict
    
    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ########################################

    def sendDeviceCommand(self, pluginAction, dev):
        argument =  indigo.activePlugin.substitute(pluginAction.props["argument"])
        self.logger.debug(u"{}: sendDeviceCommand: {}, argument: {}".format(dev.name, pluginAction.props["command"], argument))
        if len(argument):
            try:
                self.doDeviceCommand(dev, pluginAction.props["command"], {"argument" : int(argument)})
            except:
                self.logger.error(u"{}: sendDeviceCommand: {}, argument: {} - cannot convert to integer".format(dev.name, pluginAction.props["command"], argument))        
        else:
            self.doDeviceCommand(dev, pluginAction.props["command"])
            
    def doDeviceCommand(self, dev, command, payload={}):
        bridge = indigo.devices[int(dev.pluginProps["bridge"])]
        host = bridge.address
        header = {'BOND-Token': bridge.pluginProps["token"]}
        url = "http://{}/v2/devices/{}/actions/{}".format(host, dev.pluginProps["address"], command)
        self.logger.debug(u"{}: doDeviceCommand, url = {}, payload = {}".format(dev.name, url, payload))
        resp = requests.put(url, headers=header, json=payload)
        self.logger.debug(u"{}: doDeviceCommand, resp = {}".format(dev.name, resp))
        dev.updateStateOnServer(key="last_command", value=command)

    ########################################
    # Plugin Menu object callbacks
    ########################################

    def setCommandRepeatMenu(self, valuesDict, typeId):
        self.logger.debug(u"{}: setCommandRepeatMenu: typeId: {},  valuesDict: {}".format(dev.name, typeId, valuesDict))


    def setCommandRepeats(self, pluginAction, dev):
        command = pluginAction.props["command"]
        repeats = pluginAction.props["repeats"]
        self.logger.debug(u"{}: setCommandRepeats: {}, repeats: {}".format(dev.name, command, repeats))

        bridge = indigo.devices[int(dev.pluginProps["bridge"])]
        host = bridge.address
        header = {'BOND-Token': bridge.pluginProps["token"]}
        url = "http://{}/v2/devices/{}/commands/{}/signal".format(host, dev.pluginProps["address"], command)
        payload = {"reps": int(repeats)}
        self.logger.debug(u"{}: setCommandRepeats, url = {}, payload = {}".format(dev.name, url, payload))
        resp = requests.patch(url, headers=header, json=payload)
        self.logger.debug(u"{}: setCommandRepeats, resp = {}".format(dev.name, resp))


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
 