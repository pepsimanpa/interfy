from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..protocols import normalize_protocol_string, split_protocols
from ..models import (
    Project,
    Message,
    MessageField,
    MessageEnumValue,
    MessageGroup,
    MessageGroupItem,
    MessageLabel,
    MessageLabelItem,
    MessageTxLabelItem,
    MessageRxLabelItem,
    IntegrationTarget,
    MessageTxTargetItem,
    MessageRxTargetItem,
    MessageChangeHistory,
    ProjectBackup,
    ProjectBackupEvent,
    User,
    ChangeType,
)
from ..schemas import BackupCreate, BackupRead, BackupEventRead
from ..auth import get_current_user

router = APIRouter(tags=["backups"])
BACKUP_FORMAT = "project_message_database_v2"


def _user_name(user: User | None, fallback_id: int | None = None) -> str:
    if user is not None:
        return user.display_name or user.email
    return f"사용자 #{fallback_id}" if fallback_id else "-"


def _dt(value: datetime | None):
    return value.isoformat() if value else None


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _normalize_array_dimensions(row: dict) -> str | None:
    raw = row.get("array_dimensions")
    if raw is not None and str(raw).strip() not in {"", "0"}:
        parts = [part.strip() for part in str(raw).split(",")]
        if parts and all(part.isdigit() and int(part) > 0 for part in parts):
            return ",".join(str(int(part)) for part in parts)
    if row.get("is_array") and row.get("array_size"):
        try:
            size = int(row.get("array_size"))
            if size > 0:
                return str(size)
        except (TypeError, ValueError):
            pass
    return None


def _first_array_dimension(array_dimensions: str | None) -> int | None:
    if not array_dimensions:
        return None
    try:
        return int(str(array_dimensions).split(",")[0])
    except (TypeError, ValueError):
        return None


def _normalize_field_backup_row(row: dict) -> dict:
    data = dict(row or {})
    type_kind = str(data.get("type_kind") or "BASIC").upper()
    field_type = data.get("type") or "int32"
    dimensions = _normalize_array_dimensions(data)
    if type_kind != "MESSAGE" and field_type == "string":
        field_type = "char"
        dimensions = dimensions or "256"
    is_array = dimensions is not None
    data["type"] = field_type
    data["type_kind"] = type_kind if type_kind in {"MESSAGE", "ENUM"} else "BASIC"
    data["is_array"] = is_array
    data["array_dimensions"] = dimensions
    data["array_size"] = _first_array_dimension(dimensions) if is_array else None
    legacy_display_name = str(data.get("name") or "").strip()
    field_name = str(data.get("variable_name") or legacy_display_name or "").strip()
    data["name"] = field_name
    data["variable_name"] = field_name
    purpose = str(data.get("purpose") or "").strip()
    if legacy_display_name and legacy_display_name != field_name:
        if not purpose:
            purpose = legacy_display_name
        elif legacy_display_name.lower() not in purpose.lower():
            purpose = f"{legacy_display_name} - {purpose}"
    data["purpose"] = purpose
    data["value_range"] = data.get("value_range") or ""
    data["unit"] = data.get("unit") or ""
    data["note"] = data.get("note") or data.get("description") or ""
    return data


