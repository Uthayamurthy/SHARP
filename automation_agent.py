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

from datetime import datetime, time as dt_time
from time import sleep
import paho.mqtt.client as mqtt
import json
from sun_manager import SunManager
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base

# --- Database Setup for Agent Logging ---
Base = declarative_base()

class Log(Base):
    __tablename__ = 'log'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    entity = Column(String(100), nullable=False)
    event = Column(String(255), nullable=False)

try:
    # Use the same relative path as the main app
    engine = create_engine('sqlite:///instance/sharp.db')
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    print("SHARP AUTO AGENT: Database connection for logging established.")
except Exception as e:
    print(f"SHARP AUTO AGENT: Could not connect to DB for logging: {e}")
    SessionLocal = None

def agent_log_event(entity, event):
    if not SessionLocal:
        print(f"SHARP AUTO AGENT: DB not available. Log failed: {entity} - {event}")
        return
    session = SessionLocal()
    try:
        log_entry = Log(entity=entity, event=event)
        session.add(log_entry)
        session.commit()
    except Exception as e:
        print(f"SHARP AUTO AGENT: Error logging event: {e}")
        session.rollback()
    finally:
        session.close()
# --- End Database Setup ---


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
                msg = "Fired, turning ON target."
                print(f"SHARP AUTO AGENT TS: Automation '{self.alias}' {msg}")
                agent_log_event(f"SHARP-{self.alias}", msg)
                sleep(0.25)
                self.published_on = True
                self.published_off = False
        else:
            if self.on and not self.published_off:
                    msg = "Fired, turning OFF target."
                    print(f"SHARP AUTO AGENT TS: Automation '{self.alias}' {msg}")
                    self.client.publish(self.pub_topic, 'off', qos=1)
                    agent_log_event(f"SHARP-{self.alias}", msg)
                    self.published_off = True
                    self.published_on = False
                    sleep(0.25)

class SUNLIGHT_TRIGGERED:
    def __init__(self, client, pub_topic, sun_manager, params, alias=''):
        self.client = client
        self.pub_topic = pub_topic
        self.sun_manager = sun_manager
        self.params = params
        self.alias = alias
        
        self.on = False
        self.published_on = False
        self.client.publish(self.pub_topic, 'off', qos=1)
        self.published_off = True

    def _get_trigger_time(self, trigger_info, sunrise, sunset):
        trigger_type = trigger_info.get('type')
        trigger_value = trigger_info.get('value')

        if trigger_type == 'Sunrise':
            return sunrise
        elif trigger_type == 'Sunset':
            return sunset
        elif trigger_type == 'Time' and trigger_value:
            try:
                return datetime.strptime(trigger_value, '%H:%M').time()
            except (ValueError, TypeError):
                return None
        return None

    def is_time(self):
        time_now = datetime.now().time()
        today = datetime.now().date()
        
        sunrise, sunset = self.sun_manager.get_sun_times(today)

        start_time = self._get_trigger_time(self.params['start'], sunrise, sunset)
        end_time = self._get_trigger_time(self.params['end'], sunrise, sunset)

        if not start_time or not end_time:
            print(f"SHARP AUTO AGENT ST: Invalid trigger time for {self.alias}. Skipping check.")
            return False

        if start_time < end_time:
            return time_now >= start_time and time_now <= end_time
        else: # Over Midnight Condition
            return time_now >= start_time or time_now <= end_time

    def on_ack(self, state):
        if state.lower() == 'on':
            self.on = True
        else:
            self.on = False

    def loop(self):
        if self.is_time():
            if not self.on and not self.published_on:
                self.client.publish(self.pub_topic, 'on', qos=1)
                msg = "Fired, turning ON target."
                print(f"SHARP AUTO AGENT ST: Automation '{self.alias}' {msg}")
                agent_log_event(f"SHARP-{self.alias}", msg)
                sleep(0.25)
                self.published_on = True
                self.published_off = False
        else:
            if self.on and not self.published_off:
                self.client.publish(self.pub_topic, 'off', qos=1)
                msg = "Fired, turning OFF target."
                print(f"SHARP AUTO AGENT ST: Automation '{self.alias}' {msg}")
                agent_log_event(f"SHARP-{self.alias}", msg)
                self.published_off = True
                self.published_on = False
                sleep(0.25)

class AUTO_AGENT:
    def __init__(self, conn):
        self.CONNECTED = False
        self.conn = conn
        self.automators = []
        self.msg_handles = {}

        with open('config/flask_app_conf.json', 'r') as f:
            app_conf = json.load(f)
        self.sun_manager = SunManager(app_conf)

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
            if not auto_info.get('enabled', False):
                continue

            pub_topic = self.devices_info[auto_info['location']][auto_info['device']][auto_info['actionable']]['action_topic']
            ack_topic = self.devices_info[auto_info['location']][auto_info['device']][auto_info['actionable']]['ack_topic']

            auto_instance = None
            if auto_info['AUTO_TYPE'] == 'TIME-SCHEDULED':
                auto_instance = TIME_SCHEDULER(
                    self.client, pub_topic, 
                    auto_info['AUTO_PARAMS']['start_time'], 
                    auto_info['AUTO_PARAMS']['end_time'], 
                    alias=auto_name
                )
                print(f"SHARP AUTO AGENT : Loaded automator - {auto_name}, TYPE - TIME-SCHEDULED")

            elif auto_info['AUTO_TYPE'] == 'SUNLIGHT-TRIGGERED':
                auto_instance = SUNLIGHT_TRIGGERED(
                    self.client, pub_topic,
                    self.sun_manager,
                    auto_info['AUTO_PARAMS'],
                    alias=auto_name
                )
                print(f"SHARP AUTO AGENT : Loaded automator - {auto_name}, TYPE - SUNLIGHT-TRIGGERED")
            
            if auto_instance:
                self.automators.append(auto_instance)
                if ack_topic not in self.msg_handles:
                    self.msg_handles[ack_topic] = [auto_instance.on_ack]
                else:
                    self.msg_handles[ack_topic].append(auto_instance.on_ack)

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
        last_sun_check = datetime.now()

        while True:
            if (datetime.now() - last_sun_check).total_seconds() > 3600:
                self.sun_manager.update_if_needed()
                last_sun_check = datetime.now()

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