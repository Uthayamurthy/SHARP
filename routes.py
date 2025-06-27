from flask import Blueprint, render_template, request, redirect, flash, url_for, current_app, jsonify
from flask_login import login_required, current_user
from extensions import db, bcrypt
from models import User, Log
from forms import (UpdateProfileForm, ChangePasswordForm, CreateUserForm, 
                   AdminUpdateUserForm, AdminChangePasswordForm, AdminUpdateRoleForm, AdminDeleteUserForm)
from decorators import admin_required
import json
import secrets
import os
from PIL import Image
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from markupsafe import Markup

main_bp = Blueprint('main', __name__)

# --- Timezone & Helper Functions ---
IST = ZoneInfo("Asia/Kolkata")

def to_ist(utc_dt):
    """Converts a UTC datetime object to IST."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=ZoneInfo("UTC"))
    return utc_dt.astimezone(IST)

def colorize_log(event_text):
    """A Jinja filter to colorize keywords in a log event string."""
    
    # Color the actionable name first if it exists
    if "state changed to" in event_text:
        match = re.match(r"('[\w\s-]+')", event_text)
        if match:
            actionable_part = match.group(1)
            colored_actionable = f'<span class="text-primary fw-bold">{actionable_part}</span>'
            event_text = event_text.replace(actionable_part, colored_actionable, 1)

    # Color general keywords
    replacements = {
        'on': '<span class="text-success fw-bold">on</span>',
        'off': '<span class="text-danger fw-bold">off</span>',
        'online': '<span class="text-success fw-bold">online</span>',
        'offline': '<span class="text-danger fw-bold">offline</span>',
        'started': '<span class="text-success fw-bold">started</span>',
        'ON': '<span class="text-success fw-bold">ON</span>',
        'OFF': '<span class="text-danger fw-bold">OFF</span>',
    }
    # Use word boundaries to avoid replacing parts of words
    for word, replacement in replacements.items():
        event_text = re.sub(r'\b' + re.escape(word) + r'\b', replacement, event_text)

    return Markup(event_text)

def format_time_12hr(time_str):
    try:
        if isinstance(time_str, datetime):
             return time_str.strftime('%I:%M %p')
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

def check_password_strength(password):
    """Returns a strength score (0-4) and a message."""
    score = 0
    feedback = []

    if len(password) >= 8:
        score += 1
    else:
        feedback.append("at least 8 characters")
    
    if re.search(r"[a-z]", password):
        score += 1
    else:
        feedback.append("a lowercase letter")

    if re.search(r"[A-Z]", password):
        score += 1
    else:
        feedback.append("an uppercase letter")

    if re.search(r"[0-9]", password):
        score += 1
    else:
        feedback.append("a number")
    
    if re.search(r"[\W_]", password): # Non-alphanumeric characters
        score += 1
    else:
        feedback.append("a symbol")

    # Determine message based on score
    if score <= 2:
        strength = "Weak"
        message = "Requires " + ", ".join(feedback) + "." if feedback else ""
    elif score == 3:
        strength = "Medium"
        message = "Good, but could be stronger."
    elif score == 4:
        strength = "Strong"
        message = "Strong password."
    else: # score == 5
        strength = "Very Strong"
        message = "Excellent password!"

    return {'score': score, 'strength': strength, 'message': message}

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
    
    for location, devices in devices_info.items():
        for device_name, device_info in devices.items():
            formatted_name = f'{location}::{device_name}'
            devices_list.append(formatted_name)
            
            actionables_for_device = []
            for actionable_name, info in device_info.items():
                if isinstance(info, dict) and 'action_topic' in info:
                    actionables_for_device.append(actionable_name)
            
            if actionables_for_device:
                actionables_list[formatted_name] = actionables_for_device

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

    auto_params = {}
    if auto_type == 'TIME-SCHEDULED':
        auto_params = {
            'start_time': request.form.get('start_time'),
            'end_time': request.form.get('end_time')
        }
    elif auto_type == 'SUNLIGHT-TRIGGERED':
        auto_params = {
            'start': {
                'type': request.form.get('start_trigger_type'),
                'value': request.form.get('start_trigger_value') or None
            },
            'end': {
                'type': request.form.get('end_trigger_type'),
                'value': request.form.get('end_trigger_value') or None
            }
        }

    if not auto_params:
        flash('Invalid automation type submitted.', 'danger')
        return redirect(url_for('main.automations'))

    automations_data[automation_name] = {
        'enabled': True, 'location': location, 'device': device, 'actionable': actionable,
        'AUTO_TYPE': auto_type, 'AUTO_PARAMS': auto_params
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
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    filter_date_str = request.args.get('filter_date', '')
    filter_entity = request.args.get('filter_entity', '').strip()

    query = Log.query
    
    distinct_entities = [item[0] for item in db.session.query(Log.entity).distinct().order_by(Log.entity).all()]

    if filter_date_str:
        try:
            filter_date_obj = datetime.strptime(filter_date_str, '%d-%m-%Y').date()
            start_dt_local = datetime.combine(filter_date_obj, datetime.min.time()).replace(tzinfo=IST)
            end_dt_local = datetime.combine(filter_date_obj, datetime.max.time()).replace(tzinfo=IST)
            start_dt_utc = start_dt_local.astimezone(ZoneInfo("UTC"))
            end_dt_utc = end_dt_local.astimezone(ZoneInfo("UTC"))
            query = query.filter(Log.timestamp.between(start_dt_utc, end_dt_utc))
        except ValueError:
            flash('Invalid date format for filter. Please use DD-MM-YYYY.', 'warning')
            filter_date_str = ''

    if filter_entity:
        query = query.filter(Log.entity == filter_entity)

    pagination = query.order_by(Log.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('logs.html', pagination=pagination, per_page=per_page,
                           filter_date=filter_date_str, filter_entity=filter_entity,
                           distinct_entities=distinct_entities)


@main_bp.route("/logs/clear", methods=['POST'])
@login_required
@admin_required
def clear_logs():
    clear_date_str = request.form.get('clear_date')
    clear_time_str = request.form.get('clear_time')

    if not clear_date_str or not clear_time_str:
        flash('Both date and time are required to clear logs.', 'warning')
        return redirect(url_for('main.logs'))

    try:
        local_dt_naive = datetime.strptime(f"{clear_date_str} {clear_time_str}", '%d-%m-%Y %H:%M')
        local_dt_aware = local_dt_naive.replace(tzinfo=IST)
        
        utc_dt_aware = local_dt_aware.astimezone(ZoneInfo("UTC"))
        
        num_deleted = db.session.query(Log).filter(Log.timestamp <= utc_dt_aware).delete()
        db.session.commit()
        
        if num_deleted > 0:
            flash(f'Successfully cleared {num_deleted} log entries.', 'success')
        else:
            flash('No log entries found on or before the specified date and time.', 'info')

    except ValueError:
        flash('Invalid date or time format. Please use DD-MM-YYYY.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred while clearing logs: {e}', 'danger')

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
        strength = check_password_strength(form.password.data)
        if strength['score'] < 3:
            flash(f"Password is too weak. Please choose a stronger one.", 'danger')
            return redirect(url_for('main.profile'))

        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        current_user.password_hash = hashed_password
        db.session.commit()
        flash('Your password has been changed successfully!', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                label = getattr(form, field).label.text
                flash(f"Error in {label}: {error}", 'danger')

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

@main_bp.route("/admin/edit_user/<int:user_id>", methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if user == current_user:
        flash("You cannot edit your own account from the admin panel. Please use the profile page.", 'warning')
        return redirect(url_for('main.admin_dashboard'))

    details_form = AdminUpdateUserForm(user)
    password_form = AdminChangePasswordForm()
    role_form = AdminUpdateRoleForm()
    delete_form = AdminDeleteUserForm()

    if 'submit_details' in request.form and details_form.validate_on_submit():
        user.username = details_form.username.data
        user.email = details_form.email.data
        db.session.commit()
        flash(f"User '{user.username}' details have been updated.", 'success')
        return redirect(url_for('main.edit_user', user_id=user.id))

    if 'submit_password' in request.form and password_form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(password_form.password.data).decode('utf-8')
        user.password_hash = hashed_password
        db.session.commit()
        flash(f"Password for user '{user.username}' has been changed.", 'success')
        return redirect(url_for('main.edit_user', user_id=user.id))

    if 'submit_role' in request.form and role_form.validate_on_submit():
        if user.role == 'Admin' and User.query.filter_by(role='Admin').count() == 1:
             flash("Cannot change the role of the last admin.", 'danger')
        else:
            user.role = role_form.role.data
            db.session.commit()
            flash(f"User '{user.username}' role has been updated to '{user.role}'.", 'success')
        return redirect(url_for('main.edit_user', user_id=user.id))

    if 'submit_delete' in request.form and delete_form.validate_on_submit():
        if user.role == 'Admin' and User.query.filter_by(role='Admin').count() == 1:
            flash("Cannot delete the last admin account.", 'danger')
            return redirect(url_for('main.edit_user', user_id=user.id))
        else:
            username_deleted = user.username
            db.session.delete(user)
            db.session.commit()
            flash(f"User '{username_deleted}' has been permanently deleted.", 'danger')
            return redirect(url_for('main.admin_dashboard'))

    details_form.username.data = user.username
    details_form.email.data = user.email
    role_form.role.data = user.role
    
    return render_template('edit_user.html', title='Edit User', user=user,
                           details_form=details_form, password_form=password_form,
                           role_form=role_form, delete_form=delete_form)

@main_bp.route('/check-password-strength', methods=['POST'])
@login_required
def password_strength():
    password = request.json.get('password')
    if not password:
        return jsonify({'score': 0, 'strength': 'Very Weak', 'message': 'Password cannot be empty.'})
    
    strength_data = check_password_strength(password)
    return jsonify(strength_data)