def _build_database_backup(db: Session, project_id: int) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    messages = (
        db.query(Message)
        .options(joinedload(Message.fields), joinedload(Message.enum_values), joinedload(Message.labels), joinedload(Message.tx_targets), joinedload(Message.rx_targets))
        .filter(Message.project_id == project_id)
        .order_by(Message.order_index.asc(), Message.id.asc())
        .all()
    )
    message_ids = [message.id for message in messages]

    groups = (
        db.query(MessageGroup)
        .options(joinedload(MessageGroup.items))
        .filter(MessageGroup.project_id == project_id)
        .order_by(MessageGroup.id.asc())
        .all()
    )
    labels = (
        db.query(MessageLabel)
        .options(joinedload(MessageLabel.items))
        .filter(MessageLabel.project_id == project_id)
        .order_by(MessageLabel.name.asc(), MessageLabel.id.asc())
        .all()
    )
    integration_targets = (
        db.query(IntegrationTarget)
        .options(joinedload(IntegrationTarget.tx_items), joinedload(IntegrationTarget.rx_items))
        .filter(IntegrationTarget.project_id == project_id)
        .order_by(IntegrationTarget.name.asc(), IntegrationTarget.id.asc())
        .all()
    )
    histories = (
        db.query(MessageChangeHistory)
        .filter(MessageChangeHistory.project_id == project_id)
        .order_by(MessageChangeHistory.id.asc())
        .all()
    )

    return {
        "format": BACKUP_FORMAT,
        "created_at": datetime.utcnow().isoformat(),
        "project": {
            "id": project.id,
            "name": project.name,
            "acronym": project.acronym,
            "description": project.description,
            "owner_id": project.owner_id,
            "created_at": _dt(project.created_at),
            "updated_at": _dt(project.updated_at),
        },
        "messages": [
            {
                "id": message.id,
                "project_id": message.project_id,
                "name": message.name,
                "struct_name": getattr(message, "struct_name", None) or message.name,
                "period": message.period,
                "description": message.description,
                "infocode": getattr(message, "infocode", None),
                "protocol": normalize_protocol_string(getattr(message, "protocol", None)),
                "protocols": split_protocols(getattr(message, "protocol", None)),
                "definition_type": getattr(message, "definition_type", "STRUCT") or "STRUCT",
                "enum_underlying_type": getattr(message, "enum_underlying_type", "uint32") or "uint32",
                "version": message.version,
                "order_index": message.order_index,
                "created_at": _dt(message.created_at),
                "updated_at": _dt(message.updated_at),
            }
            for message in messages
        ],
        "message_fields": [
            {
                "id": field.id,
                "message_id": field.message_id,
                "type": field.type,
                "type_kind": getattr(field, "type_kind", None) or "BASIC",
                "ref_message_id": field.ref_message_id,
                "name": getattr(field, "variable_name", None) or field.name,
                "variable_name": getattr(field, "variable_name", None) or field.name,
                "description": field.description,
                "purpose": getattr(field, "purpose", None) or "",
                "value_range": getattr(field, "value_range", None) or "",
                "unit": getattr(field, "unit", None) or "",
                "note": getattr(field, "note", None) or "",
                "is_array": field.is_array,
                "array_size": field.array_size,
                "array_dimensions": getattr(field, "array_dimensions", None),
                "order_index": field.order_index,
                "created_at": _dt(field.created_at),
                "updated_at": _dt(field.updated_at),
            }
            for message in messages
            for field in sorted(message.fields, key=lambda f: (f.order_index, f.id))
        ],
        "message_enum_values": [
            {
                "id": value.id,
                "message_id": value.message_id,
                "name": value.name,
                "value": value.value,
                "description": value.description,
                "order_index": value.order_index,
                "created_at": _dt(value.created_at),
                "updated_at": _dt(value.updated_at),
            }
            for message in messages
            for value in sorted(message.enum_values or [], key=lambda v: (v.order_index, v.id))
        ],
        "message_groups": [
            {
                "id": group.id,
                "project_id": group.project_id,
                "name": group.name,
                "description": group.description,
                "created_at": _dt(group.created_at),
                "updated_at": _dt(group.updated_at),
            }
            for group in groups
        ],
        "message_group_items": [
            {
                "id": item.id,
                "group_id": item.group_id,
                "message_id": item.message_id,
                "order_index": getattr(item, "order_index", 0) or 0,
            }
            for group in groups
            for item in sorted(group.items, key=lambda i: ((getattr(i, "order_index", 0) or 0), i.id))
            if item.message_id in message_ids
        ],
        "message_labels": [
            {
                "id": label.id,
                "project_id": label.project_id,
                "name": label.name,
                "description": label.description,
                "created_at": _dt(label.created_at),
                "updated_at": _dt(label.updated_at),
            }
            for label in labels
        ],
        "message_label_items": [
            {
                "id": item.id,
                "label_id": item.label_id,
                "message_id": item.message_id,
            }
            for label in labels
            for item in sorted(label.items, key=lambda i: i.id)
            if item.message_id in message_ids
        ],
        "message_tx_label_items": [
            {
                "id": item.id,
                "label_id": item.label_id,
                "message_id": item.message_id,
            }
            for message in messages
            for item in sorted(getattr(message, "tx_label_items", []) or [], key=lambda i: i.id)
            if item.message_id in message_ids
        ],
        "message_rx_label_items": [
            {
                "id": item.id,
                "label_id": item.label_id,
                "message_id": item.message_id,
            }
            for message in messages
            for item in sorted(getattr(message, "rx_label_items", []) or [], key=lambda i: i.id)
            if item.message_id in message_ids
        ],
        "integration_targets": [
            {
                "id": target.id,
                "project_id": target.project_id,
                "name": target.name,
                "description": target.description,
                "created_at": _dt(target.created_at),
                "updated_at": _dt(target.updated_at),
            }
            for target in integration_targets
        ],
        "message_tx_target_items": [
            {
                "id": item.id,
                "target_id": item.target_id,
                "message_id": item.message_id,
            }
            for target in integration_targets
            for item in sorted(getattr(target, "tx_items", []) or [], key=lambda i: i.id)
            if item.message_id in message_ids
        ],
        "message_rx_target_items": [
            {
                "id": item.id,
                "target_id": item.target_id,
                "message_id": item.message_id,
            }
            for target in integration_targets
            for item in sorted(getattr(target, "rx_items", []) or [], key=lambda i: i.id)
            if item.message_id in message_ids
        ],
        "message_change_histories": [
            {
                "id": history.id,
                "message_id": history.message_id,
                "project_id": history.project_id,
                "changed_by": history.changed_by,
                "change_type": _enum_value(history.change_type),
                "before_json": history.before_json,
                "after_json": history.after_json,
                "created_at": _dt(history.created_at),
            }
            for history in histories
        ],
    }


