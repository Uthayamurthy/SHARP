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

from flask import Flask
from flask_socketio import SocketIO
from flask_mqtt import Mqtt
from time import sleep
from __version__ import version
from auth import auth_bp
from routes import main_bp, format_time_12hr, dashless, to_ist
from extensions import db, bcrypt, login_manager
from models import User, Log
from automation_agent import AUTO_AGENT
from database_logger import log_event
import multiprocessing
import json
import signal
import os
import threading
import time

print('SHARP: Starting up...')

app = Flask(__name__)

with open('config/flask_app_conf.json', 'r') as f:
    flask_conf = json.load(f)
with open('config/mqtt_conf.json', 'r') as f:
    mqtt_conf = json.load(f)
with open('data/devices_info.json') as f:
    devices_info_data = json.load(f)

for location, devices in devices_info_data.items():
    for device_name, device_info in devices.items():
        device_info.setdefault('online_status', 'waiting')
        device_info.setdefault('last_seen', 0)
        device_info.setdefault('start_time', time.time())

app.config['SECRET_KEY'] = flask_conf['SECRET_KEY']
app.config['TEMPLATES_AUTO_RELOAD'] = flask_conf['TEMPLATES_AUTO_RELOAD']
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///../instance/sharp.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['MQTT_BROKER_URL'] = mqtt_conf['MQTT_HOST']
app.config['MQTT_BROKER_PORT'] = mqtt_conf['MQTT_PORT']
app.config['MQTT_CLIENT_ID'] = mqtt_conf["MQTT_SHARP_CLIENT_ID"]
app.config['MQTT_USERNAME'] = mqtt_conf["MQTT_USERNAME"]
app.config['MQTT_PASSWORD'] = mqtt_conf["MQTT_PASSWORD"]
app.config['MQTT_KEEPALIVE'] = mqtt_conf['MQTT_KEEP_ALIVE']
app.config['MQTT_TLS_ENABLED'] = mqtt_conf['MQTT_TLS_ENABLED']
app.config['MQTT_LAST_WILL_TOPIC'] = mqtt_conf['MQTT_LAST_WILL_TOPIC']
app.config['MQTT_LAST_WILL_MESSAGE'] = mqtt_conf['MQTT_LAST_WILL_MESSAGE']
app.config['MQTT_LAST_WILL_QOS'] = mqtt_conf['MQTT_LAST_WILL_QOS']


app.config['DEVICES_INFO'] = devices_info_data

db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)


mqtt = Mqtt(app) # MQTT needs to be initialized with app context here
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

app.register_blueprint(auth_bp)
app.register_blueprint(main_bp)

app.jinja_env.filters['format_time'] = format_time_12hr
app.jinja_env.filters['dashless'] = dashless
app.jinja_env.filters['to_ist'] = to_ist


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

agent_conn, child_conn = multiprocessing.Pipe()
app.config['AGENT_CONN'] = agent_conn
automation_process = None

def start_auto_agent():
    global automation_process
    my_agent = AUTO_AGENT(child_conn)
    automation_process = multiprocessing.Process(target=my_agent.start_agent)
    automation_process.daemon = True
    automation_process.start()

health_topic_map = {}
ack_topic_map = {}

def mqtt_setup():
    """ Creates lookup maps and subscribes to all necessary MQTT topics. """
    global health_topic_map, ack_topic_map
    for location, devices in devices_info_data.items():
        for device_name, device_info in devices.items():
            # Subscribe to health topic if it exists
            if 'health_topic' in device_info:
                health_topic = device_info['health_topic']
                mqtt.subscribe(topic=health_topic)

                health_topic_map[health_topic] = {
                    'location': location,
                    'device_name': device_name,
                    'info': device_info
                }
                print(f"SHARP: Subscribed to health topic for {device_name}: {health_topic}")

            for actionable_name, info in device_info.items():
                if isinstance(info, dict) and 'ack_topic' in info:
                    topic = info['ack_topic']
                    try:
                        mqtt.subscribe(topic=topic)
                        ack_topic_map[topic] = {
                            'location': location,
                            'device_name': device_name,
                            'actionable_name': actionable_name,
                            'actionable_info': info # Direct reference to the actionable's dict
                        }
                    except Exception as e:
                        print(f'SHARP: Failed to subscribe to topic {topic}: {e}')

