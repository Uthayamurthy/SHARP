from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, BooleanField, SelectField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from models import User
from flask_login import current_user
from extensions import bcrypt
class LoginForm(FlaskForm):
    username_or_email = StringField('Email or Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')

class UpdateProfileForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    picture = FileField('Update Profile Picture', validators=[FileAllowed(['jpg', 'png'])])
    submit = SubmitField('Update')

    def validate_username(self, username):
        if username.data != current_user.username:
            user = User.query.filter_by(username=username.data).first()
            if user:
                raise ValidationError('That username is taken. Please choose a different one.')

    def validate_email(self, email):
        if email.data != current_user.email:
            user = User.query.filter_by(email=email.data).first()
            if user:
                raise ValidationError('That email is taken. Please choose a different one.')

class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=8, message="Password must be at least 8 characters long.")])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Change Password')

    def validate_current_password(self, current_password):
        if not bcrypt.check_password_hash(current_user.password_hash, current_password.data):
            raise ValidationError('Incorrect current password.')
    
    def validate_password(self, password):
        if bcrypt.check_password_hash(current_user.password_hash, password.data):
            raise ValidationError('New password cannot be the same as the current password.')

class CreateUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    role = SelectField('Role', choices=[('Regular', 'Regular'), ('Admin', 'Admin')], validators=[DataRequired()])
    submit = SubmitField('Create User')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is already in use.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already in use.')

class AdminConfirmPasswordForm(FlaskForm):
    admin_password = PasswordField(
        'Your Admin Password',
        validators=[DataRequired(message="Your password is required for this action.")]
    )

    def validate_admin_password(self, admin_password):
        if not bcrypt.check_password_hash(current_user.password_hash, admin_password.data):
            raise ValidationError('Incorrect password. This action was not authorized.')

class AdminUpdateUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Update Details')

    def __init__(self, user_to_edit, *args, **kwargs):
        super(AdminUpdateUserForm, self).__init__(*args, **kwargs)
        self.user_to_edit = user_to_edit

    def validate_username(self, username):
        if username.data != self.user_to_edit.username:
            user = User.query.filter_by(username=username.data).first()
            if user:
                raise ValidationError('That username is already in use.')

    def validate_email(self, email):
        if email.data != self.user_to_edit.email:
            user = User.query.filter_by(email=email.data).first()
            if user:
                raise ValidationError('That email is already in use.')

class AdminChangePasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Change Password')

class AdminUpdateRoleForm(AdminConfirmPasswordForm):
    role = SelectField('Role', choices=[('Regular', 'Regular'), ('Admin', 'Admin')], validators=[DataRequired()])
    submit = SubmitField('Update Role')

class AdminDeleteUserForm(AdminConfirmPasswordForm):
    submit = SubmitField('Yes, Delete This User')