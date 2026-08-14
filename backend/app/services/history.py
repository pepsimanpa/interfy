from sqlalchemy.orm import Session
from ..models import MessageChangeHistory, ChangeType, User

def snapshot(obj, fields: list[str]) -> dict:
    return {field: getattr(obj, field) for field in fields}

def add_history(db: Session, *, project_id: int, user: User, change_type: ChangeType, message_id: int | None = None, before=None, after=None):
    history = MessageChangeHistory(
        project_id=project_id,
        message_id=message_id,
        changed_by=user.id,
        change_type=change_type,
        before_json=before,
        after_json=after,
    )
    db.add(history)
    return history
