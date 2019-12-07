#! /usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import time
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
        
    def runConcurrentThread(self):
        self.logger.debug(u"runConcurrentThread starting")
        try:
            while True:
                self.sleep(5.0)

        except self.StopThread:
            self.logger.debug(u"runConcurrentThread ending")
            pass

                
    def deviceStartComm(self, dev):
        self.logger.info(u"{}: Starting {} Device {}".format(dev.name, dev.deviceTypeId, dev.id))

        if dev.deviceTypeId == "bondBridge":

            token_header = {'BOND-Token': dev.pluginProps["token"]}
            url = "http://{}/v2/devices".format(dev.pluginProps["address"])
            try:
                resp = requests.get(url, headers=token_header)
                resp.raise_for_status()
            except requests.exceptions.ConnectionError, e:
                self.logger.error(u"{}: Connection Error: {}".format(dev.name, e))
                return     
            except requests.exceptions.Timeout, e:
                self.logger.error(u"{}: Timeout Error: {}".format(dev.name, e))        
                return     
            except requests.exceptions.TooManyRedirects, e:
                self.logger.error(u"{}: TooManyRedirects Error: {}".format(dev.name, e))        
                return     
            except requests.exceptions.HTTPError, e:
                self.logger.error(u"{}: HTTP Error: {}".format(dev.name, e))        
                return
                
            device_data = {}
            for key in resp.json():
                if key != "_":                    
                    url = "http://{}/v2/devices/{}".format(dev.pluginProps["address"], key)
                    req = requests.get(url, headers=token_header)
                    device_data[key] = req.json()
                
            self.bridge_data[dev.id] = device_data
            self.logger.debug(json.dumps(self.bridge_data, sort_keys=True, indent=4, separators=(',', ': ')))
                    
                        
        elif dev.deviceTypeId == "bondShade":
            pass
            
        elif dev.deviceTypeId == "bondFan":
            pass

        elif dev.deviceTypeId == "bondFireplace":
            pass

        else:
            self.logger.error(u"{}: deviceStartComm: Unknown device type: {}".format(dev.name, dev.deviceTypeId))
            
    def deviceStopComm(self, dev):
        self.logger.info(u"{}: Stopping {} Device {}".format( dev.name, dev.deviceTypeId, dev.id))

    ########################################
    #
    # callbacks from device creation UI
    #
    ########################################

    def get_bridge_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_gateway_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []
        for dev in indigo.devices.iter("self.bondBridge"):
            self.logger.debug(u"get_bridge_list adding: {}".format(dev.name))         
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
        self.logger.threaddebug("get_device_list: bridge_info = {}".format(bridge_info))
        for dev_key, dev_info in bridge_info.iteritems():
            self.logger.threaddebug("get_device_list: dev_key = {}, dev_info = {}".format(dev_key, dev_info))
            if dev_info["type"] == filter:
                self.logger.debug(u"get_bridge_list adding: {} ({})".format(dev_info["name"], dev_key))         
                retList.append((dev_key, dev_info["name"]))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_command_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_command_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []
        if targetId:
            dev = indigo.devices[targetId]
            bridge = int(dev.pluginProps["bridge"])
            address = dev.address
        else:
            bridge = int(valuesDict.get("bridge", None))
            self.logger.threaddebug("get_command_list: bridge = {}".format(bridge))
            if not bridge:
                return retList
            address = valuesDict.get("address", None)
            self.logger.threaddebug("get_command_list: address = {}".format(address))
            if not address:
                return retList
            
        action_list = self.bridge_data[bridge][address]['actions']
        self.logger.debug("get_command_list: action_list = {}".format(action_list))
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
        self.logger.debug(u"{}: sendDeviceCommand: {}".format(dev.name, pluginAction.props["command"]))
        doDeviceCommand(dev, pluginAction.props["command"], payload={}):


    ########################################
    #
    # do request
    #
    ########################################

    def doGet(self, dev, postURL):
        if dev.deviceTypeId == "bondBridge":
            host = dev.pluginProps["address"]
            url = "http://{}/v2/devices/{}".format(host, postURL)
            r = requests.get(url, headers=self.token_header)
            return r.json()
            
    def doDeviceCommand(self, dev, command, payload={}):
        bridge = indigo.devices[int(dev.pluginProps["bridge"])]
        host = bridge.address
        header = {'BOND-Token': bridge.pluginProps["token"]}
        url = "http://{}/v2/devices/{}/actions/{}".format(host, dev.pluginProps["address"], command)
        self.logger.debug(u"{}: doDeviceCommand, url = {}".format(dev.name, url))
        requests.put(url, headers=header, json=payload)
    
    ########################################
    # Relay / Dimmer / Shade Action callback
    ########################################
    def actionControlDevice(self, action, dev):

        ###### TURN ON ######
        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            self.logger.debug(u"{}: TurnOn".format(dev.name))
            self.doDeviceCommand(dev, "Open")
            dev.updateStateOnServer("onOffState", True)
            
        ###### TURN OFF ######
        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            self.logger.debug(u"{}: TurnOff".format(dev.name))
            self.doDeviceCommand(dev, "Close")
            dev.updateStateOnServer("onOffState", False)

        ###### TOGGLE ######
        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            self.logger.debug(u"{}: Toggle".format(dev.name))
            self.doDeviceCommand(dev, "Toggle")
            dev.updateStateOnServer("onOffState", not dev.onState)


    ######################
    # Fan Action callback
    ######################
    def actionControlSpeedControl(self, action, dev):
        
        ###### TURN ON ######
        if action.speedControlAction == indigo.kSpeedControlAction.TurnOn:
            self.logger.debug(u"{}: TurnOn".format(dev.name))

        ###### TURN OFF ######
        elif action.speedControlAction == indigo.kSpeedControlAction.TurnOff:
            self.logger.debug(u"{}: TurnOff".format(dev.name))

        ###### TOGGLE ######
        elif action.speedControlAction == indigo.kSpeedControlAction.Toggle:
            self.logger.debug(u"{}: Toggle".format(dev.name))
            
        ###### SET SPEED INDEX ######
        elif action.speedControlAction == indigo.kSpeedControlAction.SetSpeedIndex:
            self.logger.debug(u"{}: SetSpeedIndex to {}".format(dev.name, action.actionValue))

        ###### SET SPEED LEVEL ######
        elif action.speedControlAction == indigo.kSpeedControlAction.SetSpeedLevel:
            self.logger.debug(u"{}: SetSpeedLevel to {}".format(dev.name, action.actionValue))

        ###### INCREASE SPEED INDEX BY ######
        elif action.speedControlAction == indigo.kSpeedControlAction.IncreaseSpeedIndex:
            self.logger.debug(u"{}: IncreaseSpeedIndex by {}".format(dev.name, action.actionValue))

        ###### DECREASE SPEED INDEX BY ######
        elif action.speedControlAction == indigo.kSpeedControlAction.DecreaseSpeedIndex:
            self.logger.debug(u"{}: DecreaseSpeedIndex by {}".format(dev.name, action.actionValue))
