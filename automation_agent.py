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

from datetime import datetime, time as dt_time, date, timedelta
from time import sleep
import paho.mqtt.client as mqtt
import json
import os
from sun_manager import SunManager
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Date, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, scoped_session

basedir = os.path.abspath(os.path.dirname(__file__))

# --- Database Setup for Agent ---
Base = declarative_base()

class Log(Base):
    __tablename__ = 'log'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    entity = Column(String(100), nullable=False)
    event = Column(String(255), nullable=False)

class SmartRepetitionState(Base):
    __tablename__ = 'smart_repetition_state'
    id = Column(Integer, primary_key=True)
    automation_name = Column(String(100), nullable=False)
    run_date = Column(Date, nullable=False, default=datetime.utcnow().date)
    successful_runs = Column(Integer, default=0)
    status = Column(String(20), default='RUNNING')
    tasks = relationship('SmartRepetitionTask', backref='state', lazy='subquery', cascade="all, delete-orphan")

class SmartRepetitionTask(Base):
    __tablename__ = 'smart_repetition_task'
    id = Column(Integer, primary_key=True)
    state_id = Column(Integer, ForeignKey('smart_repetition_state.id'), nullable=False)
    task_index = Column(Integer, nullable=False)
    status = Column(String(20), default='PENDING')
    attempts = Column(Integer, default=0)
    last_attempt_time = Column(DateTime, nullable=True)
    completion_time = Column(DateTime, nullable=True)


try:
    db_path = os.path.join(basedir, 'instance', 'sharp.db')
    engine = create_engine(f'sqlite:///{db_path}')
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    ScopedSession = scoped_session(session_factory)
    print("SHARP AUTO AGENT: Database connection established.")
except Exception as e:
    print(f"SHARP AUTO AGENT: Could not connect to DB: {e}")
    ScopedSession = None

def agent_log_event(entity, event):
    if not ScopedSession:
        print(f"SHARP AUTO AGENT: DB not available. Log failed: {entity} - {event}")
        return
    session = ScopedSession()
    try:
        log_entry = Log(entity=entity, event=event)
        session.add(log_entry)
        session.commit()
    except Exception as e:
        print(f"SHARP AUTO AGENT: Error logging event: {e}")
        session.rollback()
    finally:
        ScopedSession.remove()
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
        self.client.publish(self.pub_topic, 'off', qos=1)
        self.published_off = True
    def is_time(self):
        time_now = datetime.now().time()
        if self.start_time < self.end_time: return time_now >= self.start_time and time_now <= self.end_time
        else: return time_now >= self.start_time or time_now <= self.end_time
    def on_ack(self, state):
        if state.lower() == 'on': self.on = True
        else: self.on = False
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
        if trigger_type == 'Sunrise': return sunrise
        elif trigger_type == 'Sunset': return sunset
        elif trigger_type == 'Time' and trigger_value:
            try: return datetime.strptime(trigger_value, '%H:%M').time()
            except (ValueError, TypeError): return None
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
        if start_time < end_time: return time_now >= start_time and time_now <= end_time
        else: return time_now >= start_time or time_now <= end_time
    def on_ack(self, state):
        if state.lower() == 'on': self.on = True
        else: self.on = False
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

