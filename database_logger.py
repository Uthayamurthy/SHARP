from extensions import db
from models import Log
from datetime import datetime

LOG_THRESHOLD = 10000  # Number of logs to trigger pruning
LOG_PRUNE_COUNT = 100  # Number of old logs to delete when threshold is met

def log_event(entity: str, event: str):
    """
    Adds a log entry to the database and prunes old logs if the threshold is exceeded.
    This must be called within a Flask app context.
    """
    try:
        log = Log(timestamp=datetime.utcnow(), entity=entity, event=event)
        db.session.add(log)
        
        last_id = db.session.query(Log.id).order_by(Log.id.desc()).first()
        if last_id and last_id[0] % 100 == 0: # Check every 100 logs
            total_logs = db.session.query(Log.id).count()
            if total_logs > LOG_THRESHOLD:
                logs_to_prune = db.session.query(Log.id).order_by(Log.timestamp.asc()).limit(LOG_PRUNE_COUNT).all()
                ids_to_delete = [log.id for log in logs_to_prune]

                if ids_to_delete:
                    db.session.query(Log).filter(Log.id.in_(ids_to_delete)).delete(synchronize_session=False)
                    print(f"DATABASE LOGGER: Pruned {len(ids_to_delete)} old log entries.")

        db.session.commit()
    except Exception as e:
        print(f"DATABASE LOGGER: Failed to log event. Entity: {entity}, Event: {event}. Error: {e}")
        db.session.rollback()