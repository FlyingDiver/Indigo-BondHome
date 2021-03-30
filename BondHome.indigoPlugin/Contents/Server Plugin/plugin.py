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

        self.bond_bridges = {}          # dict of bridge devices, keyed by BondID, value id BondHome object
        self.bond_devices = {}          # dict of "client" devices, keyed by (bond) device_ID, value is Indigo device.id        
        self.known_devices = {}         # nested dict of client devices, keyed by BondID then device_ID, value is dict returned by get_device()

    def shutdown(self):
        self.logger.info(u"Stopping BondHome")
        
        
    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorDict = indigo.Dict()

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)

        return True
        
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


    def getDeviceConfigUiValues(self, pluginProps, typeId, devId):
        self.logger.debug(u"getDeviceConfigUiValues, typeId = {}, devId = {}, pluginProps = {}".format(typeId, devId, pluginProps))
        valuesDict = pluginProps
        errorMsgDict = indigo.Dict()

        # Pre-load the first bridge for any non-bridge device, if not already specified
        if typeId == 'bondDevice' and not valuesDict.get('bridge', None) and len(self.bond_bridges):
            valuesDict['bridge'] = self.bond_bridges.keys()[0]
            
        return (valuesDict, errorMsgDict)
             
        
    def deviceStartComm(self, device):
        self.logger.info(u"{}: Starting {} Device {}".format(device.name, device.deviceTypeId, device.id))

        if device.deviceTypeId == "bondBridge":

            try:
                bridge = BondHome(device.pluginProps['address'], device.pluginProps[u'token'])
            except Exception as err:
                self.logger.debug(u"{}: BondHome __init__ error: {}".format(device.name,  err))
                device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                return
                
            try:
                version = bridge.get_bridge_version()
            except:
                self.logger.debug(u"{}: Error in get_bridge_version()".format(device.name))
                return
            self.logger.debug(u"{}: Bond version: {}".format(device.name,  version))

            try:
                info = bridge.get_bridge_info()
            except:
                self.logger.debug(u"{}: Error in get_bridge_info()".format(device.name))
                return
            self.logger.debug(u"{}: Bond info: {}".format(device.name,  info))
                
            stateList = [
                { 'key':'fw_ver',           'value':version['fw_ver']},
                { 'key':'fw_date',          'value':version['fw_date']},
                { 'key':'uptime_s',         'value':version['uptime_s']},
                { 'key':'make',             'value':version['make']},
                { 'key':'model',            'value':version['model']},
                { 'key':'bondid',           'value':version['bondid']},
                { 'key':'name',             'value':info['name']},
                { 'key':'location',         'value':info['location']},
                { 'key':'brightnessLevel',  'value':info['bluelight']}
            ]
            device.updateStatesOnServer(stateList)

            bondID = version['bondid']
            self.bond_bridges[bondID] = bridge

            # get all the devices the bridge knows about
            self.known_devices[bondID] = {}
            for bdev in bridge.get_device_list():
                self.known_devices[bondID][bdev] = bridge.get_device(bdev)
            self.logger.debug(u"{}: known_devices:\n{}".format(device.name, self.known_devices))
        
            # start up the BPUP socket connection
            bridge.udp_start(self.receiveBPUP)
        
                        
        elif device.deviceTypeId == "bondDevice":
            self.bond_devices[device.address] = device.id
            bondid = device.pluginProps['bridge']  
            bridge = self.bond_bridges[bondid] 
            dev_info = self.known_devices[bondid].get(device.address, None)
            bond_type = dev_info.get('type', 'UN')
            if dev_info and not device.pluginProps.get('bond_type', None):
                self.logger.debug(u"{}: Updating Device info:\n{}".format(device.name, dev_info))

                name = dev_info.get('name', None)
                if name:
                    device.name = "{} ({})".format(name, device.address)
                device.subModel = bond_types[bond_type]
                device.replaceOnServer()

                newProps = device.pluginProps
                newProps.update( {'bond_type' : bond_type} )
                device.replacePluginPropsOnServer(newProps)
                
            states = bridge.get_device_state(device.address)
            self.logger.debug(u"{}: Device states: {}".format(device.name, states))
            device.stateListOrDisplayStateIdChanged()
            
            if bond_type == 'GX':
                device.updateStateOnServer(key='onOffState', value=bool(states['power']))

            elif bond_type == 'FP':
                device.updateStateOnServer(key='onOffState', value=bool(states['power']))
                device.updateStateOnServer(key='flame', value=states['flame'])
            
            elif bond_type == 'MS':
                device.updateStateOnServer(key='onOffState', value=bool(states['open']))

        elif device.deviceTypeId == "smartBond":

            try:
                bridge = BondHome(device.pluginProps['address'], device.pluginProps[u'token'])
            except Exception as err:
                self.logger.debug(u"{}: BondHome __init__ error: {}".format(device.name,  err))
                device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
                return
                
            version = bridge.get_bridge_version()            
            self.logger.debug(u"{}: BondHome version: {}".format(device.name,  version))
            stateList = [
                { 'key':'fw_ver',           'value':version['fw_ver']},
                { 'key':'fw_date',          'value':version['fw_date']},
                { 'key':'uptime_s',         'value':version['uptime_s']},
                { 'key':'make',             'value':version['make']},
                { 'key':'model',            'value':version['model']},
                { 'key':'bondid',           'value':version['bondid']}
            ]

            bondID = version['bondid']
            self.bond_bridges[bondID] = bridge

            dev_info = bridge.get_device_list()[0]
            self.logger.debug(u"{}: smartBond device = {}".format(device.name, dev_info))
            
            bond_type = dev_info.get('type', 'UN')
            if dev_info and not device.pluginProps.get('bond_type', None):
                self.logger.debug(u"{}: Updating Device info:\n{}".format(device.name, dev_info))

                name = dev_info.get('name', None)
                if name:
                    device.name = "{} ({})".format(name, device.address)
                device.subModel = bond_types[bond_type]
                device.replaceOnServer()

                newProps = device.pluginProps
                newProps.update( {'bond_type' : bond_type} )
                device.replacePluginPropsOnServer(newProps)
            
            states = bridge.get_device_state(1)
            self.logger.debug(u"{}: Device states: {}".format(device.name, states))
            device.stateListOrDisplayStateIdChanged()
        
            if bond_type == 'GX':
                device.updateStateOnServer(key='onOffState', value=bool(states['power']))

            elif bond_type == 'FP':
                device.updateStateOnServer(key='onOffState', value=bool(states['power']))
                device.updateStateOnServer(key='flame', value=states['flame'])
        
            elif bond_type == 'MS':
                device.updateStateOnServer(key='onOffState', value=bool(states['open']))
            
            # start up the BPUP socket connection
            bridge.udp_start(self.receiveBPUP)
                     
        else:
            self.logger.error(u"{}: deviceStartComm: Unknown device type: {}".format(device.name, device.deviceTypeId))

            
    def deviceStopComm(self, device):
        self.logger.info(u"{}: Stopping {} Device {}".format(device.name, device.deviceTypeId, device.id))

        if device.deviceTypeId == "bondBridge":
            bondID = device.states['bondid']
            del self.bond_bridges[bondID]

        elif device.deviceTypeId == "smartBond":
            bondID = device.states['bondid']
            del self.bond_bridges[bondID]

        elif device.deviceTypeId == "bondDevice":
            self.logger.debug(u"{}: Skipping {} device".format(device.name,  device.deviceTypeId))
            pass
            
        else:
            self.logger.error(u"{}: deviceStopComm: Unknown device type: {}".format(device.name, device.deviceTypeId))


    ########################################
    #
    # callback for state list changes, called from stateListOrDisplayStateIdChanged()
    #
    ########################################
    
    def getDeviceStateList(self, device):
        state_list = indigo.PluginBase.getDeviceStateList(self, device)
        
        # add custom states as needed for bond device type
        
        if device.pluginProps.get("bond_type", None) == "FP":
            flame_state = self.getDeviceStateDictForNumberType(u"flame", u"Flame", u"Flame")
            state_list.append(flame_state)

        return state_list


    ########################################
    #
    # Process callback from BondHome devices
    #
    ########################################
 
    def receiveBPUP(self, data):
        self.logger.threaddebug("receiveBPUP: {}".format(data))
        
    
        bondID = data.get('B', None)
        self.logger.threaddebug("Bond Bridge id: {}".format(bondID))
        if not bondID:
            self.logger.warning("receiveBPUP: no Bond Bridge ID in {}".format(data))
            return

        deviceID = data.get('id', None)
        self.logger.threaddebug("Bond device id: {}".format(deviceID))
        if not deviceID:
            self.logger.warning("receiveBPUP: no Bond device ID in {}".format(data))
            return
        
        iDevID = self.bond_devices.get(deviceID, None)
        self.logger.threaddebug("Indigo device id: {}".format(iDevID))
        if not iDevID:
            self.logger.threaddebug("receiveBPUP: no Indigo device for {}".format(deviceID))
            return
            
        device = indigo.devices.get(iDevID, None)
        self.logger.threaddebug("{}: Device ID: {}".format(device.name, device.id))
        if not device:
            self.logger.warning("receiveBPUP: No Indigo device for {}".format(iDevID))
            return
        
        bond_type = device.pluginProps['bond_type']
        self.logger.threaddebug("{}: bond_type: {}".format(device.name, bond_type))
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

    def get_bridge_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_bridge_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []
        for dev in indigo.devices.iter("self.bondBridge"):
            self.logger.threaddebug(u"get_bridge_list adding: {}".format(dev.name))         
            retList.append((dev.states['bondid'], dev.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_device_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_device_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []
        bondid = valuesDict.get("bridge", None)
        if not bondid:
            return retList

        for dev_key, dev_info in self.known_devices[bondid].iteritems():
            retList.append((dev_key, dev_info["name"]))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def get_action_list(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.threaddebug("get_action_list: typeId = {}, targetId = {}, filter = {}, valuesDict = {}".format(typeId, targetId, filter, valuesDict))
        retList = []

        bondid = valuesDict.get("bridge", None)
        if not bondid:
            return retList

        if targetId:   
            try:         
                address = indigo.devices[targetId].address
            except:
                address = None
            if not address:
                address = valuesDict.get("address", None)

        elif valuesDict.get("device", None):
            address = valuesDict.get('device', None)
        
        else:
            address = None
            
        if not address:
            return retList
            
        dev_info = self.known_devices[bondid][address]
        for cmd in dev_info['actions']:
            retList.append((cmd, cmd))
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict = None, typeId = None, devId = None):
        self.logger.threaddebug("menuChanged: devId = {}, typeId = {}, valuesDict = {}".format(devId, typeId, valuesDict))
        return valuesDict

          
    ########################################
    # Relay Action callback
    ########################################
    def actionControlDevice(self, action, dev):
        self.logger.threaddebug("{}: actionControlDevice:  action = {}".format(dev.name, action))
        
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
                level = int(action.actionValue * 2.55)      # bluelight scale is 0-255
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
                level = int(newBrightness * 2.55)      # bluelight scale is 0-255
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
                level = int(newBrightness * 2.55)      # bluelight scale is 0-255
                bondID = dev.states['bondid']
                self.bond_bridges[bondID].set_bridge_info({"bluelight": level})
                dev.updateStateOnServer(key='brightnessLevel', value=newBrightness)

            elif dev.deviceTypeId == "bondDevice":
                pass
                

 
    ########################################
    # Plugin Actions object callbacks (pluginAction is an Indigo plugin action instance)
    ########################################

    def getActionConfigUiValues(self, actionProps, typeId, devId):
        self.logger.debug(u"getActionConfigUiValues, typeId = {}, devId = {}, actionProps = {}".format(typeId, devId, actionProps))
        valuesDict = actionProps
        errorMsgDict = indigo.Dict()

        # Pre-load the first bridge device, if not already specified
        if not valuesDict.get('bridge', None) and len(self.bond_bridges):
            valuesDict['bridge'] = self.bond_bridges.keys()[0]
            
        return (valuesDict, errorMsgDict)
             
        
    def doDeviceAction(self, pluginAction):
        self.logger.debug(u"doDeviceAction, pluginAction = {}".format(pluginAction))
        bridge = self.bond_bridges[pluginAction.props["bridge"]]
        argument =  indigo.activePlugin.substitute(pluginAction.props["argument"])
        
        if len(argument):
            payload = {"argument" : int(argument)}
        else:
            payload = {}
            
        bridge.device_action(pluginAction.props["device"], pluginAction.props["command"], payload)

                
    def updateStateBeliefAction(self, pluginAction):
        self.logger.debug(u"updateStateBeliefAction, pluginAction = {}".format(pluginAction))
        bridge = self.bond_bridges[pluginAction.props["bridge"]]
        state = pluginAction.props["state"]
        value = pluginAction.props["value"]   
            
        if len(state) and len(value):
            payload = {state : value}
        else:
            return
            
        bridge.update_device_state(pluginAction.props["device"], pluginAction.props["command"], payload)


    def setCommandRepeatAction(self, pluginAction):
        self.logger.debug(u"setCommandRepeatAction: pluginAction: {}".format(pluginAction))

        bridge = self.bond_bridges[pluginAction.props["bridge"]]
        device  = pluginAction.props["device"]
        command = pluginAction.props["command"]
        try:
            repeats = int(pluginAction.props["repeats"])
        except:
            self.logger.warning(u"setCommandRepeatAction: invalid repeat value: {}".format(pluginAction.props["repeats"]))
            return False
        
        # now to find the action_id that goes with that command.  There's a glaring hole in the API in that the
        # action list returned for the device is only names, not action_ids.

        command_list = bridge.get_device_command_list(device)
        for cmd_id in command_list:
            if cmd_id == "_":
                continue
            cmd_info = bridge.get_device_command(device, cmd_id)
            if cmd_info['action'] == command:
                break
        
        # send the change command and check the result
        payload = {"reps": int(repeats)}
        result = bridge.set_device_command_signal(device, cmd_id, payload)
        if result['reps'] != repeats:
            self.logger.warning(u"setCommandRepeatAction: setting repeat value failed")
                    
        
    ########################################
    # Plugin Menu object callbacks
    ########################################


    def dumpConfig(self):
        self.logger.info("\n"+json.dumps(self.known_devices, sort_keys=True, indent=4, separators=(',', ': ')))
        return True

