from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
import re
from ..database import get_db
from ..models import Project, Message, MessageField, MessageEnumValue, MessageGroupItem, MessageLabel, MessageLabelItem, MessageTxLabelItem, MessageRxLabelItem, IntegrationTarget, MessageTxTargetItem, MessageRxTargetItem, MessageChangeHistory, ChangeType, User
from ..schemas import MessageCreate, MessageRead, MessageUpdate, MessageReorder, FieldCreate, FieldRead, FieldUpdate, FieldReorder, FieldBulkSave, EnumValueBulkSave, SUPPORTED_TYPES, ENUM_UNDERLYING_TYPES, IDENTIFIER_PATTERN
from ..auth import get_current_user
from ..services.history import add_history, snapshot

router = APIRouter(tags=["messages"])
MESSAGE_FIELDS = ["name", "struct_name", "period", "description", "infocode", "protocol", "definition_type", "enum_underlying_type", "version", "order_index"]
FIELD_FIELDS = ["type", "type_kind", "ref_message_id", "name", "variable_name", "description", "purpose", "value_range", "unit", "note", "is_array", "array_size", "array_dimensions", "order_index"]
ENUM_VALUE_FIELDS = ["name", "value", "description", "order_index"]


def get_message_or_404(db: Session, message_id: int) -> Message:
    message = db.query(Message).options(joinedload(Message.fields).joinedload(MessageField.ref_message), joinedload(Message.enum_values), joinedload(Message.labels), joinedload(Message.tx_targets), joinedload(Message.rx_targets)).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


def ensure_unique_struct_name(db: Session, project_id: int, struct_name: str, exclude_message_id: int | None = None) -> None:
    value = str(struct_name or "").strip()
    query = db.query(Message).filter(Message.project_id == project_id, func.lower(Message.struct_name) == value.lower())
    if exclude_message_id is not None:
        query = query.filter(Message.id != exclude_message_id)
    if query.first():
        raise HTTPException(status_code=409, detail="같은 프로젝트 안에서 메시지 이름은 중복될 수 없습니다.")


def ensure_unique_infocode(db: Session, project_id: int, infocode: str | None, exclude_message_id: int | None = None) -> None:
    value = str(infocode or "").strip()
    if not value:
        return
    query = db.query(Message).filter(Message.project_id == project_id, Message.infocode == value)
    if exclude_message_id is not None:
        query = query.filter(Message.id != exclude_message_id)
    existing = query.first()
    if existing:
        raise HTTPException(status_code=409, detail=f"정보코드는 프로젝트 내에서 중복될 수 없습니다. 이미 사용 중인 메시지: {existing.struct_name or existing.name}")

def struct_name_exists(db: Session, project_id: int, name: str) -> bool:
    return db.query(Message.id).filter(Message.project_id == project_id, func.lower(Message.struct_name) == name.lower()).first() is not None

def make_copy_struct_name(db: Session, project_id: int, source_name: str) -> str:
    max_len = 120
    for index in range(1, 10000):
        suffix = "_copy" if index == 1 else f"_copy{index}"
        root = source_name[: max_len - len(suffix)]
        candidate = f"{root}{suffix}"
        if not struct_name_exists(db, project_id, candidate):
            return candidate
    raise HTTPException(status_code=409, detail="복사 메시지 이름을 생성할 수 없습니다.")


def ensure_unique_field_name(db: Session, message_id: int, name: str, exclude_field_id: int | None = None) -> None:
    query = db.query(MessageField).filter(MessageField.message_id == message_id, func.lower(MessageField.name) == name.lower())
    if exclude_field_id is not None:
        query = query.filter(MessageField.id != exclude_field_id)
    if query.first():
        raise HTTPException(status_code=409, detail="같은 메시지 안에서 필드 이름은 중복될 수 없습니다.")

def ensure_unique_field_variable_name(db: Session, message_id: int, variable_name: str, exclude_field_id: int | None = None) -> None:
    query = db.query(MessageField).filter(MessageField.message_id == message_id, func.lower(MessageField.variable_name) == variable_name.lower())
    if exclude_field_id is not None:
        query = query.filter(MessageField.id != exclude_field_id)
    if query.first():
        raise HTTPException(status_code=409, detail="같은 메시지 안에서 변수 이름은 중복될 수 없습니다.")


def normalize_period(value: str | None) -> str:
    value = str(value or "").strip()
    if value == "" or value == "0" or value == "비주기":
        return "비주기"
    if not value.isdigit():
        raise HTTPException(status_code=422, detail="주기는 숫자만 입력할 수 있습니다.")
    return value

