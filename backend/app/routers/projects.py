from fastapi import APIRouter, Depends, HTTPException
import re
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from ..database import get_db
from ..models import Project, User, Message, MessageField, MessageEnumValue, MessageGroup, MessageGroupItem, MessageLabel, MessageLabelItem, MessageTxLabelItem, MessageRxLabelItem, IntegrationTarget, MessageTxTargetItem, MessageRxTargetItem, MessageChangeHistory, ProjectBackup, ProjectBackupEvent
from ..schemas import ProjectCreate, ProjectRead, ProjectUpdate
from ..auth import get_current_user, require_admin
from .project_json import export_project_json as export_project_json_impl

router = APIRouter(prefix="/projects", tags=["projects"])

def normalize_acronym(value: str) -> str:
    value = (value or "").strip()
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", value):
        raise HTTPException(status_code=422, detail="프로젝트 영문약어는 영문자로 시작하고 영문/숫자/_ 만 사용할 수 있습니다.")
    return value

@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Project).order_by(Project.updated_at.desc()).all()

@router.post("", response_model=ProjectRead)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    project = Project(name=payload.name, acronym=normalize_acronym(payload.acronym), description=payload.description, owner_id=current_user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}/export/json")
def export_project_json_compat(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return export_project_json_impl(project_id, db, current_user)

@router.get("/{project_id}/project-json")
def export_project_json_simple(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return export_project_json_impl(project_id, db, current_user)

@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "acronym" and value is not None:
            value = normalize_acronym(value)
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project

@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    message_ids = [row[0] for row in db.query(Message.id).filter(Message.project_id == project_id).all()]
    group_ids = [row[0] for row in db.query(MessageGroup.id).filter(MessageGroup.project_id == project_id).all()]
    backup_ids = [row[0] for row in db.query(ProjectBackup.id).filter(ProjectBackup.project_id == project_id).all()]
    label_ids = [row[0] for row in db.query(MessageLabel.id).filter(MessageLabel.project_id == project_id).all()]
    target_ids = [row[0] for row in db.query(IntegrationTarget.id).filter(IntegrationTarget.project_id == project_id).all()]

    try:
        # Guard against invalid legacy/cross-project references. Normal Interfy data
        # only allows references within the same project, but old/manual DB edits can leave
        # another project pointing to a message that is about to be deleted. In that case,
        # deleting the project would violate the message_fields.ref_message_id FK, so show
        # a clear reason instead of failing with a generic 500 error.
        if message_ids:
            external_refs = (
                db.query(MessageField)
                .filter(
                    MessageField.ref_message_id.in_(message_ids),
                    ~MessageField.message_id.in_(message_ids),
                )
                .limit(10)
                .all()
            )
            if external_refs:
                labels = []
                for field in external_refs:
                    owner = db.get(Message, field.message_id)
                    labels.append(f"{owner.name if owner else '메시지 #' + str(field.message_id)}.{field.name}")
                raise HTTPException(
                    status_code=409,
                    detail="다른 프로젝트의 필드에서 참조 중인 메시지가 있어 프로젝트를 삭제할 수 없습니다. 참조 위치: " + ", ".join(labels),
                )

        # Delete dependent rows in FK-safe order. Conditions include both project_id and
        # direct FK ids so deletion also works with older records whose project_id/FK rows
        # became inconsistent during earlier backup/restore iterations.
        if group_ids or message_ids:
            filters = []
            if group_ids:
                filters.append(MessageGroupItem.group_id.in_(group_ids))
            if message_ids:
                filters.append(MessageGroupItem.message_id.in_(message_ids))
            db.query(MessageGroupItem).filter(or_(*filters)).delete(synchronize_session=False)

        if label_ids or message_ids:
            label_filters = []
            if label_ids:
                label_filters.append(MessageLabelItem.label_id.in_(label_ids))
            if message_ids:
                label_filters.append(MessageLabelItem.message_id.in_(message_ids))
            db.query(MessageLabelItem).filter(or_(*label_filters)).delete(synchronize_session=False)
            db.query(MessageTxLabelItem).filter(or_(*label_filters)).delete(synchronize_session=False)
            db.query(MessageRxLabelItem).filter(or_(*label_filters)).delete(synchronize_session=False)

        if target_ids or message_ids:
            tx_target_filters = []
            rx_target_filters = []
            if target_ids:
                tx_target_filters.append(MessageTxTargetItem.target_id.in_(target_ids))
                rx_target_filters.append(MessageRxTargetItem.target_id.in_(target_ids))
            if message_ids:
                tx_target_filters.append(MessageTxTargetItem.message_id.in_(message_ids))
                rx_target_filters.append(MessageRxTargetItem.message_id.in_(message_ids))
            if tx_target_filters:
                db.query(MessageTxTargetItem).filter(or_(*tx_target_filters)).delete(synchronize_session=False)
            if rx_target_filters:
                db.query(MessageRxTargetItem).filter(or_(*rx_target_filters)).delete(synchronize_session=False)

        if message_ids:
            db.query(MessageEnumValue).filter(MessageEnumValue.message_id.in_(message_ids)).delete(synchronize_session=False)
            db.query(MessageField).filter(MessageField.message_id.in_(message_ids)).delete(synchronize_session=False)
            db.query(MessageChangeHistory).filter(
                or_(
                    MessageChangeHistory.project_id == project_id,
                    MessageChangeHistory.message_id.in_(message_ids),
                )
            ).delete(synchronize_session=False)
        else:
            db.query(MessageChangeHistory).filter(MessageChangeHistory.project_id == project_id).delete(synchronize_session=False)

        if group_ids:
            db.query(MessageGroup).filter(MessageGroup.id.in_(group_ids)).delete(synchronize_session=False)
        db.query(MessageGroup).filter(MessageGroup.project_id == project_id).delete(synchronize_session=False)

        if message_ids:
            db.query(Message).filter(Message.id.in_(message_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.project_id == project_id).delete(synchronize_session=False)

        if label_ids:
            db.query(MessageLabel).filter(MessageLabel.id.in_(label_ids)).delete(synchronize_session=False)
        db.query(MessageLabel).filter(MessageLabel.project_id == project_id).delete(synchronize_session=False)

        if target_ids:
            db.query(IntegrationTarget).filter(IntegrationTarget.id.in_(target_ids)).delete(synchronize_session=False)
        db.query(IntegrationTarget).filter(IntegrationTarget.project_id == project_id).delete(synchronize_session=False)

        if backup_ids:
            db.query(ProjectBackupEvent).filter(
                or_(
                    ProjectBackupEvent.project_id == project_id,
                    ProjectBackupEvent.backup_id.in_(backup_ids),
                    ProjectBackupEvent.auto_backup_id.in_(backup_ids),
                )
            ).delete(synchronize_session=False)
            db.query(ProjectBackup).filter(ProjectBackup.source_backup_id.in_(backup_ids)).update(
                {ProjectBackup.source_backup_id: None},
                synchronize_session=False,
            )
            db.query(ProjectBackup).filter(ProjectBackup.id.in_(backup_ids)).delete(synchronize_session=False)
        else:
            db.query(ProjectBackupEvent).filter(ProjectBackupEvent.project_id == project_id).delete(synchronize_session=False)
        db.query(ProjectBackup).filter(ProjectBackup.project_id == project_id).delete(synchronize_session=False)
        db.query(ProjectBackupEvent).filter(ProjectBackupEvent.project_id == project_id).delete(synchronize_session=False)

        # Use bulk delete instead of ORM cascade delete. The child rows above were already
        # removed explicitly; bulk delete avoids stale relationship/cascade side effects.
        db.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
        db.commit()
        return {"ok": True}
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"프로젝트 삭제 중 참조 제약이 발생했습니다: {exc.orig}")
