from flask import Blueprint, render_template, request, redirect, flash, url_for, current_app
from flask_login import login_required, current_user
from extensions import db, bcrypt
from models import User
from forms import UpdateProfileForm, ChangePasswordForm, CreateUserForm
from decorators import admin_required
import json
import secrets
import os
from PIL import Image

main_bp = Blueprint('main', __name__)

# --- Helper Functions ---
def format_time_12hr(time_str):
    from datetime import datetime
    try:
        dt = datetime.strptime(time_str, '%H:%M')
        return dt.strftime('%I:%M %p')
    except (ValueError, TypeError):
        return time_str

def dashless(string):
    return string.replace('-', ' ')

def save_picture(form_picture):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(current_app.root_path, 'static/profile_pics', picture_fn)

    output_size = (125, 125)
    i = Image.open(form_picture)
    i.thumbnail(output_size)
    i.save(picture_path)
    return picture_fn


# --- Main Application Routes ---
@main_bp.route('/')
@login_required
def home():
    devices_info = current_app.config['DEVICES_INFO']
    return render_template('home.html', devices_info=devices_info)

@main_bp.route('/devices')
@login_required
def devices():
    devices_info = current_app.config['DEVICES_INFO']
    return render_template('devices.html', devices_info=devices_info)

@main_bp.route('/automations')
@login_required
def automations():
    devices_info = current_app.config['DEVICES_INFO']
    devices_list = []
    actionables_list = {}

    with open('data/automations.json', 'r') as am_file:
        automations_data = json.load(am_file)
    
    for location, device in devices_info.items():
        for device_name, actionable in device.items():
            formatted_name = f'{location}::{device_name}'
            devices_list.append(formatted_name)
            for actionable_name, info in actionable.items():
                if formatted_name not in actionables_list:
                    actionables_list[formatted_name] = [actionable_name]
                else:
                    actionables_list[formatted_name].append(actionable_name)

    return render_template('automations.html', devices=devices_list, actionables=actionables_list, automations=automations_data)

@main_bp.route('/new-automation', methods=['POST'])
@login_required
def new_automation():
    with open('data/automations.json', 'r') as am_file:
        automations_data = json.load(am_file)

    automation_name = request.form.get('automation_name').strip().replace(' ', '-')
    location, device = request.form.get('device_detail').split('::')
    actionable = request.form.get('actionable')
    auto_type = request.form.get('automation_type')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')

    automations_data[automation_name] = {
        'enabled': True, 'location': location, 'device': device, 'actionable': actionable,
        'AUTO_TYPE': auto_type, 'AUTO_PARAMS': {'start_time': start_time, 'end_time': end_time}
    }
    with open('data/automations.json', 'w') as am_file:
        json.dump(automations_data, am_file, indent=4)
    
    current_app.config['AGENT_CONN'].send('RELOAD')
    flash(f'Automation: {automation_name} added successfully!', 'success')
    return redirect(url_for('main.automations'))


@main_bp.route('/delete-automation', methods=['POST'])
@login_required
def delete_automation():
    with open('data/automations.json', 'r') as am_file:
        automations_data = json.load(am_file)
    automation_name = request.form.get('delete_am_name')
    del automations_data[automation_name]
    with open('data/automations.json', 'w') as am_file:
        json.dump(automations_data, am_file, indent=4)
    
    current_app.config['AGENT_CONN'].send('RELOAD')
    flash(f'Automation: {automation_name} deleted!', 'danger')
    return redirect(url_for('main.automations'))

@main_bp.route('/toggle-automation', methods=['POST'])
@login_required
def toggle_automation():
    with open('data/automations.json', 'r') as am_file:
        automations_data = json.load(am_file)
    automation_name, state = request.form.get('toggle_am_name').split('--')
    if state == 'pause':
        automations_data[automation_name]['enabled'] = False
        flash(f'Automation: {automation_name} paused!', 'primary')
    else:
        automations_data[automation_name]['enabled'] = True
        flash(f'Automation: {automation_name} resumed!', 'primary')
    
    with open('data/automations.json', 'w') as am_file:
        json.dump(automations_data, am_file, indent=4)

    current_app.config['AGENT_CONN'].send('RELOAD')
    return redirect(url_for('main.automations'))

@main_bp.route('/about')
@login_required
def about():
    from __version__ import version
    return render_template('about.html', version=version)

@main_bp.route('/logs')
@login_required
def logs():
    from logs_loader import load_logs
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    log_items = current_app.config.get('LOG_ITEMS')
    if page == 1 or not log_items:
        log_items = load_logs()
        current_app.config['LOG_ITEMS'] = log_items

    if log_items is None:
        return "Failed to get the logs, looks like SHARP Service is not enabled..."
    
    total_items = len(log_items)
    total_pages = (total_items + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = log_items[start:end]
    
    return render_template('logs.html', items=paginated_items, page=page, per_page=per_page, total_pages=total_pages)

@main_bp.route('/refresh-logs')
@login_required
def refresh_logs():
    from logs_loader import load_logs
    current_app.config['LOG_ITEMS'] = load_logs()
    return redirect(url_for('main.logs'))


# --- User Profile and Admin Routes ---
@main_bp.route("/profile", methods=['GET', 'POST'])
@login_required
def profile():
    update_form = UpdateProfileForm()
    if update_form.validate_on_submit():
        if update_form.picture.data:
            picture_file = save_picture(update_form.picture.data)
            current_user.profile_image = picture_file
        current_user.username = update_form.username.data
        current_user.email = update_form.email.data
        db.session.commit()
        flash('Your account has been updated!', 'success')
        return redirect(url_for('main.profile'))
    
    update_form.username.data = current_user.username
    update_form.email.data = current_user.email
    image_file = url_for('static', filename='profile_pics/' + current_user.profile_image)
    
    password_form = ChangePasswordForm()
    return render_template('profile.html', title='Profile', image_file=image_file, update_form=update_form, password_form=password_form)

@main_bp.route("/profile/change_password", methods=['POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        current_user.password_hash = hashed_password
        db.session.commit()
        flash('Your password has been changed!', 'success')
    else:
        # This part handles validation errors
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", 'danger')

    return redirect(url_for('main.profile'))

@main_bp.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    users = User.query.all()
    return render_template('admin.html', users=users)

@main_bp.route("/admin/create_user", methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    form = CreateUserForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(
            username=form.username.data, 
            email=form.email.data, 
            password_hash=hashed_password, 
            role=form.role.data)
        db.session.add(user)
        db.session.commit()
        flash(f'Account created for {form.username.data}!', 'success')
        return redirect(url_for('main.admin_dashboard'))
    return render_template('create_user.html', title='Create User', form=form)