def next_field_order(db: Session, message_id: int) -> int:
    current_max = db.query(func.max(MessageField.order_index)).filter(MessageField.message_id == message_id).scalar()
    return int(current_max or 0) + 1

def next_message_order(db: Session, project_id: int) -> int:
    current_max = db.query(func.max(Message.order_index)).filter(Message.project_id == project_id).scalar()
    return int(current_max or 0) + 1


def _normalize_label_ids(db: Session, project_id: int, label_ids: list[int] | None) -> list[int]:
    ids = list(dict.fromkeys(int(label_id) for label_id in (label_ids or [])))
    if not ids:
        return []
    labels = db.query(MessageLabel).filter(MessageLabel.project_id == project_id, MessageLabel.id.in_(ids)).all()
    if len(labels) != len(ids):
        raise HTTPException(status_code=422, detail="존재하지 않는 라벨이 포함되어 있습니다.")
    label_by_id = {label.id: label for label in labels}
    return [label_id for label_id in ids if label_id in label_by_id]

def assign_message_labels(db: Session, message: Message, label_ids: list[int] | None) -> None:
    ids = _normalize_label_ids(db, message.project_id, label_ids)
    db.query(MessageLabelItem).filter(MessageLabelItem.message_id == message.id).delete(synchronize_session=False)
    for label_id in ids:
        db.add(MessageLabelItem(message_id=message.id, label_id=label_id))

def assign_message_tx_rx_labels(db: Session, message: Message, tx_label_ids: list[int] | None, rx_label_ids: list[int] | None) -> None:
    tx_ids = _normalize_label_ids(db, message.project_id, tx_label_ids)
    rx_ids = _normalize_label_ids(db, message.project_id, rx_label_ids)
    db.query(MessageTxLabelItem).filter(MessageTxLabelItem.message_id == message.id).delete(synchronize_session=False)
    db.query(MessageRxLabelItem).filter(MessageRxLabelItem.message_id == message.id).delete(synchronize_session=False)
    for label_id in tx_ids:
        db.add(MessageTxLabelItem(message_id=message.id, label_id=label_id))
    for label_id in rx_ids:
        db.add(MessageRxLabelItem(message_id=message.id, label_id=label_id))


def _normalize_target_ids(db: Session, project_id: int, target_ids: list[int] | None) -> list[int]:
    ids = list(dict.fromkeys(int(target_id) for target_id in (target_ids or [])))
    if not ids:
        return []
    targets = db.query(IntegrationTarget).filter(IntegrationTarget.project_id == project_id, IntegrationTarget.id.in_(ids)).all()
    if len(targets) != len(ids):
        raise HTTPException(status_code=422, detail="존재하지 않는 노드이 포함되어 있습니다.")
    target_by_id = {target.id: target for target in targets}
    return [target_id for target_id in ids if target_id in target_by_id]

def assign_message_tx_rx_targets(db: Session, message: Message, tx_target_ids: list[int] | None, rx_target_ids: list[int] | None) -> None:
    tx_ids = _normalize_target_ids(db, message.project_id, tx_target_ids)
    rx_ids = _normalize_target_ids(db, message.project_id, rx_target_ids)
    db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id == message.id).delete(synchronize_session=False)
    db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id == message.id).delete(synchronize_session=False)
    for target_id in tx_ids:
        db.add(MessageTxTargetItem(message_id=message.id, target_id=target_id))
    for target_id in rx_ids:
        db.add(MessageRxTargetItem(message_id=message.id, target_id=target_id))


def parse_array_dimensions(value, *, allow_zero_as_empty: bool = True) -> str | None:
    raw = str(value or "").strip()
    if raw == "":
        return None
    if allow_zero_as_empty and raw == "0":
        return None
    parts = [part.strip() for part in raw.split(",")]
    if not parts:
        return None
    dims: list[str] = []
    for part in parts:
        if part == "" or not part.isdigit():
            raise HTTPException(status_code=422, detail="배열 크기는 빈칸, 0, 또는 10 / 3,4 형식으로 입력하세요.")
        value_int = int(part)
        if value_int <= 0:
            raise HTTPException(status_code=422, detail="배열 각 차원은 1 이상의 숫자로 입력하세요.")
        dims.append(str(value_int))
    return ",".join(dims) if dims else None


