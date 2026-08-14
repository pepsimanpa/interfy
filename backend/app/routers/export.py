from fastapi import APIRouter, Depends, HTTPException, Response
from urllib.parse import quote
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..models import Project, Message, MessageField, MessageGroup, MessageLabel, IntegrationTarget, User
from ..auth import get_current_user
from ..services.exporters import render_header, render_idl, render_csharp, to_macro_name
from .project_json import export_project_json as export_project_json_impl

router = APIRouter(tags=["export"])


def safe_filename_part(value: str) -> str:
    value = (value or "").strip() or "export"
    return value.replace("/", "_").replace("\\", "_")


def messages_with_dependencies(db: Session, project_id: int, base_message_ids: list[int] | None = None) -> list[Message]:
    all_messages = (
        db.query(Message)
        .options(joinedload(Message.fields).joinedload(MessageField.ref_message))
        .filter(Message.project_id == project_id)
        .all()
    )
    message_by_id = {message.id: message for message in all_messages}
    if base_message_ids is None:
        selected_ids = set(message_by_id.keys())
    else:
        selected_ids = {message_id for message_id in base_message_ids if message_id in message_by_id}

    pending = list(selected_ids)
    while pending:
        message_id = pending.pop()
        message = message_by_id.get(message_id)
        if not message:
            continue
        for field in message.fields:
            if (getattr(field, "type_kind", "BASIC") or "BASIC").upper() in {"MESSAGE", "ENUM"} and field.ref_message_id in message_by_id and field.ref_message_id not in selected_ids:
                selected_ids.add(field.ref_message_id)
                pending.append(field.ref_message_id)

    return [message_by_id[message_id] for message_id in selected_ids]


def project_messages(db: Session, project_id: int) -> tuple[Project, list[Message]]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project, messages_with_dependencies(db, project_id)


