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
from routes import main_bp, format_time_12hr, dashless
from extensions import db, bcrypt, login_manager
from models import User
from automation_agent import AUTO_AGENT
import multiprocessing
import json
import signal

print('SHARP: Starting up...')

app = Flask(__name__)

with open('config/flask_app_conf.json', 'r') as f:
    flask_conf = json.load(f)
with open('config/mqtt_conf.json', 'r') as f:
    mqtt_conf = json.load(f)
with open('data/devices_info.json') as f:
    devices_info_data = json.load(f)

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

def mqtt_setup():
    for location, device in devices_info_data.items():
        for device_name, actionable in device.items():
            for actionable_name, info in actionable.items():
                topic = info['ack_topic']
                try:
                    mqtt.subscribe(topic=topic)
                except Exception as e:
                    print(f'SHARP: Failed to subscribe to topic {topic}: {e}')

@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    topic = message.topic
    state = message.payload.decode()
    obj_id = ''
    # This logic needs access to the global `devices_info_data`
    for location, device in devices_info_data.items():
        for device_name, actionable in device.items():
            for actionable_name, info in actionable.items():
                if info['ack_topic'] == topic:
                    obj_id = f'{location}-{device_name}-{actionable_name}'
                    print(f'SHARP: Received message from {obj_id}, New state is "{state}" ')
                    devices_info_data[location][device_name][actionable_name]['state'] = state
                    socketio.emit('update_state', data={'obj_id': obj_id, 'state': state})

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

with app.app_context():
    db.create_all()
    if not User.query.filter_by(email=flask_conf['DEFAULT_ADMIN_EMAIL']).first():
        print("SHARP: Creating default admin user...")
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
    
    mqtt_setup()
    start_auto_agent()

if __name__ == '__main__':
    socketio.run(app, port=5000, host='0.0.0.0', use_reloader=False)