@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    topic = message.topic
    payload_str = message.payload.decode()

    # --- Health Message Handling ---
    if topic in health_topic_map:
        device_context = health_topic_map[topic]
        device_info = device_context['info']
        
        try:
            health_data = json.loads(payload_str)
            current_time = time.time()

            if health_data.get('status') == 'online':
                prev_status = device_info.get('online_status', 'waiting')
                
                device_info['online_status'] = 'online'
                device_info['last_seen'] = current_time 
                device_info['health_data'] = health_data
                
                print(f"SHARP: Health check PASSED for {device_context['device_name']}. Status: online.")

                if prev_status != 'online':
                    with app.app_context():
                        log_event(f"Device ({device_context['device_name']}@{device_context['location']})", "Came online")

                socketio.emit('update_health', data={
                    'location': device_context['location'],
                    'device': device_context['device_name'], 
                    'status': 'online',
                    'last_seen': current_time,
                    'health_data': health_data
                })

        except (json.JSONDecodeError, KeyError) as e:
            print(f"SHARP: Could not parse health message from {topic}: {e}")
        return

    # --- Acknowledgment (State Change) Message Handling ---
    if topic in ack_topic_map:
        context = ack_topic_map[topic]
        state = payload_str

        # Update the state in the original devices_info_data dictionary
        context['actionable_info']['state'] = state
        
        # Prepare data for the frontend
        obj_id = f"{context['location']}-{context['device_name']}-{context['actionable_name']}"
        
        print(f'SHARP: Received message from {obj_id}, New state is "{state}"')
        
        # Log the event
        with app.app_context():
            entity_name = f"Device ({context['device_name']}@{context['location']})"
            event_details = f"'{context['actionable_name']}' state changed to '{state}'"
            log_event(entity_name, event_details)

        # Emit the update to the frontend
        socketio.emit('update_state', data={'obj_id': obj_id, 'state': state})
        return

@socketio.on('connect')
def on_connect():
    from flask_login import current_user
    if current_user.is_authenticated:
        socketio.send('Socket server ready.')
        socketio.emit('devices_info', data=devices_info_data)
    else:
        print("SHARP: Unauthenticated user tried to connect to socket.")


@socketio.on('publish')
def on_publish(data):
    from flask_login import current_user
    if current_user.is_authenticated:
        topic = data['topic']
        state = data['state']
        sleep(0.1)
        mqtt.publish(topic, state, qos=1)

def handle_sigterm(*args):
    print("SHARP: SIGTERM received, shutting down gracefully...")
    if mqtt.client:
        mqtt.client.loop_stop()
        mqtt.client.disconnect()
    if agent_conn:
        agent_conn.send('STOP')
    print("SHARP: Exiting...")
    exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)


def check_device_liveness():
    with app.app_context():
        while True:
            now = time.time()
            for location, devices in devices_info_data.items():
                for device_name, device_info in devices.items():
                    
                    if 'health_interval_sec' not in device_info:
                        continue

                    current_status = device_info.get('online_status')

                    if current_status == 'waiting':
                        initial_wait_time = device_info['health_interval_sec'] * 1.5 
                        start_time = device_info.get('start_time', 0)

                        if now - start_time > initial_wait_time:
                            if device_info['online_status'] != 'offline':
                                print(f"SHARP: Initial health ping not received for {device_name}. Marking as offline.")
                                device_info['online_status'] = 'offline'
                                log_event(f"Device ({device_name}@{location})", "Went offline")
                                socketio.emit('update_health', data={
                                    'location': location,
                                    'device': device_name,
                                    'status': 'offline'
                                })

                    elif current_status == 'online':
                        timeout = device_info['health_interval_sec'] * 2.5 
                        last_seen = device_info.get('last_seen', 0)

                        if now - last_seen > timeout:
                            if device_info['online_status'] != 'offline':
                                print(f"SHARP: Health check FAILED for {device_name}. Marking as offline.")
                                device_info['online_status'] = 'offline'
                                log_event(f"Device ({device_name}@{location})", "Went offline")
                                socketio.emit('update_health', data={
                                    'location': location,
                                    'device': device_name,
                                    'status': 'offline'
                                })
            
            time.sleep(10)

# Start the liveness checker in a daemon thread so it exits with the app
liveness_thread = threading.Thread(target=check_device_liveness)
liveness_thread.daemon = True

with app.app_context():
    db.create_all()

    setup_flag_path = os.path.join(app.instance_path, 'setup.flag')
    
    if not os.path.exists(setup_flag_path):
        print("SHARP: First-time setup detected. Creating default admin user...")

        if not User.query.filter_by(email=flask_conf['DEFAULT_ADMIN_EMAIL']).first():
            hashed_password = bcrypt.generate_password_hash(flask_conf['DEFAULT_ADMIN_PASSWORD']).decode('utf-8')
            admin_user = User(
                username=flask_conf['DEFAULT_ADMIN_USERNAME'],
                email=flask_conf['DEFAULT_ADMIN_EMAIL'],
                password_hash=hashed_password,
                role='Admin'
            )
            db.session.add(admin_user)
            db.session.commit()
            print(f"SHARP: Default admin '{flask_conf['DEFAULT_ADMIN_USERNAME']}' created.")

            with open(setup_flag_path, 'w') as f:
                pass
            print("SHARP: Setup flag created. Default user will not be recreated on subsequent starts.")
        else:
             print("SHARP: Default admin email already exists in the database. Skipping creation.")
    
    log_event("SHARP", "Application started")

    mqtt_setup()
    start_auto_agent()
    liveness_thread.start()

if __name__ == '__main__':
    socketio.run(app, port=5000, host='0.0.0.0', use_reloader=False)