def group_messages(db: Session, group_id: int) -> tuple[Project, MessageGroup, list[Message]]:
    group = db.get(MessageGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    project = db.get(Project, group.project_id)
    base_ids = [item.message_id for item in sorted(group.items or [], key=lambda item: ((getattr(item, "order_index", 0) or 0), item.id or 0))]
    return project, group, messages_with_dependencies(db, project.id, base_ids)



def label_messages(db: Session, label_id: int) -> tuple[Project, MessageLabel, list[Message]]:
    label = db.get(MessageLabel, label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    project = db.get(Project, label.project_id)
    base_ids = [item.message_id for item in (label.items or [])]
    return project, label, messages_with_dependencies(db, project.id, base_ids)


def integration_target_messages(db: Session, target_id: int, direction: str | None = "all") -> tuple[Project, IntegrationTarget, list[Message]]:
    target = db.get(IntegrationTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Integration target not found")
    project = db.get(Project, target.project_id)
    direction_key = (direction or "all").strip().lower()
    if direction_key not in {"tx", "rx", "all"}:
        raise HTTPException(status_code=422, detail="direction은 tx, rx, all 중 하나여야 합니다.")

    base_ids: list[int] = []
    if direction_key in {"tx", "all"}:
        base_ids.extend(item.message_id for item in (target.tx_items or []))
    if direction_key in {"rx", "all"}:
        base_ids.extend(item.message_id for item in (target.rx_items or []))

    base_ids = list(dict.fromkeys(base_ids))
    return project, target, messages_with_dependencies(db, project.id, base_ids)

def file_response(content: str, filename: str, media_type: str = "text/plain") -> Response:
    safe_filename = quote(filename)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"})


@router.get("/projects/{project_id}/export/json")
def export_project_json_alias(project_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Compatibility route registered in the export router so the JSON button works
    # even when only export routes are loaded by an older container/image.
    return export_project_json_impl(project_id, db, current_user)


@router.get("/projects/{project_id}/export/header")
def export_project_header(project_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, messages = project_messages(db, project_id)
    acronym = project.acronym or to_macro_name(project.name)
    return file_response(render_header(project.name, messages, acronym, timezone_name=timezone), f"{safe_filename_part(acronym)}.h", "text/x-c")


@router.get("/projects/{project_id}/export/idl")
def export_project_idl(project_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, messages = project_messages(db, project_id)
    acronym = project.acronym or to_macro_name(project.name)
    return file_response(render_idl(project.name, messages, acronym, timezone_name=timezone), f"{safe_filename_part(acronym)}.idl")


@router.get("/projects/{project_id}/export/csharp")
def export_project_csharp(project_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, messages = project_messages(db, project_id)
    acronym = project.acronym or to_macro_name(project.name)
    return file_response(render_csharp(project.name, messages, acronym, timezone_name=timezone), f"{safe_filename_part(acronym)}.cs", "text/x-csharp")


@router.get("/groups/{group_id}/export/header")
def export_group_header(group_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, group, messages = group_messages(db, group_id)
    acronym = project.acronym or to_macro_name(project.name)
    filename_base = f"{safe_filename_part(acronym)}_{safe_filename_part(group.name)}"
    return file_response(render_header(project.name, messages, acronym, timezone_name=timezone), f"{filename_base}.h", "text/x-c")


@router.get("/groups/{group_id}/export/idl")
def export_group_idl(group_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, group, messages = group_messages(db, group_id)
    acronym = project.acronym or to_macro_name(project.name)
    filename_base = f"{safe_filename_part(acronym)}_{safe_filename_part(group.name)}"
    return file_response(render_idl(project.name, messages, acronym, timezone_name=timezone), f"{filename_base}.idl")


@router.get("/groups/{group_id}/export/csharp")
def export_group_csharp(group_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, group, messages = group_messages(db, group_id)
    acronym = project.acronym or to_macro_name(project.name)
    filename_base = f"{safe_filename_part(acronym)}_{safe_filename_part(group.name)}"
    return file_response(render_csharp(project.name, messages, acronym, timezone_name=timezone), f"{filename_base}.cs", "text/x-csharp")


@router.get("/labels/{label_id}/export/header")
def export_label_header(label_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, label, messages = label_messages(db, label_id)
    acronym = project.acronym or to_macro_name(project.name)
    filename_base = f"{safe_filename_part(acronym)}_{safe_filename_part(label.name)}"
    return file_response(render_header(project.name, messages, acronym, timezone_name=timezone), f"{filename_base}.h", "text/x-c")


@router.get("/labels/{label_id}/export/idl")
def export_label_idl(label_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, label, messages = label_messages(db, label_id)
    acronym = project.acronym or to_macro_name(project.name)
    filename_base = f"{safe_filename_part(acronym)}_{safe_filename_part(label.name)}"
    return file_response(render_idl(project.name, messages, acronym, timezone_name=timezone), f"{filename_base}.idl")


@router.get("/labels/{label_id}/export/csharp")
def export_label_csharp(label_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, label, messages = label_messages(db, label_id)
    acronym = project.acronym or to_macro_name(project.name)
    filename_base = f"{safe_filename_part(acronym)}_{safe_filename_part(label.name)}"
    return file_response(render_csharp(project.name, messages, acronym, timezone_name=timezone), f"{filename_base}.cs", "text/x-csharp")


@router.get("/integration-targets/{target_id}/export/header")
def export_integration_target_header(target_id: int, direction: str | None = "all", timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, target, messages = integration_target_messages(db, target_id, direction)
    acronym = project.acronym or to_macro_name(project.name)
    direction_key = (direction or "all").strip().upper()
    filename_base = f"{safe_filename_part(acronym)}_{safe_filename_part(target.name)}_{direction_key}"
    return file_response(render_header(project.name, messages, acronym, timezone_name=timezone), f"{filename_base}.h", "text/x-c")


@router.get("/integration-targets/{target_id}/export/idl")
def export_integration_target_idl(target_id: int, direction: str | None = "all", timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, target, messages = integration_target_messages(db, target_id, direction)
    acronym = project.acronym or to_macro_name(project.name)
    direction_key = (direction or "all").strip().upper()
    filename_base = f"{safe_filename_part(acronym)}_{safe_filename_part(target.name)}_{direction_key}"
    return file_response(render_idl(project.name, messages, acronym, timezone_name=timezone), f"{filename_base}.idl")


@router.get("/integration-targets/{target_id}/export/csharp")
def export_integration_target_csharp(target_id: int, direction: str | None = "all", timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project, target, messages = integration_target_messages(db, target_id, direction)
    acronym = project.acronym or to_macro_name(project.name)
    direction_key = (direction or "all").strip().upper()
    filename_base = f"{safe_filename_part(acronym)}_{safe_filename_part(target.name)}_{direction_key}"
    return file_response(render_csharp(project.name, messages, acronym, timezone_name=timezone), f"{filename_base}.cs", "text/x-csharp")


# Backward-compatible aliases.
@router.get("/projects/{project_id}/export/ldl")
def export_project_ldl_alias(project_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return export_project_idl(project_id, timezone, db, current_user)


@router.get("/groups/{group_id}/export/ldl")
def export_group_ldl_alias(group_id: int, timezone: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return export_group_idl(group_id, timezone, db, current_user)
