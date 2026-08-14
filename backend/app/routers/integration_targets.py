from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from ..database import get_db
from ..models import (
    Project,
    Message,
    IntegrationTarget,
    MessageTxTargetItem,
    MessageRxTargetItem,
    User,
)
from ..schemas import IntegrationTargetCreate, IntegrationTargetUpdate, IntegrationTargetRead, MessageIntegrationTargetAssign, MessageRead
from ..auth import get_current_user

router = APIRouter(tags=["integration-targets"])


def get_message_or_404(db: Session, message_id: int) -> Message:
    message = (
        db.query(Message)
        .options(
            joinedload(Message.fields),
            joinedload(Message.enum_values),
            joinedload(Message.labels),
            joinedload(Message.tx_targets),
            joinedload(Message.rx_targets),
        )
        .filter(Message.id == message_id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def ensure_targets_in_project(db: Session, project_id: int, target_ids: list[int]) -> list[IntegrationTarget]:
    ids = list(dict.fromkeys(int(target_id) for target_id in (target_ids or [])))
    if not ids:
        return []
    targets = db.query(IntegrationTarget).filter(IntegrationTarget.project_id == project_id, IntegrationTarget.id.in_(ids)).all()
    if len(targets) != len(ids):
        raise HTTPException(status_code=422, detail="존재하지 않는 노드이 포함되어 있습니다.")
    by_id = {target.id: target for target in targets}
    return [by_id[target_id] for target_id in ids]


@router.get("/projects/{project_id}/integration-targets", response_model=list[IntegrationTargetRead])
def list_integration_targets(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return db.query(IntegrationTarget).filter(IntegrationTarget.project_id == project_id).order_by(IntegrationTarget.name.asc(), IntegrationTarget.id.asc()).all()


@router.post("/projects/{project_id}/integration-targets", response_model=IntegrationTargetRead)
def create_integration_target(project_id: int, payload: IntegrationTargetCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    target = IntegrationTarget(project_id=project_id, name=payload.name.strip(), description=payload.description or "")
    db.add(target)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="이미 같은 이름의 노드이 있습니다.")
    db.refresh(target)
    return target


@router.patch("/integration-targets/{target_id}", response_model=IntegrationTargetRead)
def update_integration_target(target_id: int, payload: IntegrationTargetUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target = db.get(IntegrationTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Integration target not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    for key, value in data.items():
        setattr(target, key, value if value is not None else "")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="이미 같은 이름의 노드이 있습니다.")
    db.refresh(target)
    return target


@router.delete("/integration-targets/{target_id}")
def delete_integration_target(target_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target = db.get(IntegrationTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Integration target not found")
    db.delete(target)
    db.commit()
    return {"ok": True}


@router.post("/messages/{message_id}/integration-targets", response_model=MessageRead)
def set_message_integration_targets(message_id: int, payload: MessageIntegrationTargetAssign, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = db.get(Message, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    tx_targets = ensure_targets_in_project(db, message.project_id, payload.tx_target_ids)
    rx_targets = ensure_targets_in_project(db, message.project_id, payload.rx_target_ids)
    db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id == message_id).delete(synchronize_session=False)
    db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id == message_id).delete(synchronize_session=False)
    for target in tx_targets:
        db.add(MessageTxTargetItem(message_id=message_id, target_id=target.id))
    for target in rx_targets:
        db.add(MessageRxTargetItem(message_id=message_id, target_id=target.id))
    db.commit()
    return get_message_or_404(db, message_id)
