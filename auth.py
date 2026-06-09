from flask import Blueprint, render_template, url_for, flash, redirect, request
from flask_login import login_user, logout_user, current_user
from sqlalchemy import or_ # Import the 'or_' function
from extensions import db, bcrypt
from models import User
from forms import LoginForm

auth_bp = Blueprint('auth', __name__)

@auth_bp.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter(
            or_(User.username == form.username_or_email.data, User.email == form.username_or_email.data)
        ).first()

        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            flash('Login Successful!', 'success')
            return redirect(next_page) if next_page else redirect(url_for('main.home'))
        else:
            flash('Login Unsuccessful. Please check your credentials.', 'danger')
    return render_template('login.html', title='Login', form=form)


@auth_bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('auth.login'))