'''
S.H.A.R.P - Smart Home Automation Research Project

    Copyright (C) 2024  R Uthaya Murthy

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.

Contact Author : uthayamurthy2006@gmail.com
'''

from datetime import datetime
from time import sleep
import paho.mqtt.client as mqtt
import json

class TIME_SCHEDULER:
    def __init__(self, client, pub_topic, start_time, end_time, alias=''):
        self.client = client
        self.pub_topic = pub_topic
        self.alias = alias

        time_format = "%H:%M"
        self.start_time = datetime.strptime(start_time, time_format).time()
        self.end_time = datetime.strptime(end_time, time_format).time()
        self.on = False
        self.published_on = False

        self.client.publish(self.pub_topic, 'off', qos=1) # Publish 'off' to start with
        self.published_off = True

    def is_time(self):
        time_now = datetime.now().time()

        if self.start_time < self.end_time:
            return time_now >= self.start_time and time_now <= self.end_time
        else: # Over Midnight Condition
            return time_now >= self.start_time or time_now <= self.end_time
    
    def on_ack(self, state):
        if state.lower() == 'on':
            self.on = True
        else:
            self.on = False

    def loop(self):

        if self.is_time():
            if not self.on and not self.published_on:
                self.client.publish(self.pub_topic, 'on', qos=1)
                print(f"SHARP AUTO AGENT TS: Published 'on' to {self.pub_topic} for automation - {self.alias}")
                sleep(0.25)
                self.published_on = True
                self.published_off = False
        else:
            if self.on and not self.published_off:
                    print(f"SHARP AUTO AGENT TS: Published 'off' to {self.pub_topic} for automation - {self.alias}")
                    self.client.publish(self.pub_topic, 'off', qos=1)
                    self.published_off = True
                    self.published_on = False
                    sleep(0.25)
                    


class AUTO_AGENT:

    def __init__(self, conn):
        self.CONNECTED = False
        self.conn = conn

        self.automators = []
        self.msg_handles = {}
    
    def load_info(self):
        with open('data/devices_info.json', 'r') as di_file:
            self.devices_info = json.load(di_file)

        with open('data/automations.json', 'r') as am_file:
            self.automations = json.load(am_file)

    def connect(self):

        with open('config/mqtt_conf.json', 'r') as f:
            mqtt_conf = json.load(f)

        self.client = mqtt.Client(mqtt_conf['MQTT_AUTO_AGENT_CLIENT_ID'], True)
        self.client.username_pw_set(mqtt_conf["MQTT_USERNAME"], password=mqtt_conf["MQTT_PASSWORD"])
        self.client.on_connect= self.on_connect
        self.client.connect(mqtt_conf['MQTT_HOST'], port=mqtt_conf['MQTT_PORT'])
        self.client.loop_start()

        sleep(0.5)

        while self.CONNECTED != True:
            sleep(0.1)
            print('SHARP AUTO AGENT : Waiting for MQTT connection ......')
            
    def init_automators(self):
        for auto_name, auto_info in self.automations.items():
            if auto_info['AUTO_TYPE'] == 'TIME-SCHEDULED' and auto_info['enabled'] == True:
                pub_topic = self.devices_info[auto_info['location']][auto_info['device']][auto_info['actionable']]['action_topic']
                ack_topic = self.devices_info[auto_info['location']][auto_info['device']][auto_info['actionable']]['ack_topic']

                ts = TIME_SCHEDULER(self.client, pub_topic, auto_info['AUTO_PARAMS']['start_time'], auto_info['AUTO_PARAMS']['end_time'], alias=auto_name)
                self.automators.append(ts)

                if ack_topic not in self.msg_handles:
                    self.msg_handles[ack_topic] = [ts.on_ack]
                else:
                    self.msg_handles[ack_topic].append(ts.on_ack)

                print(f"SHARP AUTO AGENT : Loaded automator - {auto_name}, TYPE - TIME-SCHEDULED, for {auto_info['location']}::{auto_info['device']}::{auto_info['actionable']}")            

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f'SHARP AUTO AGENT : Connected to MQTT Broker !')
            self.CONNECTED = True
        else:
            print(f'SHARP AUTO AGENT : Failed to connect to MQTT Broker :(')
    
    def on_message(self, client, userdata, message):
        payload = str(message.payload.decode("utf-8"))
        topic = message.topic

        if topic in self.msg_handles:
            for handle in self.msg_handles[topic]:
                handle(payload)
    
    def subscribe(self):
        for topic in self.msg_handles:
            self.client.subscribe(topic)

        self.client.on_message = self.on_message
    
    def unsubscribe(self):
        for topic in self.msg_handles:
            self.client.unsubscribe(topic)
        self.client.on_message = None

    def start_loop(self):
        while True:
            for auto in self.automators:
                auto.loop()
            sleep(0.25)

            if self.conn.poll():
                msg = self.conn.recv()
                if msg == 'RELOAD':
                    self.unsubscribe()
                    self.automators = []
                    self.msg_handles = {}
                    self.load_info()
                    self.init_automators()
                    self.subscribe()
                    print(f"SHARP AUTO AGENT : Reloaded Automations !")
                if msg == 'STOP':
                    print(f"SHARP AUTO AGENT : Stopping Automation Agent Gracefully !")
                    self.client.loop_stop()
                    self.client.disconnect()
                    print("SHARP AUTO AGENT : Exiting")
                    exit(0)
            
                    
    def start_agent(self):
        print('SHARP AUTO AGENT : Started !')
              
        self.load_info()

        self.connect()

        self.init_automators()
        
        self.subscribe()

        sleep(5)
        self.start_loop()
