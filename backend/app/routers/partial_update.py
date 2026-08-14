from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user
from ..database import get_db
from ..protocols import normalize_protocol_string, split_protocols
from ..models import (
    ChangeType,
    IntegrationTarget,
    Message,
    MessageChangeHistory,
    MessageEnumValue,
    MessageField,
    MessageRxTargetItem,
    MessageTxTargetItem,
    Project,
    User,
)
from .project_json import _load_project_json, _validate_import_payload, _dimensions_to_first_size

router = APIRouter(tags=["partial-update"])

MESSAGE_COMPARE_FIELDS = [
    ("name", "메시지 용도"),
    ("definition_type", "정의 유형"),
    ("period", "주기"),
    ("description", "설명"),
    ("infocode", "정보코드"),
    ("enum_underlying_type", "Enum 기본 자료형"),
]
FIELD_COMPARE_FIELDS = [
    ("type_kind", "자료형 종류"),
    ("data_type", "자료형"),
    ("ref_message", "참조 자료형"),
    ("array_dimensions", "배열"),
    ("purpose", "필드 용도"),
    ("description", "설명"),
    ("value_range", "허용 값 범위"),
    ("unit", "단위"),
    ("note", "비고"),
    ("order", "순서"),
]
ENUM_COMPARE_FIELDS = [
    ("value", "값"),
    ("description", "설명"),
    ("order", "순서"),
]


