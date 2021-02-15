#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import socket
import json
import logging
import requests
import threading
import indigo

################################################################################
class BondHome(object):

    def __init__(self, device):
        self.logger = logging.getLogger("Plugin.BondHome")
        self.device = device

        self.address = device.pluginProps.get(u'address', "")
        self.token = device.pluginProps.get(u'token', "")
        self.enableUDP = bool(device.pluginProps.get(u'enableUDP', False))
        self.token_header = {'BOND-Token': self.token}
        
        self.udp_port = None
        self.sock = None

        self.pollFrequency = float(self.device.pluginProps.get('pollingFrequency', "10")) *  60.0
        self.next_poll = time.time()

        self.logger.debug(u"BondHome __init__ address = {}, token = {}, pollFrequency = {}".format(self.address, self.token, self.pollFrequency))

        if self.enableUDP:
            self.udp_start()
            
        # Get basic info about the bridge
        
        url = "http://{}/v2/sys/version".format(self.address)
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError, e:
            self.logger.error(u"{}: Connection Error: {}".format(self.device.name, e))
            self.device.updateStateOnServer("status", "Connection Error")
            return     
        except requests.exceptions.Timeout, e:
            self.logger.error(u"{}: Timeout Error: {}".format(self.device.name, e))        
            self.device.updateStateOnServer("status", "Timeout Error")
            return     
        except requests.exceptions.TooManyRedirects, e:
            self.logger.error(u"{}: TooManyRedirects Error: {}".format(self.device.name, e))        
            self.device.updateStateOnServer("status", "Redirect Error")
            return     
        except requests.exceptions.HTTPError, e:
            self.logger.error(u"{}: HTTP Error: {}".format(self.device.name, e))        
            self.device.updateStateOnServer("status", "Other Error")
            return
        data = resp.json()
        stateList = [
            { 'key':'status',   'value':'OK'},
            { 'key':'fw_ver',   'value':data['fw_ver']},
            { 'key':'fw_date',  'value':data['fw_date']},
            { 'key':'uptime_s', 'value':data['uptime_s']},
            { 'key':'make',     'value':data['make']},
            { 'key':'model',    'value':data['model']},
            { 'key':'bondid',   'value':data['bondid']},
        ]
        self.device.updateStatesOnServer(stateList)
      
    def getUpdate(self):
    
        # Update info about the bridge itself
        
        url = "http://{}/v2/bridge".format(self.address)
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError, e:
            self.logger.error(u"{}: Connection Error: {}".format(self.device.name, e))
            self.device.updateStateOnServer("status", "Connection Error")
            return     
        except requests.exceptions.Timeout, e:
            self.logger.error(u"{}: Timeout Error: {}".format(self.device.name, e))        
            self.device.updateStateOnServer("status", "Timeout Error")
            return     
        except requests.exceptions.TooManyRedirects, e:
            self.logger.error(u"{}: TooManyRedirects Error: {}".format(self.device.name, e))        
            self.device.updateStateOnServer("status", "Redirect Error")
            return     
        except requests.exceptions.HTTPError, e:
            self.logger.error(u"{}: HTTP Error: {}".format(self.device.name, e))        
            self.device.updateStateOnServer("status", "Other Error")
            return
        self.device.updateStateOnServer("status", "OK")

        data = resp.json()
        self.device.updateStateOnServer("name", data['name'])
        self.device.updateStateOnServer("location", data['location'])
        self.device.updateStateOnServer("bluelight", data['bluelight'])
        stateList = [
            { 'key':'name',      'value':data['name']},
            { 'key':'location',  'value':data['location']},
            { 'key':'bluelight', 'value':data['bluelight']},
        ]
        self.device.updateStatesOnServer(stateList)
        
        # Get the list of devices

        url = "http://{}/v2/devices".format(self.address)
        resp = requests.get(url, headers=self.token_header)
        resp.raise_for_status()
           
        # Then get details for each device
        
        self.bridge_data = {}
        for key in resp.json():
            if key != "_":                    
                url = "http://{}/v2/devices/{}".format(self.address, key)
                req = requests.get(url, headers=self.token_header)
                self.bridge_data[key] = req.json()
            
        self.device.updateStateOnServer("devcount", len(self.bridge_data))
        self.logger.threaddebug("{}: Bridge Data:\n{}".format(self.device.name, json.dumps(self.bridge_data, sort_keys=True, indent=4, separators=(',', ': '))))
                    
        
            
    def __del__(self):
        self.sock.close()
        stateList = [
            { 'key':'status',   'value':  "Off"},
            { 'key':'timestamp','value':  datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
        
    def dumpDeviceData(self):
        self.logger.info(u"{}:\n{}".format(self.device.name, json.dumps(self.bridge_data, sort_keys=True, indent=4, separators=(',', ': '))))


    ########################################
    # Bond Push UDP Protocol (BPUP)
    ########################################

    def udp_start(self):
            
        # set up socket listener  
        
        if not self.sock:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.settimeout(0.1)
                self.sock.sendto('\n', (self.address, 30007))
            except Exception as err:
                self.logger.error(u"udp_start() Exception: {}".format(err))
            else:
                self.logger.debug(u"udp_start() socket listener started")

    def udp_receive(self):
    
        if not self.enableUDP:
            return None

        if not self.sock:
            self.logger.threaddebug(u"{}: udp_receive error: no socket".format(self.device.name))
            return
            
        try:
            data, addr = self.sock.recvfrom(2048)
        except socket.timeout, err:
            return
        except socket.error, err:
            self.logger.error(u"{}: udp_receive socket error: {}".format(device.name, err))
            stateList = [
                { 'key':'status',   'value':'socket Error'},
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return

            # send keep-alive
            self.sock.sock.sendto('\n', (self.address, 30007))

        try:
            raw_data = data.decode("utf-8")
            self.logger.threaddebug("{}".format(raw_data))
            json_data = json.loads(raw_data)        
        except Exception as err:
            self.logger.error(u"{}: udp_receive JSON decode error: {}".format(self.device.name, err))
            stateList = [
                { 'key':'status',   'value':'JSON Error'},
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return
            
        self.logger.threaddebug(u"{}: udp_receive:\n{}".format(self.device.name, json.dumps(json_data, sort_keys=True, indent=4, separators=(',', ': '))))
                   
        return json_data