def first_array_dimension(array_dimensions: str | None) -> int | None:
    if not array_dimensions:
        return None
    try:
        return int(str(array_dimensions).split(",")[0])
    except (TypeError, ValueError):
        return None


def normalize_array_payload(data: dict) -> tuple[bool, str | None, int | None]:
    raw_dimensions = data.get("array_dimensions")
    dimensions = None
    if raw_dimensions is not None:
        dimensions = parse_array_dimensions(raw_dimensions)
    elif data.get("is_array") and data.get("array_size"):
        dimensions = parse_array_dimensions(str(data.get("array_size")))

    is_array = dimensions is not None
    return is_array, dimensions, first_array_dimension(dimensions) if is_array else None


def normalize_field_data(db: Session, message: Message, data: dict) -> dict:
    normalized = dict(data)
    type_kind = str(normalized.get("type_kind") or "BASIC").upper()
    if type_kind not in {"BASIC", "MESSAGE", "ENUM"}:
        raise HTTPException(status_code=422, detail="자료형 종류는 BASIC, MESSAGE 또는 ENUM만 가능합니다.")
    normalized["type_kind"] = type_kind

    is_array, array_dimensions, array_size = normalize_array_payload(normalized)
    normalized["is_array"] = is_array
    normalized["array_dimensions"] = array_dimensions
    normalized["array_size"] = array_size

    if type_kind in {"MESSAGE", "ENUM"}:
        ref_message_id = normalized.get("ref_message_id")
        if ref_message_id is None:
            raise HTTPException(status_code=422, detail="자료형을 선택하세요.")
        ref_message = db.get(Message, int(ref_message_id))
        if not ref_message or ref_message.project_id != message.project_id:
            raise HTTPException(status_code=422, detail="같은 프로젝트의 정의만 자료형으로 선택할 수 있습니다.")
        ref_definition_type = str(getattr(ref_message, "definition_type", "STRUCT") or "STRUCT").upper()
        if type_kind == "MESSAGE" and ref_definition_type != "STRUCT":
            raise HTTPException(status_code=422, detail="메시지 자료형에는 메시지만 선택할 수 있습니다.")
        if type_kind == "ENUM" and ref_definition_type != "ENUM":
            raise HTTPException(status_code=422, detail="Enum 자료형에는 Enum만 선택할 수 있습니다.")
        if ref_message.id == message.id:
            raise HTTPException(status_code=409, detail="자기 자신을 자료형으로 선택할 수 없습니다.")
        normalized["ref_message_id"] = ref_message.id
        normalized["type"] = ref_message.struct_name or ref_message.name
    else:
        field_type = normalized.get("type")
        if field_type not in SUPPORTED_TYPES:
            raise HTTPException(status_code=422, detail=f"Unsupported type: {field_type}")
        normalized["ref_message_id"] = None

    field_name = str(normalized.get("variable_name") or normalized.get("name") or "").strip()
    if not re.fullmatch(IDENTIFIER_PATTERN, field_name):
        raise HTTPException(status_code=422, detail="필드 이름은 영문 또는 _로 시작하고 영문, 숫자, _만 사용할 수 있습니다.")
    normalized["name"] = field_name
    normalized["variable_name"] = field_name
    normalized["description"] = normalized.get("description") or ""
    normalized["purpose"] = normalized.get("purpose") or ""
    normalized["value_range"] = normalized.get("value_range") or ""
    normalized["unit"] = normalized.get("unit") or ""
    normalized["note"] = normalized.get("note") or ""
    return normalized


def ensure_no_message_reference_cycle(db: Session, project_id: int, target_message_id: int, replacement_ref_ids: list[int]) -> None:
    project_messages = (
        db.query(Message)
        .options(joinedload(Message.fields).joinedload(MessageField.ref_message))
        .filter(Message.project_id == project_id)
        .all()
    )
    message_ids = {message.id for message in project_messages}
    edges: dict[int, set[int]] = {message.id: set() for message in project_messages}
    for message in project_messages:
        if message.id == target_message_id:
            continue
        for field in message.fields:
            if (getattr(field, "type_kind", "BASIC") or "BASIC").upper() == "MESSAGE" and field.ref_message_id in message_ids:
                edges[message.id].add(field.ref_message_id)
    edges[target_message_id] = {ref_id for ref_id in replacement_ref_ids if ref_id in message_ids}

    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node_id: int) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for next_id in edges.get(node_id, set()):
            if visit(next_id):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    for message_id in message_ids:
        if visit(message_id):
            raise HTTPException(status_code=409, detail="메시지 자료형 순환 참조는 허용되지 않습니다.")


