from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import MessageChangeHistory, User
from ..schemas import HistoryRead
from ..auth import get_current_user

router = APIRouter(prefix="/history", tags=["history"])

def _name_from_snapshot(value):
    if isinstance(value, dict):
        if isinstance(value.get("name"), str):
            return value.get("name")
        # Reorder histories are stored as {"reordered_messages": [{"name": ...}]}
        partial = value.get("partial_update")
        if isinstance(partial, dict):
            count = int(partial.get("message_count") or 0)
            return f"부분 업데이트 ({count}건)" if count else "부분 업데이트"
        for key in ("reordered_messages", "reordered_fields"):
            items = value.get(key)
            if isinstance(items, list) and items:
                names = [str(item.get("name")) for item in items if isinstance(item, dict) and item.get("name")]
                if names:
                    return ", ".join(names[:3]) + (" 외" if len(names) > 3 else "")
    return None


@router.get("", response_model=list[HistoryRead])
def list_history(project_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(MessageChangeHistory)
    if project_id is not None:
        query = query.filter(MessageChangeHistory.project_id == project_id)
    rows = query.order_by(MessageChangeHistory.created_at.desc()).limit(500).all()
    result = []
    for h in rows:
        message_name = None
        if h.message is not None:
            message_name = h.message.name
        if not message_name:
            message_name = _name_from_snapshot(h.after_json) or _name_from_snapshot(h.before_json)
        result.append({
            "id": h.id,
            "message_id": h.message_id,
            "message_name": message_name,
            "project_id": h.project_id,
            "changed_by": h.changed_by,
            "changed_by_name": (h.user.display_name or h.user.email) if h.user is not None else f"사용자 #{h.changed_by}",
            "change_type": h.change_type,
            "before_json": h.before_json,
            "after_json": h.after_json,
            "created_at": h.created_at,
        })
    return result
