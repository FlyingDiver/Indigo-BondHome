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
                self.sock.settimeout(PING_TIMEOUT)
            except (Exception,):
                raise
            else:
                self.logger.debug(u"udp_start() socket listener started")

        # start up the receiver thread
        self.receive_thread.start()

    def udp_receive(self):
        while True:
            now = time.time()
            if now > self.next_ping:
                self.sock.sendto('\n', (self.address, 30007))
                self.next_ping = now + PING_TIMEOUT

            try:
                json_data, address = self.sock.recvfrom(2048)
            except socket.timeout as err:
                continue
            except socket.error as err:
                raise
            else:
                try:
                    data = json.loads(json_data.decode("utf-8"))
                except Exception as err:
                    raise

                # don't send ping ack
                if len(data) == 1:
                    continue

                # fix up the data

                topic = data['t'].split('/')
                data['id'] = topic[1]

                self.callback(data)

    ########################################
    # Commands to the Bridge
    ########################################

    def device_action(self, device_id, action, payload=None):
        if not payload:
            payload = {}
        url = f"http://{self.address}/v2/devices/{device_id}/actions/{action}"
        self.logger.debug(f"device_action, url = {url}, payload = {payload}")
        try:
            resp = requests.put(url, headers=self.token_header, json=payload)
            resp.raise_for_status()
        except (Exception,):
            raise
        self.logger.debug(f"device_action, resp = {resp}")
        return resp

    def get_bridge_version(self):
        url = f"http://{self.address}/v2/sys/version"
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except (Exception,):
            raise
        return resp.json()

    def get_bridge_info(self):
        url = f"http://{self.address}/v2/bridge"
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except (Exception,):
            raise
        return resp.json()

    def set_bridge_info(self, data):
        url = f"http://{self.address}/v2/bridge"
        try:
            resp = requests.patch(url, headers=self.token_header, json=data)
            resp.raise_for_status()
        except (Exception,):
            raise
        return resp.json()

    def get_device_list(self):
        url = f"http://{self.address}/v2/devices"
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except (Exception,):
            raise
        self.logger.debug(f"get_device_list: {resp.json()}")

        retList = []
        for key in resp.json():
            if not key.startswith("_"):     # skip internal keys
                retList.append(key)
        return retList

    def get_device(self, device_id):
        url = f"http://{self.address}/v2/devices/{device_id}"
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except (Exception,):
            raise
        return resp.json()

    def get_device_state(self, device_id):
        url = f"http://{self.address}/v2/devices/{device_id}/state"
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except (Exception,):
            raise
        return resp.json()

    def update_device_state(self, device_id, payload):
        url = f"http://{self.address}/v2/devices/{device_id}/state"
        try:
            resp = requests.patch(url, headers=self.token_header, json=payload)
            resp.raise_for_status()
        except (Exception,):
            raise
        return resp.json()

    def get_device_command_list(self, device_id):
        url = f"http://{self.address}/v2/devices/{device_id}/commands"
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except (Exception,):
            raise
        retList = []
        for key in resp.json():
            if not key.startswith("_"):     # skip internal keys
                retList.append(key)
        return retList

    def get_device_command(self, device_id, command_id):
        url = "http://{}/v2/devices/{}/commands/{}".format(self.address, device_id, command_id)
        try:
            resp = requests.get(url, headers=self.token_header)
            resp.raise_for_status()
        except (Exception,):
            raise
        return resp.json()

    def set_device_command_signal(self, device_id, command_id, payload):
        url = "http://{}/v2/devices/{}/commands/{}/signal".format(self.address, device_id, command_id)
        try:
            resp = requests.patch(url, headers=self.token_header, json=payload)
            resp.raise_for_status()
        except (Exception,):
            raise
        return resp.json()