def field_state_from_obj(field: MessageField) -> dict:
    type_kind = (getattr(field, "type_kind", None) or "BASIC").upper()
    array_dimensions = getattr(field, "array_dimensions", None)
    if not array_dimensions and field.is_array and field.array_size:
        array_dimensions = str(field.array_size)
    return {
        "type": field.type,
        "type_kind": type_kind,
        "ref_message_id": field.ref_message_id if type_kind in {"MESSAGE", "ENUM"} else None,
        "name": field.name,
        "variable_name": field.variable_name or field.name,
        "description": field.description or "",
        "purpose": field.purpose or "",
        "value_range": field.value_range or "",
        "unit": field.unit or "",
        "note": field.note or "",
        "is_array": bool(array_dimensions),
        "array_size": first_array_dimension(array_dimensions),
        "array_dimensions": array_dimensions if array_dimensions else None,
        "order_index": field.order_index,
    }


@router.get("/projects/{project_id}/messages", response_model=list[MessageRead])
def list_messages(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Message).options(joinedload(Message.fields).joinedload(MessageField.ref_message), joinedload(Message.enum_values), joinedload(Message.labels), joinedload(Message.tx_targets), joinedload(Message.rx_targets)).filter(Message.project_id == project_id).order_by(Message.order_index.asc(), Message.id.asc()).all()