def _backup_counts(payload: dict) -> tuple[int, int]:
    return len(payload.get("messages") or []), len(payload.get("message_fields") or [])


def _legacy_snapshot_to_database_backup(snapshot: dict, project_id: int) -> dict:
    """Read old MVP snapshot backups without keeping the old restore model.

    Existing backups created before this redesign had messages with nested fields and
    groups with message_names. Convert them once at restore time into the database-backup
    shape. New backups are stored directly in the v2 table-shaped format.
    """
    if snapshot.get("format") == BACKUP_FORMAT:
        return snapshot

    messages = []
    fields = []
    groups = []
    group_items = []
    message_name_to_id = {}
    next_negative_field_id = -1
    next_negative_group_id = -1
    next_negative_item_id = -1

    for idx, message in enumerate(snapshot.get("messages") or [], start=1):
        message_id = int(message.get("id") or -idx)
        name = message.get("name") or f"Message_{idx}"
        message_name_to_id[name] = message_id
        messages.append({
            "id": message_id,
            "project_id": project_id,
            "name": name,
            "period": message.get("period") or "비주기",
            "description": message.get("description") or "",
            "definition_type": message.get("definition_type") or "STRUCT",
            "enum_underlying_type": message.get("enum_underlying_type") or "uint32",
            "version": int(message.get("version") or 1),
            "order_index": int(message.get("order_index") or idx),
            "created_at": None,
            "updated_at": None,
        })
        for fidx, field in enumerate(message.get("fields") or [], start=1):
            field_id = int(field.get("id") or next_negative_field_id)
            next_negative_field_id -= 1
            fields.append({
                "id": field_id,
                "message_id": message_id,
                "type": field.get("type") or "int32",
                "type_kind": field.get("type_kind") or "BASIC",
                "ref_message_id": field.get("ref_message_id"),
                "name": field.get("name") or f"field_{fidx}",
                "description": field.get("description") or "",
                "is_array": bool(field.get("is_array")),
                "array_size": field.get("array_size"),
                "array_dimensions": field.get("array_dimensions"),
                "order_index": int(field.get("order_index") or fidx),
                "created_at": None,
                "updated_at": None,
            })

    for gidx, group in enumerate(snapshot.get("groups") or [], start=1):
        group_id = int(group.get("id") or next_negative_group_id)
        next_negative_group_id -= 1
        groups.append({
            "id": group_id,
            "project_id": project_id,
            "name": group.get("name") or f"Group_{gidx}",
            "description": group.get("description") or "",
            "created_at": None,
            "updated_at": None,
        })
        for message_name in group.get("message_names") or []:
            message_id = message_name_to_id.get(message_name)
            if message_id is not None:
                group_items.append({"id": next_negative_item_id, "group_id": group_id, "message_id": message_id})
                next_negative_item_id -= 1

    return {
        "format": BACKUP_FORMAT,
        "created_at": snapshot.get("created_at"),
        "project": snapshot.get("project") or {"id": project_id},
        "messages": messages,
        "message_fields": fields,
        "message_groups": groups,
        "message_group_items": group_items,
        "message_change_histories": [],
    }


