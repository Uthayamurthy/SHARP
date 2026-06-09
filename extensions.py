from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt

db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()

# Configure login manager
login_manager.login_view = 'auth.login'  # The route to redirect to for login
login_manager.login_message_category = 'info' # Bootstrap class for flash message
login_manager.login_message = 'Please log in to access this page.'