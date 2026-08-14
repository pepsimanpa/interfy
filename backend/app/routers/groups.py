from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from ..database import get_db
from ..models import Project, Message, MessageGroup, MessageGroupItem, ChangeType, User
from ..schemas import GroupCreate, GroupRead, GroupUpdate, GroupMessageReorder
from ..auth import get_current_user
from ..services.history import add_history

router = APIRouter(tags=["groups"])

def as_group_read(group: MessageGroup) -> GroupRead:
    return GroupRead(
        id=group.id,
        project_id=group.project_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        updated_at=group.updated_at,
        message_ids=[item.message_id for item in sorted(group.items or [], key=lambda item: ((item.order_index or 0), item.id or 0))],
    )

@router.get("/projects/{project_id}/groups", response_model=list[GroupRead])
def list_groups(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [as_group_read(g) for g in db.query(MessageGroup).filter(MessageGroup.project_id == project_id).order_by(MessageGroup.name.asc()).all()]

@router.post("/projects/{project_id}/groups", response_model=GroupRead)
def create_group(project_id: int, payload: GroupCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    group = MessageGroup(project_id=project_id, name=payload.name, description=payload.description)
    db.add(group)
    db.flush()
    add_history(db, project_id=project_id, user=current_user, change_type=ChangeType.GROUP_CREATE, after={"name": group.name, "description": group.description})
    db.commit()
    db.refresh(group)
    return as_group_read(group)

@router.patch("/groups/{group_id}", response_model=GroupRead)
def update_group(group_id: int, payload: GroupUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    group = db.get(MessageGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    before = {"name": group.name, "description": group.description}
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, key, value)
    db.flush()
    add_history(db, project_id=group.project_id, user=current_user, change_type=ChangeType.GROUP_UPDATE, before=before, after={"name": group.name, "description": group.description})
    db.commit()
    db.refresh(group)
    return as_group_read(group)

@router.delete("/groups/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    group = db.get(MessageGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    before = {"name": group.name, "description": group.description}
    project_id = group.project_id
    db.delete(group)
    add_history(db, project_id=project_id, user=current_user, change_type=ChangeType.GROUP_DELETE, before=before)
    db.commit()
    return {"ok": True}

@router.post("/groups/{group_id}/messages/reorder", response_model=GroupRead)
def reorder_group_messages(group_id: int, payload: GroupMessageReorder, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    group = db.get(MessageGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    items = db.query(MessageGroupItem).filter(MessageGroupItem.group_id == group_id).all()
    item_by_message_id = {item.message_id: item for item in items}
    current_ids = set(item_by_message_id.keys())
    requested_ids = list(payload.message_ids or [])

    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(status_code=422, detail="중복된 메시지 ID가 포함되어 있습니다.")
    if set(requested_ids) != current_ids:
        raise HTTPException(status_code=422, detail="그룹에 포함된 메시지 목록과 순서 변경 요청이 일치하지 않습니다.")

    for order_index, message_id in enumerate(requested_ids, start=1):
        item_by_message_id[message_id].order_index = order_index

    db.commit()
    db.refresh(group)
    return as_group_read(group)

@router.post("/groups/{group_id}/messages/{message_id}", response_model=GroupRead)
def add_message_to_group(group_id: int, message_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    group = db.get(MessageGroup, group_id)
    message = db.get(Message, message_id)
    if not group or not message:
        raise HTTPException(status_code=404, detail="Group or message not found")
    if group.project_id != message.project_id:
        raise HTTPException(status_code=400, detail="Message must belong to the same project")
    max_order = db.query(func.max(MessageGroupItem.order_index)).filter(MessageGroupItem.group_id == group_id).scalar() or 0
    db.add(MessageGroupItem(group_id=group_id, message_id=message_id, order_index=max_order + 1))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    db.refresh(group)
    return as_group_read(group)

@router.delete("/groups/{group_id}/messages/{message_id}", response_model=GroupRead)
def remove_message_from_group(group_id: int, message_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(MessageGroupItem).filter(MessageGroupItem.group_id == group_id, MessageGroupItem.message_id == message_id).first()
    if item:
        db.delete(item)
        db.commit()
    group = db.get(MessageGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return as_group_read(group)
