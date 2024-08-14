from automation_agent import AUTO_AGENT
from flask import Flask, render_template, request, redirect, flash
from flask_mqtt import Mqtt
from flask_socketio import SocketIO
from datetime import datetime
from time import sleep
from __version__ import version
from  logs_loader import load_logs
import multiprocessing 
import json
import signal

print('SHARP: Starting up...')

app = Flask(__name__)

log_items = None

with open('config/flask_app_conf.json', 'r') as f:
    flask_conf = json.load(f)

with open('config/mqtt_conf.json', 'r') as f:
    mqtt_conf = json.load(f)

app.config['MQTT_BROKER_URL'] = mqtt_conf['MQTT_HOST']
app.config['MQTT_BROKER_PORT'] = mqtt_conf['MQTT_PORT']
app.config['MQTT_CLIENT_ID'] = mqtt_conf["MQTT_SHARP_CLIENT_ID"]
app.config['MQTT_CLEAN_SESSION'] = mqtt_conf["MQTT_CLEAN_SESSION"]
app.config['MQTT_USERNAME'] = mqtt_conf["MQTT_USERNAME"]
app.config['MQTT_PASSWORD'] = mqtt_conf["MQTT_PASSWORD"]
app.config['MQTT_KEEPALIVE'] = mqtt_conf['MQTT_KEEP_ALIVE']
app.config['MQTT_TLS_ENABLED'] = mqtt_conf['MQTT_TLS_ENABLED']
app.config['MQTT_LAST_WILL_TOPIC'] = mqtt_conf['MQTT_LAST_WILL_TOPIC']
app.config['MQTT_LAST_WILL_MESSAGE'] = mqtt_conf['MQTT_LAST_WILL_MESSAGE']
app.config['MQTT_LAST_WILL_QOS'] = mqtt_conf['MQTT_LAST_WILL_QOS']

app.config['SECRET_KEY'] = flask_conf['SECRET_KEY']
app.config['TEMPLATES_AUTO_RELOAD'] = flask_conf['TEMPLATES_AUTO_RELOAD']


mqtt = Mqtt(app)
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")
agent_conn = None # The pipe to communicate with auto agent process 
automation_process = None

def format_time_12hr(time_str):
    try:
        # Parse the 24-hour format time string
        dt = datetime.strptime(time_str, '%H:%M')
        # Convert to 12-hour format with AM/PM
        return dt.strftime('%I:%M %p')
    except ValueError:
        return time_str

def dashless(string):
    return string.replace('-', ' ')

app.jinja_env.filters['format_time'] = format_time_12hr
app.jinja_env.filters['dashless'] = dashless

with open('data/devices_info.json') as f:
    devices_info = json.load(f)

def setup():
    for location, device in devices_info.items():
            for device_name, actionable in device.items():
                for actionable_name, info in actionable.items():
                    topic = info['ack_topic']
                    try:
                        b = mqtt.subscribe(topic=topic)
                    except:
                        print(f'SHARP : Failed to subscribe to the topic: {topic}')

def start_auto_agent():
    global agent_conn
    global automation_process
    parent_conn, child_conn = multiprocessing.Pipe()
    agent_conn = parent_conn
    my_agent = AUTO_AGENT(child_conn)
    automation_process = multiprocessing.Process(target=my_agent.start_agent)
    automation_process.daemon = True
    automation_process.start()

@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    global devices_info

    topic = message.topic
    state = message.payload.decode()

    obj_id = ''

    for location, device in devices_info.items():
        for device_name, actionable in device.items():
            for actionable_name, info in actionable.items():
                if info['ack_topic'] == topic:
                    obj_id = f'{location}-{device_name}-{actionable_name}'
                    print(f'SHARP : Received message from {obj_id}, New state is "{state}" ')
                    devices_info[location][device_name][actionable_name]['state'] = state
                    socketio.emit('update_state', data={'obj_id': obj_id, 'state': state})

@socketio.on('connect')
def on_connect ():
    print('SHARP : New Socket client connected.')
    socketio.send('Socket server ready.')
    socketio.emit('devices_info', data=devices_info)

@socketio.on('publish')
def on_publish(data):
    topic = data['topic']
    state = data['state']
    sleep(0.1)
    a = mqtt.publish(topic, state, qos=1)