class SMART_REPETITION:
    def __init__(self, client, pub_topic, params, alias=''):
        self.client = client
        self.pub_topic = pub_topic
        self.params = params
        self.alias = alias
        self.time_format = "%H:%M"

        # In-memory state for the active cycle
        self.active_task_id = None
        self.active_cycle_end_time = None
        self.ack_received = None # 'on' or 'off'

        # Cooldowns and timeouts
        self.RETRY_COOLDOWN = timedelta(minutes=5)
        self.ACK_TIMEOUT = timedelta(seconds=60)
        self.MAKEUP_COOLDOWN = timedelta(minutes=15)

    def _get_or_create_daily_state(self, session, today):
        state = session.query(SmartRepetitionState).filter_by(automation_name=self.alias, run_date=today).first()
        if not state:
            agent_log_event(f"SHARP-{self.alias}", f"Creating new daily state for {today}.")
            state = SmartRepetitionState(automation_name=self.alias, run_date=today)
            session.add(state)
            session.flush() # To get state.id for tasks
            for i, _ in enumerate(self.params['repetitions']):
                task = SmartRepetitionTask(state_id=state.id, task_index=i)
                session.add(task)
            session.commit()
            print(f"SHARP AUTO AGENT SR: Created new state for '{self.alias}' for {today}")
        return state

    def on_ack(self, payload):
        if not self.active_task_id:
            return

        if payload.lower() == 'on':
            self.ack_received = 'on'
            print(f"SHARP AUTO AGENT SR: '{self.alias}' received ON ack for task {self.active_task_id}.")
        elif payload.lower() == 'off':
            self.ack_received = 'off'
            print(f"SHARP AUTO AGENT SR: '{self.alias}' received OFF ack for task {self.active_task_id}.")

    def _fail_active_task(self, session, reason):
        if not self.active_task_id: return
        
        task = session.query(SmartRepetitionTask).get(self.active_task_id)
        if task and task.status == 'ACTIVE':
            task.status = 'FAILED'
            session.commit()
            agent_log_event(f"SHARP-{self.alias}", f"Cycle for task index {task.task_index} failed: {reason}.")
            print(f"SHARP AUTO AGENT SR: '{self.alias}' task {self.active_task_id} FAILED. Reason: {reason}")
        
        # Reset in-memory state
        self.active_task_id = None
        self.active_cycle_end_time = None
        self.ack_received = None

    def loop(self):
        session = ScopedSession()
        try:
            today = date.today()
            time_now = datetime.now()
            state = self._get_or_create_daily_state(session, today)

            if state.status == 'COMPLETE':
                return
            
            # --- Handle Active Cycle ---
            if self.active_task_id:
                task = session.query(SmartRepetitionTask).get(self.active_task_id)

                # Check for successful completion
                if self.ack_received == 'off':
                    task.status = 'SUCCESS'
                    task.completion_time = time_now
                    state.successful_runs = state.successful_runs + 1
                    session.commit()
                    agent_log_event(f"SHARP-{self.alias}", f"Cycle for task index {task.task_index} completed successfully.")
                    print(f"SHARP AUTO AGENT SR: '{self.alias}' task {task.id} SUCCESS.")
                    self.active_task_id = None # End of cycle
                    return

                # Check for cycle timeout (end of duration)
                if time_now >= self.active_cycle_end_time:
                    if self.ack_received == 'on': # It turned on, now try to turn it off
                        print(f"SHARP AUTO AGENT SR: '{self.alias}' duration ended. Publishing OFF for task {self.active_task_id}.")
                        self.client.publish(self.pub_topic, 'off', qos=1)
                        # Now we wait for the 'off' ack, but with a timeout
                        if 'off_ack_timeout' not in self.__dict__ or not self.off_ack_timeout:
                             self.off_ack_timeout = time_now + self.ACK_TIMEOUT
                        
                        if time_now > self.off_ack_timeout:
                            self._fail_active_task(session, "Did not receive OFF acknowledgement in time.")
                            self.off_ack_timeout = None

                    else: # It never even turned on
                        self._fail_active_task(session, "Did not receive ON acknowledgement in time.")
                return # Still handling an active task, don't start a new one

            # --- Find and Start a New Task ---
            all_tasks_finished_for_day = True
            for i, task_config in enumerate(self.params['repetitions']):
                task = state.tasks[i]
                
                if task.status in ['SUCCESS', 'ACTIVE']:
                    continue

                all_tasks_finished_for_day = False
                
                feasible_start = datetime.strptime(task_config['feasible_start'], self.time_format).time()
                feasible_end = datetime.strptime(task_config['feasible_end'], self.time_format).time()

                # If task failed, check for retry cooldown
                if task.status == 'FAILED' and task.last_attempt_time:
                    if time_now < task.last_attempt_time + self.RETRY_COOLDOWN:
                        continue # In cooldown, skip for now

                if feasible_start <= time_now.time() <= feasible_end:
                    # Check if there's enough time for a full cycle
                    duration_td = timedelta(minutes=self.params['duration_minutes'])
                    if time_now + duration_td > time_now.replace(hour=feasible_end.hour, minute=feasible_end.minute, second=0):
                        continue # Not enough time left in window
                    
                    # Start this task
                    self.active_task_id = task.id
                    self.active_cycle_end_time = time_now + duration_td
                    self.ack_received = None
                    self.off_ack_timeout = None

                    task.status = 'ACTIVE'
                    task.attempts += 1
                    task.last_attempt_time = time_now
                    session.commit()

                    self.client.publish(self.pub_topic, 'on', qos=1)
                    msg = f"Starting cycle for task index {i} (Attempt {task.attempts})."
                    agent_log_event(f"SHARP-{self.alias}", msg)
                    print(f"SHARP AUTO AGENT SR: '{self.alias}' {msg}")
                    return # Exit loop for this iteration, we have an active task

            # --- Handle End-of-Day Reconciliation (Make-up Mode) ---
            if all_tasks_finished_for_day:
                last_window_end_time = datetime.strptime(self.params['repetitions'][-1]['feasible_end'], self.time_format).time()
                if time_now.time() > last_window_end_time:
                    if state.successful_runs < self.params['min_repetitions']:
                        # Check cooldown for make-up runs
                        last_failed_task = next((t for t in reversed(state.tasks) if t.status == 'FAILED'), None)
                        if last_failed_task and last_failed_task.last_attempt_time and time_now < last_failed_task.last_attempt_time + self.MAKEUP_COOLDOWN:
                            return # In cooldown from last failed attempt, wait.

                        # Start a make-up cycle
                        # We create a pseudo-task for make-up
                        task = SmartRepetitionTask(state_id=state.id, task_index=99, status='ACTIVE', attempts=1, last_attempt_time=time_now)
                        session.add(task)
                        session.commit()

                        self.active_task_id = task.id
                        self.active_cycle_end_time = time_now + timedelta(minutes=self.params['duration_minutes'])
                        self.ack_received = None
                        self.off_ack_timeout = None

                        self.client.publish(self.pub_topic, 'on', qos=1)
                        msg = f"Entering make-up mode. Starting cycle ({state.successful_runs + 1}/{self.params['min_repetitions']})."
                        agent_log_event(f"SHARP-{self.alias}", msg)
                        print(f"SHARP AUTO AGENT SR: '{self.alias}' {msg}")

                    else:
                        state.status = 'COMPLETE'
                        session.commit()
                        agent_log_event(f"SHARP-{self.alias}", "All cycles complete for the day.")
                        print(f"SHARP AUTO AGENT SR: '{self.alias}' All tasks completed for today.")

        except Exception as e:
            print(f"SHARP AUTO AGENT SR: FATAL_ERROR in '{self.alias}' loop: {e}")
            session.rollback()
        finally:
            ScopedSession.remove()


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
            auto_type = auto_info['AUTO_TYPE']

            if auto_type == 'TIME-SCHEDULED':
                auto_instance = TIME_SCHEDULER(
                    self.client, pub_topic, 
                    auto_info['AUTO_PARAMS']['start_time'], 
                    auto_info['AUTO_PARAMS']['end_time'], 
                    alias=auto_name
                )
            elif auto_type == 'SUNLIGHT-TRIGGERED':
                auto_instance = SUNLIGHT_TRIGGERED(
                    self.client, pub_topic,
                    self.sun_manager,
                    auto_info['AUTO_PARAMS'],
                    alias=auto_name
                )
            elif auto_type == 'SMART-REPETITION':
                auto_instance = SMART_REPETITION(
                    self.client, pub_topic,
                    auto_info['AUTO_PARAMS'],
                    alias=auto_name
                )

            if auto_instance:
                print(f"SHARP AUTO AGENT : Loaded automator - {auto_name}, TYPE - {auto_type}")
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
            sleep(0.5) # Increased sleep a bit for SR class

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