def _backup_read(backup: ProjectBackup) -> dict:
    return {
        "id": backup.id,
        "project_id": backup.project_id,
        "created_by": backup.created_by,
        "created_by_name": _user_name(backup.user, backup.created_by),
        "kind": getattr(backup, "kind", None) or "MANUAL",
        "source_backup_id": getattr(backup, "source_backup_id", None),
        "message_count": backup.message_count,
        "field_count": backup.field_count,
        "note": getattr(backup, "note", None),
        "created_at": backup.created_at,
    }


def _event_read(event: ProjectBackupEvent) -> dict:
    return {
        "id": event.id,
        "project_id": event.project_id,
        "event_type": event.event_type,
        "backup_id": event.backup_id,
        "auto_backup_id": event.auto_backup_id,
        "created_by": event.created_by,
        "created_by_name": _user_name(event.user, event.created_by),
        "created_at": event.created_at,
    }


def _create_project_backup(db: Session, project_id: int, user: User, *, kind: str = "MANUAL", source_backup_id: int | None = None, note: str | None = None) -> ProjectBackup:
    payload = _build_database_backup(db, project_id)
    message_count, field_count = _backup_counts(payload)
    backup = ProjectBackup(
        project_id=project_id,
        created_by=user.id,
        snapshot_json=payload,
        kind=kind,
        source_backup_id=source_backup_id,
        message_count=message_count,
        field_count=field_count,
        note=(note or "").strip() or None,
    )
    db.add(backup)
    db.flush()
    db.add(ProjectBackupEvent(
        project_id=project_id,
        event_type="BACKUP",
        backup_id=backup.id,
        auto_backup_id=None,
        created_by=user.id,
    ))
    db.flush()
    return backup


def _reset_sequence(db: Session, table_name: str, id_column: str = "id") -> None:
    try:
        db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table_name}', '{id_column}'), COALESCE((SELECT MAX({id_column}) FROM {table_name}), 1), true)"))
    except Exception:
        # Non-Postgres engines used for lightweight local tests do not require this.
        pass


