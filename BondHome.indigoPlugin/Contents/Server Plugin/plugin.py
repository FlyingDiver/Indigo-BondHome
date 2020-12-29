#! /usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import requests

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
        self.bridge_data ={}
        
    def startup(self):
        self.logger.info(u"Starting BondHome")

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
                
    def deviceStartComm(self, dev):
        self.logger.info(u"{}: Starting {} Device {}".format(dev.name, dev.deviceTypeId, dev.id))
        dev.stateListOrDisplayStateIdChanged()

        if dev.deviceTypeId == "bondBridge":

            token_header = {'BOND-Token': dev.pluginProps["token"]}
            url = "http://{}/v2/devices".format(dev.pluginProps["address"])
            try:
                resp = requests.get(url, headers=token_header)
                resp.raise_for_status()
            except requests.exceptions.ConnectionError, e:
                self.logger.error(u"{}: Connection Error: {}".format(dev.name, e))
                dev.updateStateOnServer("status", "Connection Error")
                return     
            except requests.exceptions.Timeout, e:
                self.logger.error(u"{}: Timeout Error: {}".format(dev.name, e))        
                dev.updateStateOnServer("status", "Timeout Error")
                return     
            except requests.exceptions.TooManyRedirects, e:
                self.logger.error(u"{}: TooManyRedirects Error: {}".format(dev.name, e))        
                dev.updateStateOnServer("status", "Redirect Error")
                return     
            except requests.exceptions.HTTPError, e:
                self.logger.error(u"{}: HTTP Error: {}".format(dev.name, e))        
                dev.updateStateOnServer("status", "Other Error")
                return
                
            device_data = {}
            for key in resp.json():
                if key != "_":                    
                    url = "http://{}/v2/devices/{}".format(dev.pluginProps["address"], key)
                    req = requests.get(url, headers=token_header)
                    device_data[key] = req.json()
                
            self.bridge_data[dev.id] = device_data
            self.logger.debug("{}: Bridge Data:\n{}".format(dev.name, json.dumps(self.bridge_data, sort_keys=True, indent=4, separators=(',', ': '))))
            dev.updateStateOnServer("status", "OK - {}".format(len(self.bridge_data[dev.id])))
                    
                        
        elif dev.deviceTypeId in ["bondDevice", "bondRelay"]:
            pass
            
        else:
            self.logger.error(u"{}: deviceStartComm: Unknown device type: {}".format(dev.name, dev.deviceTypeId))

            
    def deviceStopComm(self, dev):
        self.logger.info(u"{}: Stopping {} Device {}".format(dev.name, dev.deviceTypeId, dev.id))

        if dev.deviceTypeId == "bondBridge":
            dev.updateStateOnServer("status", "Stopped")

        elif dev.deviceTypeId in ["bondDevice", "bondRelay"]:
            pass
            
        else:
            self.logger.error(u"{}: deviceStopComm: Unknown device type: {}".format(dev.name, dev.deviceTypeId))

        
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

    #######################################

    def get_action_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_action_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []
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
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)    def startRaising(self, pluginAction, dev):
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

    #######################################
            
    def doDeviceCommand(self, dev, command, payload={}):
        bridge = indigo.devices[int(dev.pluginProps["bridge"])]
        host = bridge.address
        header = {'BOND-Token': bridge.pluginProps["token"]}
        url = "http://{}/v2/devices/{}/actions/{}".format(host, dev.pluginProps["address"], command)
        self.logger.debug(u"{}: doDeviceCommand, url = {}, payload = {}".format(dev.name, url, payload))
        requests.put(url, headers=header, json=payload)
        dev.updateStateOnServer(key="last_command", value=command)

    ########################################
    # Relay Action callback
    ######################
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