@app.route('/')
def home():
    return render_template('home.html', devices_info=devices_info)

@app.route('/devices')
def devices():
    return render_template('devices.html', devices_info=devices_info)

@app.route('/automations')
def automations():
    devices_list = []
    actionables_list = {}


    with open('data/automations.json', 'r') as am_file:
        automations = json.load(am_file)
    
    for location, device in devices_info.items():
        for device_name, actionable in device.items():
            formatted_name = f'{location}::{device_name}'
            devices_list.append(formatted_name)
            for actionable_name, info in actionable.items():
                if formatted_name not in actionables_list:
                    actionables_list[formatted_name] = [actionable_name]
                else:
                    actionables_list[formatted_name].append(actionable_name)

    return render_template('automations.html', devices=devices_list, actionables=actionables_list, automations=automations)

@app.route('/new-automation', methods=['POST'])
def new_automation():
    with open('data/automations.json', 'r') as am_file:
        automations = json.load(am_file)

    automation_name = request.form.get('automation_name')
    automation_name = automation_name.strip().replace(' ', '-')
    location, device = request.form.get('device_detail').split('::')
    actionable = request.form.get('actionable')
    auto_type = request.form.get('automation_type')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')

    automations[automation_name] = {
        'enabled': True,
        'location': location,
        'device': device,
        'actionable': actionable,
        'AUTO_TYPE': auto_type,
        'AUTO_PARAMS': {
            'start_time': start_time,
            'end_time': end_time
        }
    }
    print(f'SHARP: Added New Automation "{automation_name}" for {location}::{device}::{actionable}')
    with open('data/automations.json', 'w') as am_file:
        json.dump(automations, am_file, indent=4)

    agent_conn.send('RELOAD')

    flash(f'Automation: {automation_name} added successfully !', 'success')
    return redirect('/automations')

@app.route('/delete-automation', methods=['POST'])
def delete_automation():
    with open('data/automations.json', 'r') as am_file:
        automations = json.load(am_file)

    automation_name = request.form.get('delete_am_name')

    del automations[automation_name]

    with open('data/automations.json', 'w') as am_file:
        json.dump(automations, am_file, indent=4)

    agent_conn.send('RELOAD')

    print(f'SHARP: Deleted Automation "{automation_name}" ')

    flash(f'Automation: {automation_name} deleted !', 'danger')
    return redirect('/automations')

@app.route('/toggle-automation', methods=['POST'])
def toggle_automation():
    with open('data/automations.json', 'r') as am_file:
        automations = json.load(am_file)

    automation_name, state = request.form.get('toggle_am_name').split('--')

    if state == 'pause':
        automations[automation_name]['enabled'] = False
        print(f'SHARP: Paused Automation "{automation_name}" ')
        flash(f'Automation: {automation_name} paused !', 'primary')
    else:
        automations[automation_name]['enabled'] = True
        print(f'SHARP: Resumed Automation "{automation_name}" ')
        flash(f'Automation: {automation_name} resumed !', 'primary')

    with open('data/automations.json', 'w') as am_file:
        json.dump(automations, am_file, indent=4)

    agent_conn.send('RELOAD')

    
    return redirect('/automations')

@app.route('/about')
def about():
    return render_template('about.html', version=version)

@app.route('/logs')
def logs():
    global log_items

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    if page == 1:
        log_items = load_logs()

    if log_items == None:
        return "Failed to get the logs, looks like SHARP Service is not enabled ..."
    
    total_items = len(log_items)
    total_pages = (total_items + per_page - 1) // per_page
    
    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = log_items[start:end]
    
    return render_template('logs.html', items=paginated_items, page=page, per_page=per_page, total_pages=total_pages)

@app.route('/refresh-logs')
def refresh_logs():
    global log_items
    log_items = load_logs()
    return redirect('/logs')

with app.app_context():
        setup()
        start_auto_agent()
        
def handle_sigterm(*args):
    print("SHARP: SIGTERM received, attempting to shut down gracefully...")
    mqtt.client.loop_stop()
    mqtt.client.disconnect()
    agent_conn.send('STOP')
    socketio.stop()
    print("SHARP: Exiting ...")
    exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

if __name__ == '__main__':
    # run app in debug mode on port 5000

    socketio.run(app, port=5000, host='0.0.0.0', use_reloader=False)