@router.post("/projects/{project_id}/messages", response_model=MessageRead)
def create_message(project_id: int, payload: MessageCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_unique_struct_name(db, project_id, payload.struct_name)
    definition_type = (payload.definition_type or "STRUCT").upper()
    if definition_type != "ENUM":
        ensure_unique_infocode(db, project_id, payload.infocode)
    period = "비주기" if definition_type == "ENUM" else normalize_period(payload.period)
    message = Message(
        project_id=project_id,
        name=payload.name,
        struct_name=payload.struct_name,
        period=period,
        description=payload.description,
        infocode=payload.infocode,
        protocol=payload.protocol,
        definition_type=definition_type,
        enum_underlying_type=payload.enum_underlying_type or "uint32",
        version=1,
        order_index=next_message_order(db, project_id),
    )
    db.add(message)
    db.flush()
    assign_message_labels(db, message, payload.label_ids)
    # Legacy tx/rx label fields are accepted but new UI/API uses integration targets.
    assign_message_tx_rx_targets(db, message, payload.tx_target_ids, payload.rx_target_ids)
    db.flush()
    add_history(db, project_id=project_id, message_id=message.id, user=current_user, change_type=ChangeType.CREATE, after=snapshot(message, MESSAGE_FIELDS))
    db.commit()
    return get_message_or_404(db, message.id)


@router.post("/messages/{message_id}/copy", response_model=MessageRead)
def copy_message(message_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    source = get_message_or_404(db, message_id)
    copied = Message(
        project_id=source.project_id,
        name=source.name,
        struct_name=make_copy_struct_name(db, source.project_id, getattr(source, "struct_name", None) or source.name),
        period=source.period,
        description=source.description,
        protocol=getattr(source, "protocol", None),
        # 정보코드는 프로젝트 내 유일해야 하므로 복사본은 비워서 생성합니다.
        infocode=None,
        definition_type=getattr(source, "definition_type", "STRUCT") or "STRUCT",
        enum_underlying_type=getattr(source, "enum_underlying_type", "uint32") or "uint32",
        version=1,
        order_index=next_message_order(db, source.project_id),
    )
    db.add(copied)
    db.flush()

    copied_fields = []
    source_fields = sorted(source.fields or [], key=lambda field: ((field.order_index or 0), (field.id or 0)))
    for index, field in enumerate(source_fields, start=1):
        data = field_state_from_obj(field)
        data["order_index"] = index
        copied_field = MessageField(message_id=copied.id, **data)
        db.add(copied_field)
        copied_fields.append(copied_field)

    copied_enum_values = []
    if (getattr(source, "definition_type", "STRUCT") or "STRUCT").upper() == "ENUM":
        source_values = sorted(source.enum_values or [], key=lambda value: ((value.order_index or 0), (value.id or 0)))
        for index, enum_value in enumerate(source_values, start=1):
            copied_value = MessageEnumValue(
                message_id=copied.id,
                name=enum_value.name,
                value=enum_value.value,
                description=enum_value.description or "",
                order_index=index,
            )
            db.add(copied_value)
            copied_enum_values.append(copied_value)

    for label in source.labels or []:
        db.add(MessageLabelItem(message_id=copied.id, label_id=label.id))
    for target in getattr(source, "tx_targets", []) or []:
        db.add(MessageTxTargetItem(message_id=copied.id, target_id=target.id))
    for target in getattr(source, "rx_targets", []) or []:
        db.add(MessageRxTargetItem(message_id=copied.id, target_id=target.id))

    db.flush()
    add_history(
        db,
        project_id=source.project_id,
        message_id=copied.id,
        user=current_user,
        change_type=ChangeType.CREATE,
        after={
            "message": snapshot(copied, MESSAGE_FIELDS),
            "copied_from_message_id": source.id,
            "copied_from_message_name": source.struct_name or source.name,
            "fields": [snapshot(field, FIELD_FIELDS) for field in copied_fields],
            "enum_values": [snapshot(value, ENUM_VALUE_FIELDS) for value in copied_enum_values],
            "labels": [label.name for label in (source.labels or [])],
        },
    )
    db.commit()
    return get_message_or_404(db, copied.id)



@router.post("/projects/{project_id}/messages/reorder", response_model=list[MessageRead])
def reorder_messages(project_id: int, payload: MessageReorder, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    messages = db.query(Message).filter(Message.project_id == project_id).all()
    message_by_id = {message.id: message for message in messages}
    if set(message_by_id.keys()) != set(payload.message_ids):
        raise HTTPException(status_code=400, detail="message_ids must include every message in this project exactly once")
    before = [snapshot(message_by_id[mid], MESSAGE_FIELDS) for mid in payload.message_ids]
    for index, message_id in enumerate(payload.message_ids, start=1):
        message_by_id[message_id].order_index = index
    db.flush()
    after = [snapshot(message_by_id[mid], MESSAGE_FIELDS) for mid in payload.message_ids]
    add_history(db, project_id=project_id, message_id=None, user=current_user, change_type=ChangeType.UPDATE, before=before, after={"reordered_messages": after})
    db.commit()
    return db.query(Message).options(joinedload(Message.fields).joinedload(MessageField.ref_message), joinedload(Message.enum_values), joinedload(Message.labels), joinedload(Message.tx_targets), joinedload(Message.rx_targets)).filter(Message.project_id == project_id).order_by(Message.order_index.asc(), Message.id.asc()).all()


@router.get("/messages/{message_id}", response_model=MessageRead)
def get_message(message_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_message_or_404(db, message_id)


@router.patch("/messages/{message_id}", response_model=MessageRead)
def update_message(message_id: int, payload: MessageUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = get_message_or_404(db, message_id)
    data = payload.model_dump(exclude_unset=True)
    renamed_to = None
    if "struct_name" in data and data["struct_name"] != (message.struct_name or message.name):
        ensure_unique_struct_name(db, message.project_id, data["struct_name"], exclude_message_id=message.id)
        renamed_to = data["struct_name"]
    if "infocode" in data and (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper() != "ENUM":
        ensure_unique_infocode(db, message.project_id, data.get("infocode"), exclude_message_id=message.id)
    before = snapshot(message, MESSAGE_FIELDS)
    changed = False
    if "period" in data:
        data["period"] = "비주기" if (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper() == "ENUM" else normalize_period(data.get("period"))
    for key, value in data.items():
        if getattr(message, key) != value:
            setattr(message, key, value)
            changed = True
    if changed:
        if renamed_to:
            db.query(MessageField).filter(MessageField.ref_message_id == message.id).update({MessageField.type: renamed_to}, synchronize_session=False)
        if "enum_underlying_type" in data and (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper() == "ENUM":
            message.version += 1
        # 메시지 이름/메시지 용도/주기/설명은 메타데이터 수정으로 보고 버전은 올리지 않습니다.
        # 버전은 필드/Enum 값 변경처럼 실제 데이터 구조가 바뀔 때만 증가합니다.
        db.flush()
        add_history(db, project_id=message.project_id, message_id=message.id, user=current_user, change_type=ChangeType.UPDATE, before=before, after=snapshot(message, MESSAGE_FIELDS))
    db.commit()
    return get_message_or_404(db, message_id)


@router.delete("/messages/{message_id}")
def delete_message(message_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = get_message_or_404(db, message_id)
    referencing_fields = (
        db.query(MessageField)
        .options(joinedload(MessageField.message))
        .filter(MessageField.ref_message_id == message_id, MessageField.message_id != message_id)
        .order_by(MessageField.message_id.asc(), MessageField.order_index.asc(), MessageField.id.asc())
        .all()
    )
    if referencing_fields:
        reference_labels = []
        for field in referencing_fields:
            owner_name = (field.message.struct_name or field.message.name) if field.message is not None else f"메시지 #{field.message_id}"
            reference_labels.append(f"{owner_name}.{field.name}")
        unique_labels = list(dict.fromkeys(reference_labels))
        preview = ", ".join(unique_labels[:8])
        if len(unique_labels) > 8:
            preview += f" 외 {len(unique_labels) - 8}건"
        raise HTTPException(
            status_code=409,
            detail=f"다른 메시지 필드에서 참조 중인 메시지는 삭제할 수 없습니다. 참조 위치: {preview}",
        )
    before = snapshot(message, MESSAGE_FIELDS)
    project_id = message.project_id

    # PostgreSQL enforces foreign-key constraints strictly. A message can be linked
    # from groups and previous change-history rows, so clean up or detach those
    # references before deleting the message itself. Message fields are removed by
    # the Message.fields cascade configured on the ORM relationship.
    db.query(MessageGroupItem).filter(MessageGroupItem.message_id == message_id).delete(synchronize_session=False)
    db.query(MessageLabelItem).filter(MessageLabelItem.message_id == message_id).delete(synchronize_session=False)
    db.query(MessageTxLabelItem).filter(MessageTxLabelItem.message_id == message_id).delete(synchronize_session=False)
    db.query(MessageRxLabelItem).filter(MessageRxLabelItem.message_id == message_id).delete(synchronize_session=False)
    db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id == message_id).delete(synchronize_session=False)
    db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id == message_id).delete(synchronize_session=False)
    db.query(MessageChangeHistory).filter(MessageChangeHistory.message_id == message_id).update(
        {MessageChangeHistory.message_id: None},
        synchronize_session=False,
    )

    db.delete(message)
    add_history(db, project_id=project_id, message_id=None, user=current_user, change_type=ChangeType.DELETE, before=before)
    db.commit()
    return {"ok": True}


@router.get("/messages/{message_id}/fields", response_model=list[FieldRead])
def list_fields(message_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = get_message_or_404(db, message_id)
    if (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper() == "ENUM":
        raise HTTPException(status_code=422, detail="Enum 정의에는 필드를 추가할 수 없습니다.")
    return db.query(MessageField).filter(MessageField.message_id == message_id).order_by(MessageField.order_index.asc(), MessageField.id.asc()).all()




@router.post("/messages/{message_id}/fields/bulk-save", response_model=MessageRead)
def bulk_save_fields(message_id: int, payload: FieldBulkSave, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = get_message_or_404(db, message_id)
    if (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper() != "STRUCT":
        raise HTTPException(status_code=422, detail="Enum 정의에는 필드를 추가할 수 없습니다.")
    normalized_fields = []
    seen_names: set[str] = set()
    for index, item in enumerate(payload.fields, start=1):
        data = normalize_field_data(db, message, item.model_dump(exclude={"id"}))
        name_key = data["name"].lower()
        if name_key in seen_names:
            raise HTTPException(status_code=409, detail="같은 메시지 안에서 필드 이름은 중복될 수 없습니다.")
        seen_names.add(name_key)
        data["order_index"] = index
        normalized_fields.append(data)

    ensure_no_message_reference_cycle(
        db,
        message.project_id,
        message.id,
        [data["ref_message_id"] for data in normalized_fields if data.get("type_kind") == "MESSAGE" and data.get("ref_message_id")],
    )

    current_fields = db.query(MessageField).filter(MessageField.message_id == message_id).order_by(MessageField.order_index.asc(), MessageField.id.asc()).all()

    before_state = [field_state_from_obj(field) for field in current_fields]
    if before_state == normalized_fields:
        return get_message_or_404(db, message_id)

    before_history = [snapshot(field, FIELD_FIELDS) for field in current_fields]
    for field in current_fields:
        db.delete(field)
    db.flush()

    for data in normalized_fields:
        db.add(MessageField(message_id=message_id, **data))

    message.version += 1
    db.flush()
    after_fields = db.query(MessageField).filter(MessageField.message_id == message_id).order_by(MessageField.order_index.asc(), MessageField.id.asc()).all()
    after_history = [snapshot(field, FIELD_FIELDS) for field in after_fields]
    add_history(
        db,
        project_id=message.project_id,
        message_id=message.id,
        user=current_user,
        change_type=ChangeType.FIELD_UPDATE,
        before={"fields": before_history},
        after={"fields": after_history, "version": message.version},
    )
    db.commit()
    return get_message_or_404(db, message_id)

def enum_value_state_from_obj(value: MessageEnumValue) -> dict:
    return {
        "name": value.name,
        "value": value.value,
        "description": value.description or "",
        "order_index": value.order_index,
    }


def enum_bounds(underlying_type: str) -> tuple[int, int]:
    return {
        "int8": (-128, 127),
        "uint8": (0, 255),
        "int16": (-32768, 32767),
        "uint16": (0, 65535),
        "int32": (-2147483648, 2147483647),
        "uint32": (0, 4294967295),
        "int64": (-9223372036854775808, 9223372036854775807),
        "uint64": (0, 18446744073709551615),
    }.get(underlying_type or "uint32", (0, 4294967295))


def validate_enum_values_payload(message: Message, values: list[dict]) -> list[dict]:
    min_value, max_value = enum_bounds(getattr(message, "enum_underlying_type", "uint32") or "uint32")
    normalized_values: list[dict] = []
    seen_names: set[str] = set()
    seen_values: set[int] = set()
    for index, value in enumerate(values, start=1):
        name = str(value.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Enum 값 이름을 입력하세요.")
        if not __import__("re").fullmatch(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            raise HTTPException(status_code=422, detail="Enum 값 이름은 영문, 숫자, _ 만 사용할 수 있으며 숫자로 시작할 수 없습니다.")
        name_key = name.lower()
        if name_key in seen_names:
            raise HTTPException(status_code=409, detail="같은 Enum 안에서 값 이름은 중복될 수 없습니다.")
        seen_names.add(name_key)
        try:
            enum_number = int(value.get("value"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"Enum 값은 정수로 입력하세요: {name}")
        if enum_number < min_value or enum_number > max_value:
            raise HTTPException(status_code=422, detail=f"{name} 값은 {message.enum_underlying_type} 범위를 벗어났습니다.")
        if enum_number in seen_values:
            raise HTTPException(status_code=409, detail="같은 Enum 안에서 숫자 값은 중복될 수 없습니다.")
        seen_values.add(enum_number)
        normalized_values.append({
            "name": name,
            "value": enum_number,
            "description": value.get("description") or "",
            "order_index": index,
        })
    return normalized_values


@router.post("/messages/{message_id}/enum-values/bulk-save", response_model=MessageRead)
def bulk_save_enum_values(message_id: int, payload: EnumValueBulkSave, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = get_message_or_404(db, message_id)
    if (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper() != "ENUM":
        raise HTTPException(status_code=422, detail="Enum 정의에서만 Enum 값을 관리할 수 있습니다.")
    normalized_values = validate_enum_values_payload(message, [item.model_dump(exclude={"id"}) for item in payload.values])
    current_values = db.query(MessageEnumValue).filter(MessageEnumValue.message_id == message_id).order_by(MessageEnumValue.order_index.asc(), MessageEnumValue.id.asc()).all()
    before_state = [enum_value_state_from_obj(value) for value in current_values]
    if before_state == normalized_values:
        return get_message_or_404(db, message_id)
    before_history = [snapshot(value, ENUM_VALUE_FIELDS) for value in current_values]
    for value in current_values:
        db.delete(value)
    db.flush()
    for data in normalized_values:
        db.add(MessageEnumValue(message_id=message_id, **data))
    message.version += 1
    db.flush()
    after_values = db.query(MessageEnumValue).filter(MessageEnumValue.message_id == message_id).order_by(MessageEnumValue.order_index.asc(), MessageEnumValue.id.asc()).all()
    add_history(
        db,
        project_id=message.project_id,
        message_id=message.id,
        user=current_user,
        change_type=ChangeType.FIELD_UPDATE,
        before={"enum_values": before_history},
        after={"enum_values": [snapshot(value, ENUM_VALUE_FIELDS) for value in after_values], "version": message.version},
    )
    db.commit()
    return get_message_or_404(db, message_id)



@router.post("/messages/{message_id}/fields", response_model=FieldRead)
def create_field(message_id: int, payload: FieldCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = get_message_or_404(db, message_id)
    if (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper() != "STRUCT":
        raise HTTPException(status_code=422, detail="Enum 정의에는 필드를 추가할 수 없습니다.")
    data = normalize_field_data(db, message, payload.model_dump())
    ensure_unique_field_name(db, message_id, data["name"])
    if data.get("order_index") is None or data.get("order_index") == 0:
        data["order_index"] = next_field_order(db, message_id)
    current_refs = [row[0] for row in db.query(MessageField.ref_message_id).filter(MessageField.message_id == message_id, MessageField.ref_message_id.isnot(None)).all()]
    if data.get("type_kind") == "MESSAGE" and data.get("ref_message_id"):
        current_refs.append(data["ref_message_id"])
    ensure_no_message_reference_cycle(db, message.project_id, message.id, current_refs)
    field = MessageField(message_id=message_id, **data)
    db.add(field)
    message.version += 1
    db.flush()
    add_history(db, project_id=message.project_id, message_id=message.id, user=current_user, change_type=ChangeType.FIELD_CREATE, after=snapshot(field, FIELD_FIELDS))
    db.commit()
    db.refresh(field)
    return field


@router.patch("/fields/{field_id}", response_model=FieldRead)
def update_field(field_id: int, payload: FieldUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    field = db.get(MessageField, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    message = db.get(Message, field.message_id)
    if (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper() != "STRUCT":
        raise HTTPException(status_code=422, detail="Enum 정의에는 필드를 수정할 수 없습니다.")
    data = payload.model_dump(exclude_unset=True)
    before = snapshot(field, FIELD_FIELDS)
    changed = False
    full_data = field_state_from_obj(field)
    full_data.update(data)
    normalized = normalize_field_data(db, message, full_data)
    ensure_unique_field_name(db, field.message_id, normalized["name"], exclude_field_id=field.id)
    current_refs = []
    for other in db.query(MessageField).filter(MessageField.message_id == field.message_id, MessageField.id != field.id).all():
        if (getattr(other, "type_kind", "BASIC") or "BASIC").upper() == "MESSAGE" and other.ref_message_id:
            current_refs.append(other.ref_message_id)
    if normalized.get("type_kind") == "MESSAGE" and normalized.get("ref_message_id"):
        current_refs.append(normalized["ref_message_id"])
    ensure_no_message_reference_cycle(db, message.project_id, message.id, current_refs)
    for key, value in normalized.items():
        if getattr(field, key) != value:
            setattr(field, key, value)
            changed = True
    if changed:
        message.version += 1
        db.flush()
        add_history(db, project_id=message.project_id, message_id=message.id, user=current_user, change_type=ChangeType.FIELD_UPDATE, before=before, after=snapshot(field, FIELD_FIELDS))
    db.commit()
    db.refresh(field)
    return field


@router.post("/messages/{message_id}/fields/reorder", response_model=list[FieldRead])
def reorder_fields(message_id: int, payload: FieldReorder, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = get_message_or_404(db, message_id)
    if (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper() != "STRUCT":
        raise HTTPException(status_code=422, detail="Enum 정의에는 필드 순서를 변경할 수 없습니다.")
    fields = db.query(MessageField).filter(MessageField.message_id == message_id).all()
    field_by_id = {field.id: field for field in fields}
    if set(field_by_id.keys()) != set(payload.field_ids):
        raise HTTPException(status_code=400, detail="field_ids must include every field in this message exactly once")
    before = [snapshot(field_by_id[field_id], FIELD_FIELDS) for field_id in payload.field_ids]
    for index, field_id in enumerate(payload.field_ids, start=1):
        field_by_id[field_id].order_index = index
    message.version += 1
    db.flush()
    after = [snapshot(field_by_id[field_id], FIELD_FIELDS) for field_id in payload.field_ids]
    add_history(db, project_id=message.project_id, message_id=message.id, user=current_user, change_type=ChangeType.FIELD_UPDATE, before=before, after={"reordered_fields": after})
    db.commit()
    return db.query(MessageField).filter(MessageField.message_id == message_id).order_by(MessageField.order_index.asc(), MessageField.id.asc()).all()


@router.delete("/fields/{field_id}")
def delete_field(field_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    field = db.get(MessageField, field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Field not found")
    message = db.get(Message, field.message_id)
    before = snapshot(field, FIELD_FIELDS)
    db.delete(field)
    message.version += 1
    add_history(db, project_id=message.project_id, message_id=message.id, user=current_user, change_type=ChangeType.FIELD_DELETE, before=before)
    db.commit()
    return {"ok": True}
