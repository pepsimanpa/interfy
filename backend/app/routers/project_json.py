from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import Project, Message, MessageField, MessageEnumValue, MessageGroup, MessageGroupItem, MessageLabel, MessageLabelItem, MessageTxLabelItem, MessageRxLabelItem, IntegrationTarget, MessageTxTargetItem, MessageRxTargetItem, User
from ..schemas import SUPPORTED_TYPES, IDENTIFIER_PATTERN, ENUM_UNDERLYING_TYPES
from ..protocols import normalize_protocol_string, split_protocols

router = APIRouter(tags=["project-json"])

PROJECT_FORMAT = "interfy-project"
LEGACY_PROJECT_FORMATS = {"messageforge-project"}
PROJECT_FORMAT_VERSION = 1
TYPE_KINDS = {"BASIC", "MESSAGE", "ENUM"}
DEFINITION_TYPES = {"STRUCT", "ENUM"}
ACRONYM_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"


def _json_response(content: dict[str, Any], filename: str) -> Response:
    body = json.dumps(content, ensure_ascii=False, indent=2)
    safe_filename = quote(filename)
    return Response(
        body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"},
    )


def _safe_filename_part(value: str) -> str:
    value = (value or "interfy-project").strip() or "interfy-project"
    return value.replace("/", "_").replace("\\", "_")


