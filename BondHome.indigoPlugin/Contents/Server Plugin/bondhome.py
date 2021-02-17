#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import json
import logging
import requests
import socket
import time
from threading import Thread

TIMEOUT = 60.0
          
################################################################################

class BondHome(object):

    def __init__(self, address, token):
        self.logger = logging.getLogger("Plugin.BondHome")

        self.address = address
        self.token_header = {'BOND-Token': token}
        self.bridge_data =  {}
         
        self.udp_port = None
        self.sock = None
        self.callback = None
        
        self.logger.debug(u"BondHome __init__ address = {}, token = {}".format(address, token))
                    
    def __del__(self):
        device = indigo.devices[self.deviceID]
        self.sock.close()
        self.stopFlag.set()


    ########################################
    # Bond Push UDP Protocol (BPUP)
    ########################################

    def udp_start(self, callback):
        self.callback = callback
        if not self.sock:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.settimeout(TIMEOUT)
            except:
                raise
            else:
                self.logger.debug(u"udp_start() socket listener started")

        # start up the receiver thread        
        self.receive_thread = Thread(target=self.udp_receive)
        self.receive_thread.daemon = True
        self.receive_thread.start()
        
    def udp_receive(self):
        self.next_ping = time.time()
    
        while True: 
            now = time.time()
            if now > self.next_ping:
                self.sock.sendto('\n', (self.address, 30007))
                self.next_ping = now + TIMEOUT
                
            try:
                json_data, addr = self.sock.recvfrom(2048)
            except socket.timeout as err:
                continue
            except socket.error as err:
                raise
            else:
                try:
                    data = json.loads(json_data.decode("utf-8"))
                except Exception as err:
                    raise

                # don't send ping acks
                if len(data) == 1:
                    continue
                    
                # fix up the data

                topic = data['t'].split('/')
                data['id'] = topic[1]

                self.callback(data)


    ########################################
    # Commands to the Bridge
    ########################################
    
    def device_action(device_id, action, payload={}):
        url = "http://{}/v2/devices/{}/actions/{}".format(self.address, device_id, action)
        self.logger.debug(u"device_action, url = {}, payload = {}".format(url, payload))
        try:
            resp = requests.put(url, headers=self.token_header, json=payload)
            resp.raise_for_status()
        except:
            raise
        self.logger.debug(u"device_action, resp = {}".format(resp))
        return resp


    def get_bridge_version(self):
        self.logger.debug(u"get_bridge_version()")
            
        url = "http://{}/v2/sys/version".format(self.address)
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except:
            raise
        return resp.json()

    def get_bridge_info(self):
        self.logger.debug(u"get_bridge_info()")
            
        url = "http://{}/v2/bridge".format(self.address)
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except:
            raise            
        return resp.json()

    def set_bridge_info(self, device_id, data):
        
        url = "http://{}/v2/bridge".format(self.address)
        data = {"reps": int(reps)}
        try:
            resp = requests.patch(url, headers=self.token_header, params=data)
            resp.raise_for_status()
        except:
            raise
        return resp.json()
        
    def get_device_list(self):
        self.logger.debug(u"get_device_list()")
            
        url = "http://{}/v2/devices".format(self.address)
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except:
            raise
        self.logger.debug(u"get_device_list: {}".format(resp.json()))

        retList = []
        for key in resp.json():    
            if key != "_": 
                retList.append(key)   
        return retList

    def get_device(self, device_id):
        
        url = "http://{}/v2/devices/{}".format(self.address, device_id)
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except:
            raise
        return resp.json()
                                
    def get_device_command_list(self, device_id):
        
        url = "http://{}/v2/devices/{}/commands".format(self.address, device_id)
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except:
            raise
        return resp.json()
                                    
    def get_device_command(self, device_id, command_id):
        
        url = "http://{}/v2/devices/{}/commands/{}".format(self.address, device_id, command_id)
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except:
            raise
        return resp.json()
                                
    def set_device_command_reps(self, device_id, command_id, reps):
        
        url = "http://{}/v2/devices/{}/commands/{}/signal".format(self.address, device_id, command_id)
        data = {"reps": int(reps)}
        try:
            resp = requests.patch(url, headers=self.token_header, params=data)
            resp.raise_for_status()
        except:
            raise
        return resp.json()
                                