def _restore_database_backup(db: Session, project: Project, backup_payload: dict) -> None:
    payload = _legacy_snapshot_to_database_backup(backup_payload or {}, project.id)
    project_data = payload.get("project") or {}

    message_ids = [int(row[0]) for row in db.query(Message.id).filter(Message.project_id == project.id).all()]
    group_ids = [int(row[0]) for row in db.query(MessageGroup.id).filter(MessageGroup.project_id == project.id).all()]
    label_ids = [int(row[0]) for row in db.query(MessageLabel.id).filter(MessageLabel.project_id == project.id).all()]
    target_ids = [int(row[0]) for row in db.query(IntegrationTarget.id).filter(IntegrationTarget.project_id == project.id).all()]

    if group_ids:
        db.query(MessageGroupItem).filter(MessageGroupItem.group_id.in_(group_ids)).delete(synchronize_session=False)
    if label_ids:
        db.query(MessageLabelItem).filter(MessageLabelItem.label_id.in_(label_ids)).delete(synchronize_session=False)
        db.query(MessageTxLabelItem).filter(MessageTxLabelItem.label_id.in_(label_ids)).delete(synchronize_session=False)
        db.query(MessageRxLabelItem).filter(MessageRxLabelItem.label_id.in_(label_ids)).delete(synchronize_session=False)
    if message_ids:
        db.query(MessageLabelItem).filter(MessageLabelItem.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(MessageTxLabelItem).filter(MessageTxLabelItem.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(MessageRxLabelItem).filter(MessageRxLabelItem.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id.in_(message_ids)).delete(synchronize_session=False)
    if target_ids:
        db.query(MessageTxTargetItem).filter(MessageTxTargetItem.target_id.in_(target_ids)).delete(synchronize_session=False)
        db.query(MessageRxTargetItem).filter(MessageRxTargetItem.target_id.in_(target_ids)).delete(synchronize_session=False)
    db.query(MessageGroup).filter(MessageGroup.project_id == project.id).delete(synchronize_session=False)
    db.query(MessageLabel).filter(MessageLabel.project_id == project.id).delete(synchronize_session=False)
    db.query(IntegrationTarget).filter(IntegrationTarget.project_id == project.id).delete(synchronize_session=False)
    if message_ids:
        db.query(MessageEnumValue).filter(MessageEnumValue.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(MessageField).filter(MessageField.message_id.in_(message_ids)).delete(synchronize_session=False)
    db.query(MessageChangeHistory).filter(MessageChangeHistory.project_id == project.id).delete(synchronize_session=False)
    db.query(Message).filter(Message.project_id == project.id).delete(synchronize_session=False)
    db.flush()

    project.name = project_data.get("name") or project.name
    project.acronym = project_data.get("acronym") or project.acronym
    project.description = project_data.get("description") or project.description or ""
    project.updated_at = _parse_dt(project_data.get("updated_at")) or datetime.utcnow()
    db.flush()

    restored_message_ids: set[int] = set()
    for row in payload.get("messages") or []:
        message_id = int(row.get("id"))
        restored_message_ids.add(message_id)
        db.add(Message(
            id=message_id,
            project_id=project.id,
            name=row.get("name") or f"Message_{message_id}",
            struct_name=row.get("struct_name") or row.get("name") or f"Message_{message_id}",
            period=row.get("period") or "비주기",
            description=row.get("description") or "",
            infocode=row.get("infocode"),
            protocol=normalize_protocol_string(row.get("protocols") if "protocols" in row else row.get("protocol")),
            definition_type=str(row.get("definition_type") or "STRUCT").upper(),
            enum_underlying_type=row.get("enum_underlying_type") or "uint32",
            version=int(row.get("version") or 1),
            order_index=int(row.get("order_index") or 0),
            created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
        ))
    db.flush()

    restored_enum_value_ids: set[int] = set()
    for row in payload.get("message_enum_values") or []:
        message_id = int(row.get("message_id"))
        if message_id not in restored_message_ids:
            continue
        value_id = int(row.get("id"))
        restored_enum_value_ids.add(value_id)
        db.add(MessageEnumValue(
            id=value_id,
            message_id=message_id,
            name=row.get("name") or f"ENUM_VALUE_{value_id}",
            value=int(row.get("value") or 0),
            description=row.get("description") or "",
            order_index=int(row.get("order_index") or 0),
            created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
        ))
    db.flush()

    restored_field_ids: set[int] = set()
    for row in payload.get("message_fields") or []:
        row = _normalize_field_backup_row(row)
        message_id = int(row.get("message_id"))
        if message_id not in restored_message_ids:
            continue
        field_id = int(row.get("id"))
        restored_field_ids.add(field_id)
        ref_message_id = row.get("ref_message_id")
        try:
            ref_message_id = int(ref_message_id) if ref_message_id is not None else None
        except (TypeError, ValueError):
            ref_message_id = None
        if ref_message_id not in restored_message_ids:
            ref_message_id = None
        type_kind = str(row.get("type_kind") or "BASIC").upper()
        if type_kind not in {"MESSAGE", "ENUM"}:
            ref_message_id = None
            type_kind = "BASIC"
        db.add(MessageField(
            id=field_id,
            message_id=message_id,
            type=row.get("type") or "int32",
            type_kind=type_kind,
            ref_message_id=ref_message_id,
            name=row.get("variable_name") or row.get("name") or f"field_{field_id}",
            variable_name=row.get("variable_name") or row.get("name") or f"field_{field_id}",
            description=row.get("description") or "",
            purpose=row.get("purpose") or "",
            value_range=row.get("value_range") or "",
            unit=row.get("unit") or "",
            note=row.get("note") or row.get("description") or "",
            is_array=bool(row.get("is_array")),
            array_size=row.get("array_size"),
            array_dimensions=row.get("array_dimensions"),
            order_index=int(row.get("order_index") or 0),
            created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
        ))
    db.flush()

    restored_group_ids: set[int] = set()
    for row in payload.get("message_groups") or []:
        group_id = int(row.get("id"))
        restored_group_ids.add(group_id)
        db.add(MessageGroup(
            id=group_id,
            project_id=project.id,
            name=row.get("name") or f"Group_{group_id}",
            description=row.get("description") or "",
            created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
        ))
    db.flush()

    for row in payload.get("message_group_items") or []:
        group_id = int(row.get("group_id"))
        message_id = int(row.get("message_id"))
        if group_id not in restored_group_ids or message_id not in restored_message_ids:
            continue
        db.add(MessageGroupItem(
            id=int(row.get("id")),
            group_id=group_id,
            message_id=message_id,
            order_index=int(row.get("order_index") or 0),
        ))
    db.flush()

    restored_label_ids: set[int] = set()
    for row in payload.get("message_labels") or []:
        label_id = int(row.get("id"))
        restored_label_ids.add(label_id)
        db.add(MessageLabel(
            id=label_id,
            project_id=project.id,
            name=row.get("name") or f"Label_{label_id}",
            description=row.get("description") or "",
            created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
        ))
    db.flush()

    for row in payload.get("message_label_items") or []:
        label_id = int(row.get("label_id"))
        message_id = int(row.get("message_id"))
        if label_id not in restored_label_ids or message_id not in restored_message_ids:
            continue
        item_id = row.get("id")
        db.add(MessageLabelItem(
            id=int(item_id) if item_id is not None else None,
            label_id=label_id,
            message_id=message_id,
        ))
    db.flush()

    for row in payload.get("message_tx_label_items") or []:
        label_id = int(row.get("label_id"))
        message_id = int(row.get("message_id"))
        if label_id not in restored_label_ids or message_id not in restored_message_ids:
            continue
        item_id = row.get("id")
        db.add(MessageTxLabelItem(
            id=int(item_id) if item_id is not None else None,
            label_id=label_id,
            message_id=message_id,
        ))
    for row in payload.get("message_rx_label_items") or []:
        label_id = int(row.get("label_id"))
        message_id = int(row.get("message_id"))
        if label_id not in restored_label_ids or message_id not in restored_message_ids:
            continue
        item_id = row.get("id")
        db.add(MessageRxLabelItem(
            id=int(item_id) if item_id is not None else None,
            label_id=label_id,
            message_id=message_id,
        ))
    db.flush()

    restored_target_ids: set[int] = set()
    for row in payload.get("integration_targets") or []:
        target_id = int(row.get("id"))
        restored_target_ids.add(target_id)
        db.add(IntegrationTarget(
            id=target_id,
            project_id=project.id,
            name=row.get("name") or f"Target_{target_id}",
            description=row.get("description") or "",
            created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
        ))
    db.flush()

    for row in payload.get("message_tx_target_items") or []:
        target_id = int(row.get("target_id"))
        message_id = int(row.get("message_id"))
        if target_id not in restored_target_ids or message_id not in restored_message_ids:
            continue
        item_id = row.get("id")
        db.add(MessageTxTargetItem(
            id=int(item_id) if item_id is not None else None,
            target_id=target_id,
            message_id=message_id,
        ))
    for row in payload.get("message_rx_target_items") or []:
        target_id = int(row.get("target_id"))
        message_id = int(row.get("message_id"))
        if target_id not in restored_target_ids or message_id not in restored_message_ids:
            continue
        item_id = row.get("id")
        db.add(MessageRxTargetItem(
            id=int(item_id) if item_id is not None else None,
            target_id=target_id,
            message_id=message_id,
        ))
    db.flush()

    for row in payload.get("message_change_histories") or []:
        change_type = row.get("change_type") or ChangeType.UPDATE.value
        try:
            change_type = ChangeType(change_type)
        except ValueError:
            change_type = ChangeType.UPDATE
        message_id = row.get("message_id")
        if message_id is not None:
            try:
                message_id = int(message_id)
            except (TypeError, ValueError):
                message_id = None
            if message_id not in restored_message_ids:
                message_id = None
        db.add(MessageChangeHistory(
            id=int(row.get("id")),
            message_id=message_id,
            project_id=project.id,
            changed_by=int(row.get("changed_by")),
            change_type=change_type,
            before_json=row.get("before_json"),
            after_json=row.get("after_json"),
            created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
        ))
    db.flush()

    for table in ("messages", "message_fields", "message_enum_values", "message_groups", "message_group_items", "message_labels", "message_label_items", "message_tx_label_items", "message_rx_label_items", "integration_targets", "message_tx_target_items", "message_rx_target_items", "message_change_histories"):
        _reset_sequence(db, table)


@router.get("/projects/{project_id}/backups", response_model=list[BackupRead])
def list_backups(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    rows = (
        db.query(ProjectBackup)
        .filter(ProjectBackup.project_id == project_id)
        .order_by(ProjectBackup.created_at.desc(), ProjectBackup.id.desc())
        .all()
    )
    return [_backup_read(row) for row in rows]


@router.get("/projects/{project_id}/backup-events", response_model=list[BackupEventRead])
def list_backup_events(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    rows = (
        db.query(ProjectBackupEvent)
        .filter(ProjectBackupEvent.project_id == project_id)
        .order_by(ProjectBackupEvent.created_at.desc(), ProjectBackupEvent.id.desc())
        .limit(100)
        .all()
    )
    return [_event_read(row) for row in rows]


@router.post("/projects/{project_id}/backups", response_model=BackupRead)
def create_backup(project_id: int, payload: BackupCreate | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    backup = _create_project_backup(db, project_id, current_user, kind="MANUAL", note=payload.note if payload else None)
    db.commit()
    db.refresh(backup)
    return _backup_read(backup)


@router.post("/backups/{backup_id}/restore")
def restore_backup(backup_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    backup = db.get(ProjectBackup, backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    project = db.get(Project, backup.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Always save the exact current database state before restore.
    auto_backup = _create_project_backup(db, project.id, current_user, kind="AUTO_BEFORE_RESTORE", source_backup_id=backup.id)
    db.flush()

    _restore_database_backup(db, project, backup.snapshot_json or {})
    db.flush()

    db.add(ProjectBackupEvent(
        project_id=project.id,
        event_type="RESTORE",
        backup_id=backup.id,
        auto_backup_id=auto_backup.id,
        created_by=current_user.id,
    ))
    db.commit()
    return {"ok": True, "auto_backup_id": auto_backup.id}
