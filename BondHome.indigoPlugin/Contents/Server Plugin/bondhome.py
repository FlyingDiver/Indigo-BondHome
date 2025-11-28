#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import json
import logging
import requests
import socket
import time
from threading import Thread

PING_TIMEOUT = 60.0



################################################################################
class BondHome(object):

    def __init__(self, address, token):
        self.logger = logging.getLogger("Plugin.BondHome")
        self.address = address
        self.token_header = {'BOND-Token': token}
        self.bridge_data = {}
        self.udp_port = None
        self.sock = None
        self.callback = None
        self.receive_thread = Thread(target=self.udp_receive)
        self.receive_thread.daemon = True
        self.next_ping = time.time()
        self.logger.debug(f"BondHome __init__ address = {address}, token = {token}")

    def __del__(self):
        if self.sock:
            self.sock.close()

    ########################################
    # Bond Push UDP Protocol (BPUP)
    ########################################

    def udp_start(self, callback):
        self.callback = callback
        if not self.sock:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(PING_TIMEOUT)

        # start up the receiver thread
        self.receive_thread.start()
        self.logger.debug("udp_start() socket listener started")

        self.enable_bpup(True)

    def udp_receive(self):
        while True:
            now = time.time()
            if now > self.next_ping:
                self.sock.sendto('\n'.encode("utf-8"), (self.address, 30007))
                self.next_ping = now + PING_TIMEOUT

            try:
                json_data, address = self.sock.recvfrom(2048)
            except socket.timeout as err:
                continue
            except socket.error as err:
                raise
            else:
                data = json.loads(json_data.decode("utf-8"))

            if topic := data.get('t'):
                parts = topic.split('/')
                if parts[0] == 'devices' and parts[2] == 'state':   # state update
                    data['id'] = parts[1]
                    self.callback(data)

    def udp_stop(self):
        self.enable_bpup(False)
        if self.sock:
            self.sock.close()
            self.sock = None
            self.logger.debug("udp_stop() socket closed")

    ########################################
    # Commands to the Bridge
    ########################################

    def device_action(self, device_id, action, payload=None):
        url = f"http://{self.address}/v2/devices/{device_id}/actions/{action}"
        self.logger.debug(f"device_action, url = {url}, payload = {payload}")
        resp = requests.put(url, headers=self.token_header, json=payload)
        if not resp.ok:
            self.logger.warning(f"Device Action error {resp.status_code} for {url} with payload {payload}")

    def get_bridge_version(self):
        self.logger.debug(f"get_bridge_version: {self.address}")
        url = f"http://{self.address}/v2/sys/version"
        resp = requests.get(url, headers=self.token_header)
        resp.raise_for_status()
        return resp.json()

    def get_bridge_info(self):
        self.logger.debug(f"get_bridge_info: {self.address}")
        url = f"http://{self.address}/v2/bridge"
        resp = requests.get(url, headers=self.token_header)
        resp.raise_for_status()
        return resp.json()

    def set_bridge_info(self, data):
        self.logger.debug(f"set_bridge_info: {self.address} = {data}")
        url = f"http://{self.address}/v2/bridge"
        resp = requests.patch(url, headers=self.token_header, json=data)
        resp.raise_for_status()
        return resp.json()

    def get_device_list(self):
        self.logger.debug(f"get_device_list: {self.address}")
        url = f"http://{self.address}/v2/devices"
        resp = requests.get(url, headers=self.token_header)
        resp.raise_for_status()
        self.logger.debug(f"get_device_list: {resp.json()}")
        retList = []
        for key in resp.json():
            if not key.startswith("_"):     # skip internal keys
                retList.append(key)
        return retList

    def get_device(self, device_id):
        self.logger.debug(f"get_device: {device_id} @ {self.address}")
        url = f"http://{self.address}/v2/devices/{device_id}"
        resp = requests.get(url, headers=self.token_header)
        resp.raise_for_status()
        return resp.json()

    def get_device_state(self, device_id):
        self.logger.debug(f"get_device_state: {device_id} @ {self.address}")
        url = f"http://{self.address}/v2/devices/{device_id}/state"
        resp = requests.get(url, headers=self.token_header)
        resp.raise_for_status()
        return resp.json()

    def update_device_state(self, device_id, payload):
        self.logger.debug(f"update_device_state: {device_id} @ {self.address}, {payload}")
        url = f"http://{self.address}/v2/devices/{device_id}/state"
        resp = requests.patch(url, headers=self.token_header, json=payload)
        resp.raise_for_status()
        return resp.json()

    def get_device_command_list(self, device_id):
        self.logger.debug(f"get_device_command_list: {device_id} @ {self.address}")
        url = f"http://{self.address}/v2/devices/{device_id}/commands"
        resp = requests.get(url, headers=self.token_header)
        resp.raise_for_status()
        retList = []
        for key in resp.json():
            if not key.startswith("_"):     # skip internal keys
                retList.append(key)
        return retList

    def get_device_command(self, device_id, command_id):
        self.logger.debug(f"get_device_command: {device_id} @ {self.address}, {command_id}")
        url = f"http://{self.address}/v2/devices/{device_id}/commands/{command_id}"
        resp = requests.get(url, headers=self.token_header)
        resp.raise_for_status()
        return resp.json()

    def set_device_command_signal(self, device_id, command_id, payload):
        self.logger.debug(f"set_device_command_signal: {device_id} @ {self.address}, {command_id}, {payload}")
        url = f"http://{self.address}/v2/devices/{device_id}/commands/{command_id}/signal"
        resp = requests.patch(url, headers=self.token_header, json=payload)
        resp.raise_for_status()
        return resp.json()

    def enable_bpup(self, enable=True):
        self.logger.debug(f"enable_bpup: {enable} @ {self.address}")
        url = f"http://{self.address}/v2/api/bpup"
        payload = {"broadcast": enable}
        resp = requests.patch(url, headers=self.token_header, json=payload)
        resp.raise_for_status()
        return resp.json()
