from extensions import db
from flask_login import UserMixin
from datetime import datetime

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    profile_image = db.Column(db.String(20), nullable=False, default='default.jpg')
    password_hash = db.Column(db.String(60), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='Regular')

    def __repr__(self):
        return f"User('{self.username}', '{self.email}', '{self.role}')"
class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    entity = db.Column(db.String(100), nullable=False)
    event = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f"Log('{self.timestamp}', '{self.entity}', '{self.event}')"
class SmartRepetitionState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    automation_name = db.Column(db.String(100), nullable=False)
    run_date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    successful_runs = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='RUNNING') # RUNNING, COMPLETE
    
    tasks = db.relationship('SmartRepetitionTask', backref='state', lazy=True, cascade="all, delete-orphan")
    
    __table_args__ = (db.UniqueConstraint('automation_name', 'run_date', name='_automation_date_uc'),)

    def __repr__(self):
        return f"<SmartRepetitionState {self.automation_name} on {self.run_date}>"

class SmartRepetitionTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    state_id = db.Column(db.Integer, db.ForeignKey('smart_repetition_state.id'), nullable=False)
    
    task_index = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='PENDING') # PENDING, ACTIVE, SUCCESS, FAILED
    attempts = db.Column(db.Integer, default=0)
    last_attempt_time = db.Column(db.DateTime, nullable=True)
    completion_time = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<SmartRepetitionTask {self.id} - Status: {self.status}>"