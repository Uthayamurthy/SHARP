from extensions import db
from models import Log
from datetime import datetime

def log_event(entity: str, event: str):
    """
    Adds a log entry to the database.
    """
    try:
        log = Log(timestamp=datetime.utcnow(), entity=entity, event=event)
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        # Using print as a fallback logger for critical logging failures
        print(f"DATABASE LOGGER: Failed to log event. Entity: {entity}, Event: {event}. Error: {e}")
        db.session.rollback()