def _normalize_array_dimensions(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "0":
        return None
    parts = [part.strip() for part in text.split(",")]
    if not parts or any(part == "" or not part.isdigit() or int(part) <= 0 for part in parts):
        raise ValueError("배열 크기는 빈칸, 0, 또는 10 / 3,4 형식이어야 합니다.")
    return ",".join(str(int(part)) for part in parts)


def _dimensions_to_first_size(dimensions: str | None) -> int | None:
    if not dimensions:
        return None
    try:
        return int(str(dimensions).split(",")[0])
    except Exception:
        return None


def _next_unique_value(db: Session, model, column_name: str, base_value: str, max_len: int, suffix: str = "_import") -> str:
    column = getattr(model, column_name)
    existing = {row[0].lower() for row in db.query(column).all() if row[0]}
    candidate = base_value[:max_len]
    if candidate.lower() not in existing:
        return candidate
    for index in range(1, 10000):
        postfix = suffix if index == 1 else f"{suffix}{index}"
        candidate = f"{base_value[: max_len - len(postfix)]}{postfix}"
        if candidate.lower() not in existing:
            return candidate
    raise HTTPException(status_code=409, detail="가져오기 프로젝트 이름을 생성할 수 없습니다.")


def _normalize_project_name(db: Session, value: Any) -> str:
    name = str(value or "Imported Project").strip()
    if not name:
        name = "Imported Project"
    return _next_unique_value(db, Project, "name", name, 120)


def _default_acronym(name: str) -> str:
    chars: list[str] = []
    for ch in name or "PROJECT":
        if ch.isascii() and ch.isalnum():
            chars.append(ch.upper())
        elif ch == "_":
            chars.append("_")
    value = "".join(chars).strip("_") or "PROJECT"
    if not value[0].isalpha():
        value = "P_" + value
    return value[:40]


def _normalize_project_acronym(db: Session, value: Any, fallback_name: str) -> str:
    acronym = str(value or "").strip()
    if not acronym:
        acronym = _default_acronym(fallback_name)
    acronym = re.sub(r"[^A-Za-z0-9_]", "_", acronym).strip("_") or _default_acronym(fallback_name)
    if not acronym[0].isalpha():
        acronym = "P_" + acronym
    acronym = acronym[:40]
    if not re.fullmatch(ACRONYM_PATTERN, acronym):
        raise HTTPException(status_code=422, detail="프로젝트 영문약어는 영문자로 시작하고 영문/숫자/_ 만 사용할 수 있습니다.")
    return _next_unique_value(db, Project, "acronym", acronym, 40)


def _field_to_json(field: MessageField) -> dict[str, Any]:
    type_kind = (field.type_kind or "BASIC").upper()
    data: dict[str, Any] = {
        "name": field.variable_name or field.name,
        "type_kind": type_kind,
        "data_type": (field.ref_message.struct_name or field.ref_message.name) if type_kind in {"MESSAGE", "ENUM"} and field.ref_message else field.type,
        "array_dimensions": field.array_dimensions or "",
        "description": field.description or "",
        "purpose": field.purpose or "",
        "value_range": field.value_range or "",
        "unit": field.unit or "",
        "note": field.note or "",
        "order": field.order_index or 0,
    }
    if type_kind in {"MESSAGE", "ENUM"} and field.ref_message:
        data["ref_message"] = field.ref_message.struct_name or field.ref_message.name
    return data


def _enum_value_to_json(value: MessageEnumValue) -> dict[str, Any]:
    return {
        "name": value.name,
        "value": value.value,
        "description": value.description or "",
        "order": value.order_index or 0,
    }


@router.get("/projects/{project_id}/export/json")
def export_project_json(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    messages = (
        db.query(Message)
        .options(joinedload(Message.fields).joinedload(MessageField.ref_message), joinedload(Message.enum_values), joinedload(Message.labels), joinedload(Message.tx_targets), joinedload(Message.rx_targets))
        .filter(Message.project_id == project_id)
        .order_by(Message.order_index.asc(), Message.id.asc())
        .all()
    )
    groups = (
        db.query(MessageGroup)
        .filter(MessageGroup.project_id == project_id)
        .order_by(MessageGroup.name.asc())
        .all()
    )
    labels = (
        db.query(MessageLabel)
        .filter(MessageLabel.project_id == project_id)
        .order_by(MessageLabel.name.asc(), MessageLabel.id.asc())
        .all()
    )
    integration_targets = (
        db.query(IntegrationTarget)
        .filter(IntegrationTarget.project_id == project_id)
        .order_by(IntegrationTarget.name.asc(), IntegrationTarget.id.asc())
        .all()
    )

    content = {
        "format": PROJECT_FORMAT,
        "version": PROJECT_FORMAT_VERSION,
        "exported_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "project": {
            "name": project.name,
            "acronym": project.acronym or "",
            "description": project.description or "",
        },
        "messages": [
            {
                "name": message.name,
                "struct_name": message.struct_name or message.name,
                "definition_type": getattr(message, "definition_type", "STRUCT") or "STRUCT",
                "period": message.period or "",
                "description": message.description or "",
                "infocode": getattr(message, "infocode", None) or "",
                "protocol": normalize_protocol_string(getattr(message, "protocol", None)) or "",
                "protocols": split_protocols(getattr(message, "protocol", None)),
                "enum_underlying_type": getattr(message, "enum_underlying_type", "uint32") or "uint32",
                "version": message.version or 1,
                "order": message.order_index or 0,
                "fields": [_field_to_json(field) for field in sorted(message.fields or [], key=lambda f: ((f.order_index or 0), (f.id or 0)))],
                "enum_values": [_enum_value_to_json(value) for value in sorted(message.enum_values or [], key=lambda v: ((v.order_index or 0), (v.id or 0)))],
                "labels": [label.name for label in sorted(message.labels or [], key=lambda label: (label.name.lower(), label.id or 0))],
                "tx_targets": [target.name for target in sorted(getattr(message, "tx_targets", []) or [], key=lambda target: (target.name.lower(), target.id or 0))],
                "rx_targets": [target.name for target in sorted(getattr(message, "rx_targets", []) or [], key=lambda target: (target.name.lower(), target.id or 0))],
            }
            for message in messages
        ],
        "groups": [
            {
                "name": group.name,
                "description": group.description or "",
                "messages": [(item.message.struct_name or item.message.name) for item in sorted(group.items or [], key=lambda item: ((getattr(item, "order_index", 0) or 0), item.id or 0)) if item.message is not None],
            }
            for group in groups
        ],
        "labels": [
            {
                "name": label.name,
                "description": label.description or "",
                "messages": [(item.message.struct_name or item.message.name) for item in sorted(label.items or [], key=lambda item: ((item.message.order_index if item.message else 0), item.id or 0)) if item.message is not None],
            }
            for label in labels
        ],
        "integration_targets": [
            {
                "name": target.name,
                "description": target.description or "",
            }
            for target in integration_targets
        ],
    }

    filename_base = project.acronym or project.name or "interfy-project"
    return _json_response(content, f"{_safe_filename_part(filename_base)}.json")


def _load_project_json(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="JSON 최상위 구조는 객체여야 합니다.")
    if data.get("format") not in ({PROJECT_FORMAT} | LEGACY_PROJECT_FORMATS):
        raise HTTPException(status_code=422, detail="Interfy 프로젝트 JSON 형식이 아닙니다.")
    if int(data.get("version") or 0) > PROJECT_FORMAT_VERSION:
        raise HTTPException(status_code=422, detail="지원하지 않는 Interfy JSON 버전입니다.")
    if not isinstance(data.get("project"), dict):
        raise HTTPException(status_code=422, detail="project 정보가 없습니다.")
    if not isinstance(data.get("messages", []), list):
        raise HTTPException(status_code=422, detail="messages는 배열이어야 합니다.")
    if not isinstance(data.get("groups", []), list):
        raise HTTPException(status_code=422, detail="groups는 배열이어야 합니다.")
    if not isinstance(data.get("labels", []), list):
        raise HTTPException(status_code=422, detail="labels는 배열이어야 합니다.")
    if not isinstance(data.get("integration_targets", []), list):
        raise HTTPException(status_code=422, detail="integration_targets는 배열이어야 합니다.")
    return data


def _validate_import_payload(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    messages = data.get("messages", []) or []
    groups = data.get("groups", []) or []
    labels = data.get("labels", []) or []
    integration_targets = data.get("integration_targets", []) or []
    seen_messages: set[str] = set()
    seen_infocodes: dict[str, str] = {}
    normalized_messages: list[dict[str, Any]] = []

    for message_index, raw_message in enumerate(messages, start=1):
        if not isinstance(raw_message, dict):
            raise HTTPException(status_code=422, detail=f"messages[{message_index}]는 객체여야 합니다.")
        name = str(raw_message.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail=f"메시지/Enum 이름이 비어 있습니다: {message_index}")
        struct_name = str(raw_message.get("struct_name") or raw_message.get("type_name") or name).strip()
        if not re.fullmatch(IDENTIFIER_PATTERN, struct_name):
            raise HTTPException(status_code=422, detail=f"메시지/Enum 이름 형식 오류: {struct_name or message_index}")
        key = struct_name.lower()
        if key in seen_messages:
            raise HTTPException(status_code=422, detail=f"중복 메시지/Enum 이름: {struct_name}")
        seen_messages.add(key)

        definition_type = str(raw_message.get("definition_type") or "STRUCT").strip().upper()
        if definition_type not in DEFINITION_TYPES:
            raise HTTPException(status_code=422, detail=f"{name}의 정의 유형은 STRUCT 또는 ENUM이어야 합니다.")
        enum_underlying_type = str(raw_message.get("enum_underlying_type") or "uint32").strip()
        if enum_underlying_type not in ENUM_UNDERLYING_TYPES:
            raise HTTPException(status_code=422, detail=f"{name}의 Enum 기본 자료형이 지원되지 않습니다: {enum_underlying_type}")

        period = str(raw_message.get("period", raw_message.get("cycle_ms", "")) or "").strip()
        if definition_type == "ENUM":
            period = "비주기"
        elif period in {"", "0", "비주기"}:
            period = "비주기"
        elif not period.isdigit():
            raise HTTPException(status_code=422, detail=f"메시지 {name}의 주기는 숫자만 가능합니다.")

        infocode = str(raw_message.get("infocode") or "").strip()
        if infocode and not infocode.isdigit():
            raise HTTPException(status_code=422, detail=f"메시지 {name}의 정보코드는 숫자만 가능합니다.")
        if definition_type == "ENUM":
            infocode = ""
        if infocode:
            if infocode in seen_infocodes:
                raise HTTPException(status_code=422, detail=f"중복 정보코드: {infocode} / {seen_infocodes[infocode]}, {name}")
            seen_infocodes[infocode] = name

        fields = raw_message.get("fields", []) or []
        enum_values = raw_message.get("enum_values", []) or []
        if not isinstance(fields, list):
            raise HTTPException(status_code=422, detail=f"{name}의 fields는 배열이어야 합니다.")
        if not isinstance(enum_values, list):
            raise HTTPException(status_code=422, detail=f"{name}의 enum_values는 배열이어야 합니다.")

        normalized_fields: list[dict[str, Any]] = []
        normalized_enum_values: list[dict[str, Any]] = []

        if definition_type == "ENUM":
            seen_value_names: set[str] = set()
            seen_numbers: set[int] = set()
            for value_index, raw_value in enumerate(enum_values, start=1):
                if not isinstance(raw_value, dict):
                    raise HTTPException(status_code=422, detail=f"Enum {name}의 enum_values[{value_index}]는 객체여야 합니다.")
                value_name = str(raw_value.get("name") or "").strip()
                if not re.fullmatch(IDENTIFIER_PATTERN, value_name):
                    raise HTTPException(status_code=422, detail=f"Enum 값 이름 형식 오류: {name}.{value_name or value_index}")
                value_key = value_name.lower()
                if value_key in seen_value_names:
                    raise HTTPException(status_code=422, detail=f"중복 Enum 값 이름: {name}.{value_name}")
                seen_value_names.add(value_key)
                try:
                    number = int(raw_value.get("value"))
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Enum 값은 정수여야 합니다: {name}.{value_name}")
                if number in seen_numbers:
                    raise HTTPException(status_code=422, detail=f"중복 Enum 숫자 값: {name}.{number}")
                seen_numbers.add(number)
                normalized_enum_values.append({
                    "name": value_name,
                    "value": number,
                    "description": str(raw_value.get("description") or ""),
                    "order": int(raw_value.get("order") or value_index),
                })
        else:
            seen_fields: set[str] = set()
            for field_index, raw_field in enumerate(fields, start=1):
                if not isinstance(raw_field, dict):
                    raise HTTPException(status_code=422, detail=f"메시지 {name}의 fields[{field_index}]는 객체여야 합니다.")
                legacy_display_name = str(raw_field.get("name") or "").strip()
                field_name = str(raw_field.get("variable_name") or raw_field.get("member_name") or legacy_display_name).strip()
                if not field_name:
                    raise HTTPException(status_code=422, detail=f"필드 이름이 비어 있습니다: {name}.{field_index}")
                if not re.fullmatch(IDENTIFIER_PATTERN, field_name):
                    raise HTTPException(status_code=422, detail=f"필드 이름 형식 오류: {name}.{field_name or field_index}")
                field_key = field_name.lower()
                if field_key in seen_fields:
                    raise HTTPException(status_code=422, detail=f"중복 필드 이름: {name}.{field_name}")
                seen_fields.add(field_key)
                type_kind = str(raw_field.get("type_kind") or "BASIC").strip().upper()
                if type_kind not in TYPE_KINDS:
                    raise HTTPException(status_code=422, detail=f"{name}.{field_name}의 자료형 종류는 BASIC, MESSAGE 또는 ENUM만 가능합니다.")
                data_type = str(raw_field.get("data_type", raw_field.get("type", "")) or "").strip()
                ref_message = str(raw_field.get("ref_message", raw_field.get("ref_message_name", "")) or "").strip()
                if type_kind == "BASIC":
                    if data_type not in SUPPORTED_TYPES:
                        raise HTTPException(status_code=422, detail=f"지원하지 않는 자료형: {name}.{field_name} / {data_type}")
                    ref_message = ""
                else:
                    ref_message = ref_message or data_type
                    if not ref_message:
                        raise HTTPException(status_code=422, detail=f"자료형 참조가 없습니다: {name}.{field_name}")
                    if ref_message.lower() == struct_name.lower():
                        raise HTTPException(status_code=422, detail=f"자기 자신은 자료형으로 사용할 수 없습니다: {name}.{field_name}")
                    matching = next((m for m in messages if str(m.get("struct_name") or m.get("type_name") or m.get("name") or "").strip().lower() == ref_message.lower()), None)
                    if not matching:
                        raise HTTPException(status_code=422, detail=f"존재하지 않는 자료형 참조: {name}.{field_name} → {ref_message}")
                    matching_type = str(matching.get("definition_type") or "STRUCT").strip().upper()
                    if type_kind == "MESSAGE" and matching_type != "STRUCT":
                        raise HTTPException(status_code=422, detail=f"메시지 자료형에는 메시지만 사용할 수 있습니다: {name}.{field_name}")
                    if type_kind == "ENUM" and matching_type != "ENUM":
                        raise HTTPException(status_code=422, detail=f"Enum 자료형에는 Enum만 사용할 수 있습니다: {name}.{field_name}")
                    data_type = ref_message
                try:
                    array_dimensions = _normalize_array_dimensions(raw_field.get("array_dimensions", raw_field.get("array_size", "")))
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=f"{name}.{field_name}: {exc}")
                purpose = str(raw_field.get("purpose") or "").strip()
                if legacy_display_name and legacy_display_name != field_name:
                    if not purpose:
                        purpose = legacy_display_name
                    elif legacy_display_name.lower() not in purpose.lower():
                        purpose = f"{legacy_display_name} - {purpose}"
                normalized_fields.append({
                    "name": field_name,
                    "variable_name": field_name,
                    "type_kind": type_kind,
                    "data_type": data_type,
                    "ref_message": ref_message,
                    "array_dimensions": array_dimensions,
                    "description": str(raw_field.get("description") or ""),
                    "purpose": purpose,
                    "value_range": str(raw_field.get("value_range") or ""),
                    "unit": str(raw_field.get("unit") or ""),
                    "note": str(raw_field.get("note") or ""),
                    "order": int(raw_field.get("order") or field_index),
                })

        normalized_messages.append({
            "name": name,
            "struct_name": struct_name,
            "definition_type": definition_type,
            "period": period,
            "description": str(raw_message.get("description") or ""),
            "infocode": infocode or None,
            "protocol": normalize_protocol_string(raw_message.get("protocols") if "protocols" in raw_message else raw_message.get("protocol")),
            "enum_underlying_type": enum_underlying_type,
            "version": max(1, int(raw_message.get("version") or 1)),
            "order": int(raw_message.get("order") or message_index),
            "fields": normalized_fields,
            "enum_values": normalized_enum_values,
            "labels": [str(label_name or "").strip() for label_name in (raw_message.get("labels", []) or []) if str(label_name or "").strip()],
            "tx_targets": [str(target_name or "").strip() for target_name in (raw_message.get("tx_targets", raw_message.get("tx_labels", [])) or []) if str(target_name or "").strip()],
            "rx_targets": [str(target_name or "").strip() for target_name in (raw_message.get("rx_targets", raw_message.get("rx_labels", [])) or []) if str(target_name or "").strip()],
        })

    message_names = {message["struct_name"].lower() for message in normalized_messages}
    canonical = {message["struct_name"].lower(): message["struct_name"] for message in normalized_messages}
    definition_by_name = {message["struct_name"].lower(): message["definition_type"] for message in normalized_messages}

    edges = {message["struct_name"].lower(): [] for message in normalized_messages if message["definition_type"] == "STRUCT"}
    for message in normalized_messages:
        if message["definition_type"] != "STRUCT":
            continue
        for field in message["fields"]:
            if field["type_kind"] == "MESSAGE":
                ref_key = field["ref_message"].lower()
                if ref_key not in message_names or definition_by_name.get(ref_key) != "STRUCT":
                    raise HTTPException(status_code=422, detail=f"존재하지 않는 메시지 자료형 참조: {message['name']}.{field['name']} → {field['ref_message']}")
                edges[message["struct_name"].lower()].append(ref_key)
            elif field["type_kind"] == "ENUM":
                ref_key = field["ref_message"].lower()
                if ref_key not in message_names or definition_by_name.get(ref_key) != "ENUM":
                    raise HTTPException(status_code=422, detail=f"존재하지 않는 Enum 자료형 참조: {message['name']}.{field['name']} → {field['ref_message']}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle = " → ".join(canonical.get(item, item) for item in stack + [node])
            raise HTTPException(status_code=422, detail=f"메시지 자료형 순환 참조가 있습니다: {cycle}")
        visiting.add(node)
        for nxt in edges.get(node, []):
            visit(nxt, stack + [node])
        visiting.remove(node)
        visited.add(node)

    for node in list(edges.keys()):
        visit(node, [])

    normalized_groups: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for group_index, raw_group in enumerate(groups, start=1):
        if not isinstance(raw_group, dict):
            raise HTTPException(status_code=422, detail=f"groups[{group_index}]는 객체여야 합니다.")
        group_name = str(raw_group.get("name") or "").strip()
        if not group_name:
            raise HTTPException(status_code=422, detail=f"그룹 이름이 비어 있습니다: groups[{group_index}]")
        group_key = group_name.lower()
        if group_key in seen_groups:
            raise HTTPException(status_code=422, detail=f"중복 그룹 이름: {group_name}")
        seen_groups.add(group_key)
        group_messages = raw_group.get("messages", []) or []
        if not isinstance(group_messages, list):
            raise HTTPException(status_code=422, detail=f"그룹 {group_name}의 messages는 배열이어야 합니다.")
        normalized_group_messages: list[str] = []
        for raw_name in group_messages:
            msg_name = str(raw_name or "").strip()
            if msg_name.lower() not in message_names:
                raise HTTPException(status_code=422, detail=f"그룹 {group_name}에 존재하지 않는 정의가 포함되어 있습니다: {msg_name}")
            normalized_group_messages.append(canonical[msg_name.lower()])
        normalized_groups.append({
            "name": group_name[:120],
            "description": str(raw_group.get("description") or ""),
            "messages": normalized_group_messages,
        })

    normalized_labels: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for label_index, raw_label in enumerate(labels, start=1):
        if not isinstance(raw_label, dict):
            raise HTTPException(status_code=422, detail=f"labels[{label_index}]는 객체여야 합니다.")
        label_name = str(raw_label.get("name") or "").strip()
        if not label_name:
            raise HTTPException(status_code=422, detail=f"라벨 이름이 비어 있습니다: labels[{label_index}]")
        key = label_name.lower()
        if key in seen_labels:
            raise HTTPException(status_code=422, detail=f"중복 라벨 이름: {label_name}")
        seen_labels.add(key)
        label_messages = raw_label.get("messages", []) or []
        if not isinstance(label_messages, list):
            raise HTTPException(status_code=422, detail=f"라벨 {label_name}의 messages는 배열이어야 합니다.")
        normalized_label_messages: list[str] = []
        for raw_name in label_messages:
            msg_name = str(raw_name or "").strip()
            if msg_name.lower() not in message_names:
                raise HTTPException(status_code=422, detail=f"라벨 {label_name}에 존재하지 않는 정의가 포함되어 있습니다: {msg_name}")
            normalized_label_messages.append(canonical[msg_name.lower()])
        normalized_labels.append({
            "name": label_name[:120],
            "description": str(raw_label.get("description") or ""),
            "messages": normalized_label_messages,
        })

    # Backward compatibility: message-level labels are also accepted.
    existing_label_keys = {label["name"].lower(): label for label in normalized_labels}
    for message in normalized_messages:
        for label_name in message.get("labels", []):
            key = label_name.lower()
            if key not in existing_label_keys:
                label = {"name": label_name[:120], "description": "", "messages": []}
                normalized_labels.append(label)
                existing_label_keys[key] = label
            if message["struct_name"] not in existing_label_keys[key]["messages"]:
                existing_label_keys[key]["messages"].append(message["struct_name"])

    normalized_targets: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for target_index, raw_target in enumerate(integration_targets, start=1):
        if not isinstance(raw_target, dict):
            raise HTTPException(status_code=422, detail=f"integration_targets[{target_index}]는 객체여야 합니다.")
        target_name = str(raw_target.get("name") or "").strip()
        if not target_name:
            raise HTTPException(status_code=422, detail=f"노드 이름이 비어 있습니다: integration_targets[{target_index}]")
        key = target_name.lower()
        if key in seen_targets:
            raise HTTPException(status_code=422, detail=f"중복 노드 이름: {target_name}")
        seen_targets.add(key)
        normalized_targets.append({"name": target_name[:120], "description": str(raw_target.get("description") or "")})

    existing_target_keys = {target["name"].lower(): target for target in normalized_targets}
    for message in normalized_messages:
        for target_name in (message.get("tx_targets", []) or []) + (message.get("rx_targets", []) or []):
            key = target_name.lower()
            if key not in existing_target_keys:
                target = {"name": target_name[:120], "description": ""}
                normalized_targets.append(target)
                existing_target_keys[key] = target

    return normalized_messages, normalized_groups, normalized_labels, normalized_targets


@router.post("/projects/import/json")
async def import_project_json(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    if not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=422, detail="JSON 파일만 가져올 수 있습니다.")
    try:
        raw = await file.read()
        payload = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        raise HTTPException(status_code=422, detail="JSON 파일을 읽을 수 없습니다.")

    data = _load_project_json(payload)
    messages, groups, labels, integration_targets = _validate_import_payload(data)
    raw_project = data["project"]
    project_name = _normalize_project_name(db, raw_project.get("name"))
    project_acronym = _normalize_project_acronym(db, raw_project.get("acronym"), project_name)

    project = Project(
        name=project_name,
        acronym=project_acronym,
        description=str(raw_project.get("description") or ""),
        owner_id=current_user.id,
    )
    db.add(project)
    db.flush()

    message_by_name: dict[str, Message] = {}
    for message_data in sorted(messages, key=lambda item: item["order"]):
        message = Message(
            project_id=project.id,
            name=message_data["name"],
            struct_name=message_data["struct_name"],
            period=message_data["period"],
            description=message_data["description"],
            infocode=message_data.get("infocode"),
            protocol=message_data.get("protocol"),
            definition_type=message_data["definition_type"],
            enum_underlying_type=message_data["enum_underlying_type"],
            version=message_data["version"],
            order_index=message_data["order"],
        )
        db.add(message)
        db.flush()
        message_by_name[(message.struct_name or message.name).lower()] = message

    for message_data in sorted(messages, key=lambda item: item["order"]):
        if message_data["definition_type"] != "ENUM":
            continue
        message = message_by_name[message_data["struct_name"].lower()]
        for value_data in sorted(message_data["enum_values"], key=lambda item: item["order"]):
            db.add(MessageEnumValue(
                message_id=message.id,
                name=value_data["name"],
                value=value_data["value"],
                description=value_data["description"],
                order_index=value_data["order"],
            ))

    for message_data in sorted(messages, key=lambda item: item["order"]):
        if message_data["definition_type"] != "STRUCT":
            continue
        message = message_by_name[message_data["struct_name"].lower()]
        for field_data in sorted(message_data["fields"], key=lambda item: item["order"]):
            ref_message = None
            ref_message_id = None
            if field_data["type_kind"] in {"MESSAGE", "ENUM"}:
                ref_message = message_by_name[field_data["ref_message"].lower()]
                ref_message_id = ref_message.id
            dimensions = field_data["array_dimensions"]
            db.add(MessageField(
                message_id=message.id,
                type=(ref_message.struct_name or ref_message.name) if ref_message is not None else field_data["data_type"],
                type_kind=field_data["type_kind"],
                ref_message_id=ref_message_id,
                name=field_data["name"],
                variable_name=field_data["variable_name"],
                description=field_data["description"],
                purpose=field_data.get("purpose") or "",
                value_range=field_data.get("value_range") or "",
                unit=field_data.get("unit") or "",
                note=field_data.get("note") or "",
                is_array=bool(dimensions),
                array_size=_dimensions_to_first_size(dimensions),
                array_dimensions=dimensions,
                order_index=field_data["order"],
            ))

    for group_data in groups:
        group = MessageGroup(project_id=project.id, name=group_data["name"], description=group_data["description"])
        db.add(group)
        db.flush()
        for order_index, message_name in enumerate(group_data["messages"], start=1):
            db.add(MessageGroupItem(group_id=group.id, message_id=message_by_name[message_name.lower()].id, order_index=order_index))

    label_by_name: dict[str, MessageLabel] = {}
    for label_data in labels:
        label = MessageLabel(project_id=project.id, name=label_data["name"], description=label_data["description"])
        db.add(label)
        db.flush()
        label_by_name[label.name.lower()] = label
        for message_name in label_data["messages"]:
            db.add(MessageLabelItem(label_id=label.id, message_id=message_by_name[message_name.lower()].id))

    target_by_name: dict[str, IntegrationTarget] = {}
    for target_data in integration_targets:
        target = IntegrationTarget(project_id=project.id, name=target_data["name"], description=target_data["description"])
        db.add(target)
        db.flush()
        target_by_name[target.name.lower()] = target

    for message_data in messages:
        message = message_by_name[message_data["struct_name"].lower()]
        for target_name in message_data.get("tx_targets", []) or []:
            target = target_by_name.get(target_name.lower())
            if target is not None:
                db.add(MessageTxTargetItem(target_id=target.id, message_id=message.id))
        for target_name in message_data.get("rx_targets", []) or []:
            target = target_by_name.get(target_name.lower())
            if target is not None:
                db.add(MessageRxTargetItem(target_id=target.id, message_id=message.id))

    db.commit()
    db.refresh(project)
    return {
        "id": project.id,
        "name": project.name,
        "acronym": project.acronym,
        "description": project.description or "",
        "owner_id": project.owner_id,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }
