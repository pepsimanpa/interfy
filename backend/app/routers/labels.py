from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from ..database import get_db
from ..models import Project, Message, MessageLabel, MessageLabelItem, MessageTxLabelItem, MessageRxLabelItem, User
from ..schemas import LabelCreate, LabelUpdate, LabelRead, MessageLabelAssign, MessageRead
from ..auth import get_current_user

router = APIRouter(tags=["labels"])


def get_message_or_404(db: Session, message_id: int) -> Message:
    message = (
        db.query(Message)
        .options(joinedload(Message.fields), joinedload(Message.enum_values), joinedload(Message.labels), joinedload(Message.tx_targets), joinedload(Message.rx_targets))
        .filter(Message.id == message_id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def ensure_labels_in_project(db: Session, project_id: int, label_ids: list[int]) -> list[MessageLabel]:
    ids = list(dict.fromkeys(int(label_id) for label_id in (label_ids or [])))
    if not ids:
        return []
    labels = db.query(MessageLabel).filter(MessageLabel.project_id == project_id, MessageLabel.id.in_(ids)).all()
    if len(labels) != len(ids):
        raise HTTPException(status_code=422, detail="존재하지 않는 라벨이 포함되어 있습니다.")
    by_id = {label.id: label for label in labels}
    return [by_id[label_id] for label_id in ids]


@router.get("/projects/{project_id}/labels", response_model=list[LabelRead])
def list_labels(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return db.query(MessageLabel).filter(MessageLabel.project_id == project_id).order_by(MessageLabel.name.asc(), MessageLabel.id.asc()).all()


@router.post("/projects/{project_id}/labels", response_model=LabelRead)
def create_label(project_id: int, payload: LabelCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    label = MessageLabel(project_id=project_id, name=payload.name.strip(), description=payload.description or "")
    db.add(label)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="이미 같은 이름의 라벨이 있습니다.")
    db.refresh(label)
    return label


@router.patch("/labels/{label_id}", response_model=LabelRead)
def update_label(label_id: int, payload: LabelUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    label = db.get(MessageLabel, label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    for key, value in data.items():
        setattr(label, key, value if value is not None else "")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="이미 같은 이름의 라벨이 있습니다.")
    db.refresh(label)
    return label


@router.delete("/labels/{label_id}")
def delete_label(label_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    label = db.get(MessageLabel, label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    db.delete(label)
    db.commit()
    return {"ok": True}


@router.post("/messages/{message_id}/labels", response_model=MessageRead)
def set_message_labels(message_id: int, payload: MessageLabelAssign, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = db.get(Message, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    labels = ensure_labels_in_project(db, message.project_id, payload.label_ids)
    db.query(MessageLabelItem).filter(MessageLabelItem.message_id == message_id).delete(synchronize_session=False)
    db.flush()
    for label in labels:
        db.add(MessageLabelItem(message_id=message_id, label_id=label.id))
    if payload.tx_label_ids is not None:
        tx_labels = ensure_labels_in_project(db, message.project_id, payload.tx_label_ids)
        db.query(MessageTxLabelItem).filter(MessageTxLabelItem.message_id == message_id).delete(synchronize_session=False)
        for label in tx_labels:
            db.add(MessageTxLabelItem(message_id=message_id, label_id=label.id))
    if payload.rx_label_ids is not None:
        rx_labels = ensure_labels_in_project(db, message.project_id, payload.rx_label_ids)
        db.query(MessageRxLabelItem).filter(MessageRxLabelItem.message_id == message_id).delete(synchronize_session=False)
        for label in rx_labels:
            db.add(MessageRxLabelItem(message_id=message_id, label_id=label.id))
    db.commit()
    return get_message_or_404(db, message_id)