def _display(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _normalize_target_names(values: list[str] | None) -> list[str]:
    seen: dict[str, str] = {}
    for value in values or []:
        text = str(value or "").strip()
        if text and text.lower() not in seen:
            seen[text.lower()] = text
    return sorted(seen.values(), key=lambda item: item.lower())


def _field_from_obj(field: MessageField) -> dict[str, Any]:
    type_kind = str(field.type_kind or "BASIC").upper()
    ref_name = ""
    if type_kind in {"MESSAGE", "ENUM"} and field.ref_message is not None:
        ref_name = field.ref_message.struct_name or field.ref_message.name
    return {
        "name": field.name,
        "variable_name": field.name,
        "type_kind": type_kind,
        "data_type": ref_name or field.type,
        "ref_message": ref_name,
        "array_dimensions": field.array_dimensions or None,
        "description": field.description or "",
        "purpose": field.purpose or "",
        "value_range": field.value_range or "",
        "unit": field.unit or "",
        "note": field.note or "",
        "order": int(field.order_index or 0),
    }


def _enum_from_obj(value: MessageEnumValue) -> dict[str, Any]:
    return {
        "name": value.name,
        "value": value.value,
        "description": value.description or "",
        "order": int(value.order_index or 0),
    }


def _message_from_obj(message: Message) -> dict[str, Any]:
    return {
        "name": message.name,
        "struct_name": message.struct_name or message.name,
        "definition_type": str(message.definition_type or "STRUCT").upper(),
        "period": message.period or "비주기",
        "description": message.description or "",
        "infocode": message.infocode or None,
        "protocol": normalize_protocol_string(message.protocol),
        "enum_underlying_type": message.enum_underlying_type or "uint32",
        "version": int(message.version or 1),
        "order": int(message.order_index or 0),
        "fields": [_field_from_obj(field) for field in sorted(message.fields or [], key=lambda item: ((item.order_index or 0), item.id or 0))],
        "enum_values": [_enum_from_obj(value) for value in sorted(message.enum_values or [], key=lambda item: ((item.order_index or 0), item.id or 0))],
        "tx_targets": _normalize_target_names([target.name for target in (message.tx_targets or [])]),
        "rx_targets": _normalize_target_names([target.name for target in (message.rx_targets or [])]),
        "labels": sorted([label.name for label in (message.labels or [])], key=lambda item: item.lower()),
    }


def _add_diff(diffs: list[dict[str, str]], kind: str, section: str, text: str) -> None:
    diffs.append({"kind": kind, "section": section, "text": text})


def _compare_named_collection(
    diffs: list[dict[str, str]],
    section: str,
    item_label: str,
    before_items: list[dict[str, Any]],
    after_items: list[dict[str, Any]],
    compare_fields: list[tuple[str, str]],
) -> None:
    before_map = {str(item.get("name") or "").lower(): item for item in before_items}
    after_map = {str(item.get("name") or "").lower(): item for item in after_items}

    for key, item in after_map.items():
        if key not in before_map:
            detail = ""
            if item_label == "필드":
                detail = f" / {_display(item.get('data_type'))}{('[' + str(item.get('array_dimensions')) + ']') if item.get('array_dimensions') else ''}"
            elif item_label == "Enum 값":
                detail = f" = {_display(item.get('value'))}"
            _add_diff(diffs, "ADD", section, f"{item_label} 추가: {item.get('name')}{detail}")

    for key, item in before_map.items():
        if key not in after_map:
            detail = ""
            if item_label == "필드":
                detail = f" / {_display(item.get('data_type'))}{('[' + str(item.get('array_dimensions')) + ']') if item.get('array_dimensions') else ''}"
            elif item_label == "Enum 값":
                detail = f" = {_display(item.get('value'))}"
            _add_diff(diffs, "DELETE", section, f"{item_label} 삭제: {item.get('name')}{detail}")

    for key, after_item in after_map.items():
        before_item = before_map.get(key)
        if before_item is None:
            continue
        changes: list[str] = []
        for field_name, label in compare_fields:
            before_value = before_item.get(field_name)
            after_value = after_item.get(field_name)
            if (before_value or None) != (after_value or None):
                changes.append(f"{label} {_display(before_value)} → {_display(after_value)}")
        if changes:
            _add_diff(diffs, "CHANGE", section, f"{item_label} 수정: {after_item.get('name')} — " + ", ".join(changes))


def _compare_message(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> list[dict[str, str]]:
    diffs: list[dict[str, str]] = []
    if existing is None:
        _add_diff(diffs, "ADD", "메시지", f"신규 {('Enum' if incoming['definition_type'] == 'ENUM' else '메시지')}: {incoming['struct_name']} ({incoming['name']})")
        if incoming["definition_type"] == "STRUCT":
            for field in incoming.get("fields", []):
                _add_diff(diffs, "ADD", "필드", f"필드 추가: {field['name']} / {_display(field.get('data_type'))}{('[' + str(field.get('array_dimensions')) + ']') if field.get('array_dimensions') else ''}")
        else:
            for value in incoming.get("enum_values", []):
                _add_diff(diffs, "ADD", "Enum", f"Enum 값 추가: {value['name']} = {value['value']}")
        for target in _normalize_target_names(incoming.get("tx_targets")):
            _add_diff(diffs, "ADD", "송수신", f"송신 노드 추가: {target}")
        for target in _normalize_target_names(incoming.get("rx_targets")):
            _add_diff(diffs, "ADD", "송수신", f"수신 노드 추가: {target}")
        return diffs

    for field_name, label in MESSAGE_COMPARE_FIELDS:
        before_value = existing.get(field_name)
        after_value = incoming.get(field_name)
        if (before_value or None) != (after_value or None):
            _add_diff(diffs, "CHANGE", "메시지", f"{label}: {_display(before_value)} → {_display(after_value)}")

    before_protocols = {value.lower(): value for value in split_protocols(existing.get("protocol"))}
    after_protocols = {value.lower(): value for value in split_protocols(incoming.get("protocol"))}
    for key in sorted(after_protocols.keys() - before_protocols.keys()):
        _add_diff(diffs, "ADD", "프로토콜", f"프로토콜 추가: {after_protocols[key]}")
    for key in sorted(before_protocols.keys() - after_protocols.keys()):
        _add_diff(diffs, "DELETE", "프로토콜", f"프로토콜 삭제: {before_protocols[key]}")

    before_tx = {value.lower(): value for value in _normalize_target_names(existing.get("tx_targets"))}
    after_tx = {value.lower(): value for value in _normalize_target_names(incoming.get("tx_targets"))}
    before_rx = {value.lower(): value for value in _normalize_target_names(existing.get("rx_targets"))}
    after_rx = {value.lower(): value for value in _normalize_target_names(incoming.get("rx_targets"))}
    for key in sorted(after_tx.keys() - before_tx.keys()):
        _add_diff(diffs, "ADD", "송수신", f"송신 노드 추가: {after_tx[key]}")
    for key in sorted(before_tx.keys() - after_tx.keys()):
        _add_diff(diffs, "DELETE", "송수신", f"송신 노드 삭제: {before_tx[key]}")
    for key in sorted(after_rx.keys() - before_rx.keys()):
        _add_diff(diffs, "ADD", "송수신", f"수신 노드 추가: {after_rx[key]}")
    for key in sorted(before_rx.keys() - after_rx.keys()):
        _add_diff(diffs, "DELETE", "송수신", f"수신 노드 삭제: {before_rx[key]}")

    # Changing STRUCT <-> ENUM means the old collection disappears and the new one appears.
    if existing.get("definition_type") != incoming.get("definition_type"):
        if existing.get("definition_type") == "STRUCT":
            for field in existing.get("fields", []):
                _add_diff(diffs, "DELETE", "필드", f"필드 삭제: {field['name']} / {_display(field.get('data_type'))}")
        else:
            for value in existing.get("enum_values", []):
                _add_diff(diffs, "DELETE", "Enum", f"Enum 값 삭제: {value['name']} = {value['value']}")
        if incoming.get("definition_type") == "STRUCT":
            for field in incoming.get("fields", []):
                _add_diff(diffs, "ADD", "필드", f"필드 추가: {field['name']} / {_display(field.get('data_type'))}")
        else:
            for value in incoming.get("enum_values", []):
                _add_diff(diffs, "ADD", "Enum", f"Enum 값 추가: {value['name']} = {value['value']}")
    elif incoming.get("definition_type") == "STRUCT":
        _compare_named_collection(diffs, "필드", "필드", existing.get("fields", []), incoming.get("fields", []), FIELD_COMPARE_FIELDS)
    else:
        _compare_named_collection(diffs, "Enum", "Enum 값", existing.get("enum_values", []), incoming.get("enum_values", []), ENUM_COMPARE_FIELDS)

    return diffs


def _load_existing_messages(db: Session, project_id: int) -> list[Message]:
    return (
        db.query(Message)
        .options(
            joinedload(Message.fields).joinedload(MessageField.ref_message),
            joinedload(Message.enum_values),
            joinedload(Message.labels),
            joinedload(Message.tx_targets),
            joinedload(Message.rx_targets),
        )
        .filter(Message.project_id == project_id)
        .order_by(Message.order_index.asc(), Message.id.asc())
        .all()
    )


async def _read_partial_json(file: UploadFile) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=422, detail="JSON 파일만 사용할 수 있습니다.")
    try:
        raw = await file.read()
        payload = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        raise HTTPException(status_code=422, detail="JSON 파일을 읽을 수 없습니다.")
    data = _load_project_json(payload)
    messages, _groups, _labels, integration_targets = _validate_import_payload(data)
    return data, messages, integration_targets


def _preview_entries(db: Session, project_id: int, incoming_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_messages = _load_existing_messages(db, project_id)
    existing_by_name = {(message.struct_name or message.name).lower(): message for message in existing_messages}
    incoming_name_set = {message["struct_name"].lower() for message in incoming_messages}
    entries: list[dict[str, Any]] = []

    for incoming in sorted(incoming_messages, key=lambda item: item.get("order") or 0):
        existing_obj = existing_by_name.get(incoming["struct_name"].lower())
        existing = _message_from_obj(existing_obj) if existing_obj is not None else None
        diffs = _compare_message(existing, incoming)
        status = "NEW" if existing is None else ("CHANGED" if diffs else "SAME")
        dependencies: list[str] = []
        if incoming.get("definition_type") == "STRUCT":
            for field in incoming.get("fields", []):
                ref_name = str(field.get("ref_message") or "").strip()
                if not ref_name:
                    continue
                ref_key = ref_name.lower()
                if ref_key not in existing_by_name and ref_key in incoming_name_set:
                    dependencies.append(ref_name)
        entries.append({
            "struct_name": incoming["struct_name"],
            "name": incoming["name"],
            "definition_type": incoming["definition_type"],
            "existing_id": existing_obj.id if existing_obj is not None else None,
            "status": status,
            "diffs": diffs,
            "dependencies": sorted(set(dependencies), key=lambda item: item.lower()),
        })
    return entries


def _message_snapshot_for_history(message: Message) -> dict[str, Any]:
    data = _message_from_obj(message)
    data.pop("labels", None)
    return data


def _validate_selected_dependencies(
    selected_messages: list[dict[str, Any]],
    all_incoming: list[dict[str, Any]],
    existing_by_name: dict[str, Message],
) -> None:
    selected_keys = {message["struct_name"].lower() for message in selected_messages}
    incoming_by_name = {message["struct_name"].lower(): message for message in all_incoming}
    for message in selected_messages:
        if message.get("definition_type") != "STRUCT":
            continue
        for field in message.get("fields", []):
            ref_name = str(field.get("ref_message") or "").strip()
            if not ref_name:
                continue
            ref_key = ref_name.lower()
            if ref_key in existing_by_name:
                continue
            if ref_key in incoming_by_name and ref_key in selected_keys:
                continue
            raise HTTPException(
                status_code=409,
                detail=f"{message['struct_name']}.{field['name']}가 신규 자료형 {ref_name}을 참조합니다. {ref_name}도 함께 선택해 주세요.",
            )


def _validate_final_infocodes(
    existing_messages: list[Message],
    selected_messages: list[dict[str, Any]],
) -> None:
    selected_by_name = {message["struct_name"].lower(): message for message in selected_messages}
    used: dict[str, str] = {}
    final_rows: list[tuple[str, str | None]] = []
    for message in existing_messages:
        key = (message.struct_name or message.name).lower()
        incoming = selected_by_name.get(key)
        if incoming is not None:
            final_rows.append((incoming["struct_name"], incoming.get("infocode")))
        else:
            final_rows.append((message.struct_name or message.name, message.infocode))
    existing_keys = {(message.struct_name or message.name).lower() for message in existing_messages}
    for incoming in selected_messages:
        if incoming["struct_name"].lower() not in existing_keys:
            final_rows.append((incoming["struct_name"], incoming.get("infocode")))
    for name, code in final_rows:
        code_text = str(code or "").strip()
        if not code_text:
            continue
        if code_text in used:
            raise HTTPException(status_code=409, detail=f"부분 업데이트 후 정보코드 {code_text}가 중복됩니다: {used[code_text]}, {name}")
        used[code_text] = name


def _ensure_target(db: Session, project_id: int, name: str, descriptions: dict[str, str]) -> IntegrationTarget:
    target = db.query(IntegrationTarget).filter(IntegrationTarget.project_id == project_id, func.lower(IntegrationTarget.name) == name.lower()).first()
    if target is None:
        target = IntegrationTarget(project_id=project_id, name=name[:120], description=descriptions.get(name.lower(), ""))
        db.add(target)
        db.flush()
    return target


@router.post("/projects/{project_id}/partial-update/preview")
async def preview_partial_update(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _data, messages, _targets = await _read_partial_json(file)
    entries = _preview_entries(db, project_id, messages)
    return {
        "filename": file.filename,
        "summary": {
            "new": sum(1 for item in entries if item["status"] == "NEW"),
            "changed": sum(1 for item in entries if item["status"] == "CHANGED"),
            "same": sum(1 for item in entries if item["status"] == "SAME"),
        },
        "messages": entries,
    }


@router.post("/projects/{project_id}/partial-update/apply")
async def apply_partial_update(
    project_id: int,
    file: UploadFile = File(...),
    selected_names: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        selected_raw = json.loads(selected_names)
        if not isinstance(selected_raw, list):
            raise ValueError
        selected_keys = {str(value or "").strip().lower() for value in selected_raw if str(value or "").strip()}
    except Exception:
        raise HTTPException(status_code=422, detail="선택한 메시지 목록 형식이 올바르지 않습니다.")
    if not selected_keys:
        raise HTTPException(status_code=422, detail="업데이트할 메시지를 하나 이상 선택하세요.")

    _data, incoming_messages, integration_targets = await _read_partial_json(file)
    incoming_by_name = {message["struct_name"].lower(): message for message in incoming_messages}
    missing = sorted(selected_keys - incoming_by_name.keys())
    if missing:
        raise HTTPException(status_code=422, detail=f"가져온 JSON에 없는 메시지가 선택되었습니다: {', '.join(missing)}")
    selected_messages = [incoming_by_name[key] for key in incoming_by_name if key in selected_keys]

    existing_messages = _load_existing_messages(db, project_id)
    existing_by_name = {(message.struct_name or message.name).lower(): message for message in existing_messages}
    _validate_selected_dependencies(selected_messages, incoming_messages, existing_by_name)
    _validate_final_infocodes(existing_messages, selected_messages)

    # Capture the exact review diff before mutating the database. This same text is stored in history.
    preview_by_name = {entry["struct_name"].lower(): entry for entry in _preview_entries(db, project_id, incoming_messages)}
    actionable_selected = [message for message in selected_messages if preview_by_name[message["struct_name"].lower()]["status"] != "SAME"]
    if not actionable_selected:
        raise HTTPException(status_code=422, detail="선택한 항목에 실제 변경사항이 없습니다.")

    before_snapshots: list[dict[str, Any]] = []
    for incoming in actionable_selected:
        existing = existing_by_name.get(incoming["struct_name"].lower())
        if existing is not None:
            before_snapshots.append(_message_snapshot_for_history(existing))

    max_order = max([int(message.order_index or 0) for message in existing_messages] + [0])
    message_by_name = dict(existing_by_name)
    created_names: set[str] = set()

    # First pass: create missing definitions and update message-level metadata so references can resolve.
    for incoming in actionable_selected:
        key = incoming["struct_name"].lower()
        message = message_by_name.get(key)
        if message is None:
            max_order += 1
            message = Message(
                project_id=project_id,
                name=incoming["name"],
                struct_name=incoming["struct_name"],
                period=incoming["period"],
                description=incoming["description"],
                infocode=incoming.get("infocode"),
                protocol=incoming.get("protocol"),
                definition_type=incoming["definition_type"],
                enum_underlying_type=incoming["enum_underlying_type"],
                version=max(1, int(incoming.get("version") or 1)),
                order_index=max_order,
            )
            db.add(message)
            db.flush()
            message_by_name[key] = message
            created_names.add(key)
        else:
            message.name = incoming["name"]
            message.period = incoming["period"]
            message.description = incoming["description"]
            message.infocode = incoming.get("infocode")
            message.protocol = incoming.get("protocol")
            message.definition_type = incoming["definition_type"]
            message.enum_underlying_type = incoming["enum_underlying_type"]
        db.flush()

    target_descriptions = {str(item.get("name") or "").lower(): str(item.get("description") or "") for item in integration_targets}

    # Second pass: selected message content is authoritative. Tags/groups remain untouched.
    for incoming in actionable_selected:
        key = incoming["struct_name"].lower()
        message = message_by_name[key]
        preview = preview_by_name[key]
        structural_change = any(diff.get("section") in {"필드", "Enum"} for diff in preview.get("diffs", [])) or key in created_names

        if structural_change:
            db.query(MessageField).filter(MessageField.message_id == message.id).delete(synchronize_session=False)
            db.query(MessageEnumValue).filter(MessageEnumValue.message_id == message.id).delete(synchronize_session=False)
            db.flush()

            if incoming["definition_type"] == "STRUCT":
                for field_data in sorted(incoming.get("fields", []), key=lambda item: item["order"]):
                    ref_message = None
                    ref_message_id = None
                    if field_data["type_kind"] in {"MESSAGE", "ENUM"}:
                        ref_message = message_by_name.get(field_data["ref_message"].lower())
                        if ref_message is None:
                            raise HTTPException(status_code=409, detail=f"참조 자료형을 찾을 수 없습니다: {field_data['ref_message']}")
                        ref_message_id = ref_message.id
                    dimensions = field_data.get("array_dimensions")
                    db.add(MessageField(
                        message_id=message.id,
                        type=(ref_message.struct_name or ref_message.name) if ref_message is not None else field_data["data_type"],
                        type_kind=field_data["type_kind"],
                        ref_message_id=ref_message_id,
                        name=field_data["name"],
                        variable_name=field_data["name"],
                        description=field_data.get("description") or "",
                        purpose=field_data.get("purpose") or "",
                        value_range=field_data.get("value_range") or "",
                        unit=field_data.get("unit") or "",
                        note=field_data.get("note") or "",
                        is_array=bool(dimensions),
                        array_size=_dimensions_to_first_size(dimensions),
                        array_dimensions=dimensions,
                        order_index=field_data["order"],
                    ))
            else:
                for value_data in sorted(incoming.get("enum_values", []), key=lambda item: item["order"]):
                    db.add(MessageEnumValue(
                        message_id=message.id,
                        name=value_data["name"],
                        value=value_data["value"],
                        description=value_data.get("description") or "",
                        order_index=value_data["order"],
                    ))

        relation_change = key in created_names or any(diff.get("section") == "송수신" for diff in preview.get("diffs", []))
        if relation_change:
            db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id == message.id).delete(synchronize_session=False)
            db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id == message.id).delete(synchronize_session=False)
            for target_name in _normalize_target_names(incoming.get("tx_targets")):
                target = _ensure_target(db, project_id, target_name, target_descriptions)
                db.add(MessageTxTargetItem(message_id=message.id, target_id=target.id))
            for target_name in _normalize_target_names(incoming.get("rx_targets")):
                target = _ensure_target(db, project_id, target_name, target_descriptions)
                db.add(MessageRxTargetItem(message_id=message.id, target_id=target.id))

        if structural_change and key not in created_names:
            message.version = int(message.version or 1) + 1
        db.flush()

    # Resolve eager-loaded state again for history after snapshot.
    db.flush()
    db.expire_all()
    after_snapshots: list[dict[str, Any]] = []
    for incoming in actionable_selected:
        refreshed = (
            db.query(Message)
            .options(
                joinedload(Message.fields).joinedload(MessageField.ref_message),
                joinedload(Message.enum_values),
                joinedload(Message.labels),
                joinedload(Message.tx_targets),
                joinedload(Message.rx_targets),
            )
            .filter(Message.id == message_by_name[incoming["struct_name"].lower()].id)
            .first()
        )
        after_snapshots.append(_message_snapshot_for_history(refreshed))

    history_messages = []
    for incoming in actionable_selected:
        preview = preview_by_name[incoming["struct_name"].lower()]
        history_messages.append({
            "name": incoming["struct_name"],
            "purpose": incoming["name"],
            "status": preview["status"],
            "diffs": [diff["text"] for diff in preview.get("diffs", [])],
        })

    db.add(MessageChangeHistory(
        project_id=project_id,
        message_id=None,
        changed_by=current_user.id,
        change_type=ChangeType.UPDATE,
        before_json={
            "partial_update": {
                "filename": file.filename,
                "message_count": len(actionable_selected),
                "messages": before_snapshots,
            }
        },
        after_json={
            "partial_update": {
                "filename": file.filename,
                "message_count": len(actionable_selected),
                "messages": history_messages,
                "after_messages": after_snapshots,
            }
        },
    ))
    db.commit()

    return {
        "ok": True,
        "filename": file.filename,
        "updated_count": len(actionable_selected),
        "new_count": sum(1 for item in actionable_selected if preview_by_name[item["struct_name"].lower()]["status"] == "NEW"),
        "changed_count": sum(1 for item in actionable_selected if preview_by_name[item["struct_name"].lower()]["status"] == "CHANGED"),
        "message_names": [item["struct_name"] for item in actionable_selected],
    }
