from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user
from ..database import get_db
from ..models import (
    ChangeType,
    IntegrationTarget,
    Message,
    MessageChangeHistory,
    MessageEnumValue,
    MessageField,
    MessageGroupItem,
    MessageLabelItem,
    MessageRxTargetItem,
    MessageTxTargetItem,
    Project,
    User,
)
from ..protocols import normalize_protocol_string

router = APIRouter(tags=["merge-tools"])


class MergeRequest(BaseModel):
    target_id: int
    source_ids: list[int]


def _unique_ids(values: list[int] | None) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values or []:
        item = int(value)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _validate_merge_ids(target_id: int, source_ids: list[int]) -> tuple[int, list[int]]:
    target_id = int(target_id)
    sources = [item for item in _unique_ids(source_ids) if item != target_id]
    if not sources:
        raise HTTPException(status_code=422, detail="대표 항목 외에 머지할 항목을 하나 이상 선택하세요.")
    return target_id, sources


def _message_name(message: Message) -> str:
    return message.struct_name or message.name


def _target_rows(db: Session, project_id: int, target_id: int, source_ids: list[int]) -> tuple[IntegrationTarget, list[IntegrationTarget]]:
    target_id, source_ids = _validate_merge_ids(target_id, source_ids)
    ids = [target_id, *source_ids]
    rows = db.query(IntegrationTarget).filter(
        IntegrationTarget.project_id == project_id,
        IntegrationTarget.id.in_(ids),
    ).all()
    by_id = {row.id: row for row in rows}
    if target_id not in by_id:
        raise HTTPException(status_code=404, detail="대표 노드를 찾을 수 없습니다.")
    missing = [item for item in source_ids if item not in by_id]
    if missing:
        raise HTTPException(status_code=422, detail="같은 프로젝트에 없는 노드가 포함되어 있습니다.")
    return by_id[target_id], [by_id[item] for item in source_ids]


def _target_merge_preview(db: Session, project_id: int, target_id: int, source_ids: list[int]) -> dict[str, Any]:
    target, sources = _target_rows(db, project_id, target_id, source_ids)
    source_id_set = {row.id for row in sources}

    tx_rows = db.query(MessageTxTargetItem).filter(MessageTxTargetItem.target_id.in_(source_id_set)).all()
    rx_rows = db.query(MessageRxTargetItem).filter(MessageRxTargetItem.target_id.in_(source_id_set)).all()
    target_tx_message_ids = {
        row.message_id
        for row in db.query(MessageTxTargetItem).filter(MessageTxTargetItem.target_id == target.id).all()
    }
    target_rx_message_ids = {
        row.message_id
        for row in db.query(MessageRxTargetItem).filter(MessageRxTargetItem.target_id == target.id).all()
    }

    tx_move = 0
    rx_move = 0
    duplicate_links = 0
    affected_ids: set[int] = set()

    seen_tx = set(target_tx_message_ids)
    for row in tx_rows:
        affected_ids.add(row.message_id)
        if row.message_id in seen_tx:
            duplicate_links += 1
        else:
            tx_move += 1
            seen_tx.add(row.message_id)

    seen_rx = set(target_rx_message_ids)
    for row in rx_rows:
        affected_ids.add(row.message_id)
        if row.message_id in seen_rx:
            duplicate_links += 1
        else:
            rx_move += 1
            seen_rx.add(row.message_id)

    messages = []
    if affected_ids:
        for message in db.query(Message).filter(Message.id.in_(affected_ids)).order_by(Message.order_index.asc(), Message.id.asc()).all():
            messages.append({
                "id": message.id,
                "struct_name": _message_name(message),
                "name": message.name,
            })

    return {
        "kind": "TARGET",
        "target": {"id": target.id, "name": target.name, "description": target.description or ""},
        "sources": [{"id": row.id, "name": row.name, "description": row.description or ""} for row in sources],
        "summary": {
            "source_count": len(sources),
            "affected_message_count": len(messages),
            "tx_move_count": tx_move,
            "rx_move_count": rx_move,
            "duplicate_link_count": duplicate_links,
        },
        "affected_messages": messages,
        "blockers": [],
    }


@router.post("/projects/{project_id}/merge/targets/preview")
def preview_target_merge(
    project_id: int,
    payload: MergeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _target_merge_preview(db, project_id, payload.target_id, payload.source_ids)


@router.post("/projects/{project_id}/merge/targets/apply")
def apply_target_merge(
    project_id: int,
    payload: MergeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    preview = _target_merge_preview(db, project_id, payload.target_id, payload.source_ids)
    target, sources = _target_rows(db, project_id, payload.target_id, payload.source_ids)

    moved_tx = 0
    moved_rx = 0
    removed_duplicates = 0

    for source in sources:
        tx_items = db.query(MessageTxTargetItem).filter(MessageTxTargetItem.target_id == source.id).all()
        for item in tx_items:
            exists = db.query(MessageTxTargetItem).filter(
                MessageTxTargetItem.target_id == target.id,
                MessageTxTargetItem.message_id == item.message_id,
            ).first()
            if exists is not None:
                db.delete(item)
                removed_duplicates += 1
            else:
                item.target_id = target.id
                moved_tx += 1

        rx_items = db.query(MessageRxTargetItem).filter(MessageRxTargetItem.target_id == source.id).all()
        for item in rx_items:
            exists = db.query(MessageRxTargetItem).filter(
                MessageRxTargetItem.target_id == target.id,
                MessageRxTargetItem.message_id == item.message_id,
            ).first()
            if exists is not None:
                db.delete(item)
                removed_duplicates += 1
            else:
                item.target_id = target.id
                moved_rx += 1

        db.flush()
        db.delete(source)

    db.flush()
    db.add(MessageChangeHistory(
        project_id=project_id,
        message_id=None,
        changed_by=current_user.id,
        change_type=ChangeType.UPDATE,
        before_json={
            "target_merge": {
                "target": preview["target"],
                "sources": preview["sources"],
            }
        },
        after_json={
            "target_merge": {
                "target": preview["target"],
                "summary": {
                    "moved_tx": moved_tx,
                    "moved_rx": moved_rx,
                    "removed_duplicate_links": removed_duplicates,
                    "removed_source_count": len(sources),
                },
                "affected_messages": preview["affected_messages"],
            }
        },
    ))
    db.commit()

    return {
        "ok": True,
        "target": preview["target"],
        "removed_source_count": len(sources),
        "moved_tx": moved_tx,
        "moved_rx": moved_rx,
        "removed_duplicate_links": removed_duplicates,
        "affected_message_count": preview["summary"]["affected_message_count"],
    }


def _load_messages_for_merge(db: Session, project_id: int, target_id: int, source_ids: list[int]) -> tuple[Message, list[Message]]:
    target_id, source_ids = _validate_merge_ids(target_id, source_ids)
    ids = [target_id, *source_ids]
    rows = (
        db.query(Message)
        .options(
            joinedload(Message.fields).joinedload(MessageField.ref_message),
            joinedload(Message.enum_values),
            joinedload(Message.labels),
            joinedload(Message.tx_targets),
            joinedload(Message.rx_targets),
        )
        .filter(Message.project_id == project_id, Message.id.in_(ids))
        .all()
    )
    by_id = {row.id: row for row in rows}
    if target_id not in by_id:
        raise HTTPException(status_code=404, detail="대표 메시지를 찾을 수 없습니다.")
    missing = [item for item in source_ids if item not in by_id]
    if missing:
        raise HTTPException(status_code=422, detail="같은 프로젝트에 없는 메시지가 포함되어 있습니다.")
    target = by_id[target_id]
    sources = [by_id[item] for item in source_ids]
    definition_types = {(row.definition_type or "STRUCT").upper() for row in [target, *sources]}
    if len(definition_types) != 1:
        raise HTTPException(status_code=422, detail="메시지와 Enum은 서로 머지할 수 없습니다.")
    return target, sources


def _mapped_ref_id(ref_message_id: int | None, merge_map: dict[int, int]) -> int | None:
    if ref_message_id is None:
        return None
    return merge_map.get(int(ref_message_id), int(ref_message_id))


def _field_signature(field: MessageField, mapped_ref_id: int | None = None) -> tuple[Any, ...]:
    type_kind = (field.type_kind or "BASIC").upper()
    ref_id = mapped_ref_id if type_kind in {"MESSAGE", "ENUM"} else None
    type_value = None if ref_id is not None else (field.type or "")
    return (
        type_kind,
        ref_id,
        type_value,
        field.description or "",
        field.purpose or "",
        field.value_range or "",
        field.unit or "",
        field.note or "",
        bool(field.is_array),
        field.array_size,
        field.array_dimensions or None,
    )


def _next_field_name(base_name: str, used_names: set[str]) -> str:
    base = str(base_name or "field").strip() or "field"
    candidate = base[:120]
    if candidate.lower() not in used_names:
        return candidate
    number = 1
    while True:
        suffix = f"_{number}"
        candidate = f"{base[:120 - len(suffix)]}{suffix}"
        if candidate.lower() not in used_names:
            return candidate
        number += 1


def _enum_bounds(underlying_type: str) -> tuple[int, int]:
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


def _find_cycle(adjacency: dict[int, set[int]]) -> list[int] | None:
    visited: set[int] = set()
    active: set[int] = set()
    stack: list[int] = []

    def visit(node: int) -> list[int] | None:
        if node in active:
            try:
                index = stack.index(node)
            except ValueError:
                index = 0
            return stack[index:] + [node]
        if node in visited:
            return None
        visited.add(node)
        active.add(node)
        stack.append(node)
        for child in adjacency.get(node, set()):
            if child not in adjacency:
                continue
            found = visit(child)
            if found:
                return found
        stack.pop()
        active.remove(node)
        return None

    for node in adjacency:
        found = visit(node)
        if found:
            return found
    return None


def _build_message_merge_plan(db: Session, project_id: int, target_id: int, source_ids: list[int]) -> dict[str, Any]:
    target, sources = _load_messages_for_merge(db, project_id, target_id, source_ids)
    all_merge_messages = [target, *sources]
    source_id_set = {row.id for row in sources}
    merge_map = {row.id: target.id for row in sources}
    blockers: list[str] = []

    target_type = (target.definition_type or "STRUCT").upper()
    field_actions: list[dict[str, Any]] = []
    enum_actions: list[dict[str, Any]] = []

    if target_type == "STRUCT":
        virtual_fields: list[dict[str, Any]] = []
        used_names: set[str] = set()
        for field in sorted(target.fields or [], key=lambda item: ((item.order_index or 0), item.id or 0)):
            mapped_ref = _mapped_ref_id(field.ref_message_id, merge_map)
            virtual_fields.append({
                "name": field.name,
                "signature": _field_signature(field, mapped_ref),
            })
            used_names.add((field.name or "").lower())

        next_order = max([int(field.order_index or 0) for field in (target.fields or [])] + [0]) + 1

        for source in sources:
            for field in sorted(source.fields or [], key=lambda item: ((item.order_index or 0), item.id or 0)):
                mapped_ref = _mapped_ref_id(field.ref_message_id, merge_map)
                signature = _field_signature(field, mapped_ref)
                same_name = next((item for item in virtual_fields if item["name"].lower() == (field.name or "").lower()), None)
                if same_name is not None and same_name["signature"] == signature:
                    field_actions.append({
                        "action": "SKIP_IDENTICAL",
                        "source_message_id": source.id,
                        "source_message": _message_name(source),
                        "source_field_id": field.id,
                        "source_name": field.name,
                        "target_name": field.name,
                        "mapped_ref_id": mapped_ref,
                    })
                    continue

                new_name = _next_field_name(field.name, used_names)
                field_actions.append({
                    "action": "COPY",
                    "source_message_id": source.id,
                    "source_message": _message_name(source),
                    "source_field_id": field.id,
                    "source_name": field.name,
                    "target_name": new_name,
                    "mapped_ref_id": mapped_ref,
                    "order_index": next_order,
                })
                next_order += 1
                used_names.add(new_name.lower())
                virtual_fields.append({"name": new_name, "signature": signature})

        # Build the final message-reference graph after redirecting references from
        # removed source messages to the representative message.
        project_messages = (
            db.query(Message)
            .options(joinedload(Message.fields))
            .filter(Message.project_id == project_id)
            .all()
        )
        adjacency: dict[int, set[int]] = {}
        for message in project_messages:
            if message.id in source_id_set:
                continue
            if (message.definition_type or "STRUCT").upper() != "STRUCT":
                continue
            refs: set[int] = set()
            for field in message.fields or []:
                if (field.type_kind or "BASIC").upper() != "MESSAGE" or not field.ref_message_id:
                    continue
                refs.add(_mapped_ref_id(field.ref_message_id, merge_map))
            adjacency[message.id] = refs

        target_refs = adjacency.setdefault(target.id, set())
        for source in sources:
            for field in source.fields or []:
                if (field.type_kind or "BASIC").upper() != "MESSAGE" or not field.ref_message_id:
                    continue
                target_refs.add(_mapped_ref_id(field.ref_message_id, merge_map))

        cycle = _find_cycle(adjacency)
        if cycle:
            name_by_id = {
                row.id: _message_name(row)
                for row in db.query(Message).filter(Message.project_id == project_id).all()
            }
            labels = [name_by_id.get(item, str(item)) for item in cycle]
            blockers.append("머지 후 메시지 참조 순환이 발생합니다: " + " → ".join(labels))

    else:
        if any((source.enum_underlying_type or "uint32") != (target.enum_underlying_type or "uint32") for source in sources):
            blockers.append("Enum 기본 자료형이 서로 달라 머지할 수 없습니다.")

        used_names = {str(value.name or "").lower(): value for value in (target.enum_values or [])}
        used_values = {int(value.value): value for value in (target.enum_values or [])}
        min_value, max_value = _enum_bounds(target.enum_underlying_type or "uint32")

        for source in sources:
            for value in sorted(source.enum_values or [], key=lambda item: ((item.order_index or 0), item.id or 0)):
                same_name = used_names.get((value.name or "").lower())
                same_value = used_values.get(int(value.value))
                if same_name is not None and int(same_name.value) == int(value.value):
                    enum_actions.append({
                        "action": "SKIP_IDENTICAL",
                        "source_message_id": source.id,
                        "source_message": _message_name(source),
                        "source_value_id": value.id,
                        "name": value.name,
                        "value": value.value,
                    })
                    continue
                if same_name is not None:
                    blockers.append(f"Enum 값 이름 충돌: {value.name}")
                    continue
                if same_value is not None:
                    blockers.append(f"Enum 숫자 값 충돌: {value.value} ({same_value.name} / {value.name})")
                    continue
                if int(value.value) < min_value or int(value.value) > max_value:
                    blockers.append(f"대표 Enum 자료형 범위를 벗어나는 값: {value.name}={value.value}")
                    continue
                enum_actions.append({
                    "action": "COPY",
                    "source_message_id": source.id,
                    "source_message": _message_name(source),
                    "source_value_id": value.id,
                    "name": value.name,
                    "value": value.value,
                })
                used_names[(value.name or "").lower()] = value
                used_values[int(value.value)] = value

    all_ids = [row.id for row in all_merge_messages]
    tx_ids = {
        row.target_id
        for row in db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id.in_(all_ids)).all()
    }
    rx_ids = {
        row.target_id
        for row in db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id.in_(all_ids)).all()
    }
    label_ids = {
        row.label_id
        for row in db.query(MessageLabelItem).filter(MessageLabelItem.message_id.in_(all_ids)).all()
    }
    group_rows = db.query(MessageGroupItem).filter(MessageGroupItem.message_id.in_(all_ids)).all()
    group_ids = {row.group_id for row in group_rows}

    target_tx_ids = {row.target_id for row in db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id == target.id).all()}
    target_rx_ids = {row.target_id for row in db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id == target.id).all()}
    target_label_ids = {row.label_id for row in db.query(MessageLabelItem).filter(MessageLabelItem.message_id == target.id).all()}
    target_group_ids = {row.group_id for row in db.query(MessageGroupItem).filter(MessageGroupItem.message_id == target.id).all()}

    reference_rows = db.query(MessageField).filter(
        MessageField.ref_message_id.in_(source_id_set),
        ~MessageField.message_id.in_(source_id_set),
    ).all() if source_id_set else []

    merged_protocol = normalize_protocol_string([row.protocol for row in all_merge_messages])
    current_protocol = normalize_protocol_string(target.protocol)

    return {
        "kind": "MESSAGE",
        "target": {
            "id": target.id,
            "struct_name": _message_name(target),
            "name": target.name,
            "definition_type": target_type,
            "infocode": target.infocode or "",
            "protocol": current_protocol or "",
        },
        "sources": [{
            "id": row.id,
            "struct_name": _message_name(row),
            "name": row.name,
            "infocode": row.infocode or "",
            "protocol": normalize_protocol_string(row.protocol) or "",
        } for row in sources],
        "summary": {
            "source_count": len(sources),
            "protocol_add_count": len(set((merged_protocol or "").split(", ")) - set((current_protocol or "").split(", "))) if merged_protocol else 0,
            "tx_add_count": len(tx_ids - target_tx_ids),
            "rx_add_count": len(rx_ids - target_rx_ids),
            "label_add_count": len(label_ids - target_label_ids),
            "group_add_count": len(group_ids - target_group_ids),
            "field_copy_count": sum(1 for item in field_actions if item["action"] == "COPY"),
            "field_skip_count": sum(1 for item in field_actions if item["action"] == "SKIP_IDENTICAL"),
            "enum_copy_count": sum(1 for item in enum_actions if item["action"] == "COPY"),
            "enum_skip_count": sum(1 for item in enum_actions if item["action"] == "SKIP_IDENTICAL"),
            "reference_redirect_count": len(reference_rows),
        },
        "merged_protocol": merged_protocol or "",
        "field_actions": field_actions,
        "enum_actions": enum_actions,
        "reference_redirects": [{
            "field_id": field.id,
            "message_id": field.message_id,
            "field_name": field.name,
            "from_message_id": field.ref_message_id,
            "to_message_id": target.id,
        } for field in reference_rows],
        "discarded_metadata": [{
            "source_message": _message_name(row),
            "infocode": row.infocode or "",
            "period": row.period or "",
        } for row in sources],
        "blockers": sorted(set(blockers)),
    }


@router.post("/projects/{project_id}/merge/messages/preview")
def preview_message_merge(
    project_id: int,
    payload: MergeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _build_message_merge_plan(db, project_id, payload.target_id, payload.source_ids)


def _copy_message_merge_field(
    db: Session,
    target: Message,
    source_field: MessageField,
    target_name: str,
    mapped_ref_id: int | None,
    order_index: int,
) -> None:
    ref_message = db.get(Message, mapped_ref_id) if mapped_ref_id is not None else None
    type_kind = (source_field.type_kind or "BASIC").upper()
    type_value = source_field.type
    if type_kind in {"MESSAGE", "ENUM"} and ref_message is not None:
        type_value = _message_name(ref_message)

    db.add(MessageField(
        message_id=target.id,
        type=type_value,
        type_kind=type_kind,
        ref_message_id=mapped_ref_id,
        name=target_name,
        variable_name=target_name,
        description=source_field.description or "",
        purpose=source_field.purpose or "",
        value_range=source_field.value_range or "",
        unit=source_field.unit or "",
        note=source_field.note or "",
        is_array=bool(source_field.is_array),
        array_size=source_field.array_size,
        array_dimensions=source_field.array_dimensions,
        order_index=order_index,
    ))


@router.post("/projects/{project_id}/merge/messages/apply")
def apply_message_merge(
    project_id: int,
    payload: MergeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    plan = _build_message_merge_plan(db, project_id, payload.target_id, payload.source_ids)
    if plan["blockers"]:
        raise HTTPException(status_code=409, detail=" / ".join(plan["blockers"]))

    target, sources = _load_messages_for_merge(db, project_id, payload.target_id, payload.source_ids)
    source_id_set = {row.id for row in sources}
    all_ids = [target.id, *source_id_set]

    before_snapshot = {
        "target": plan["target"],
        "sources": plan["sources"],
    }

    # Representative metadata stays authoritative; additive collections are merged.
    target.protocol = plan["merged_protocol"] or None

    # Fields / Enum values
    if (target.definition_type or "STRUCT").upper() == "STRUCT":
        field_by_id = {
            field.id: field
            for source in sources
            for field in (source.fields or [])
        }
        for action in plan["field_actions"]:
            if action["action"] != "COPY":
                continue
            source_field = field_by_id.get(action["source_field_id"])
            if source_field is None:
                continue
            _copy_message_merge_field(
                db,
                target,
                source_field,
                action["target_name"],
                action.get("mapped_ref_id"),
                int(action["order_index"]),
            )
    else:
        value_by_id = {
            value.id: value
            for source in sources
            for value in (source.enum_values or [])
        }
        next_order = max([int(value.order_index or 0) for value in (target.enum_values or [])] + [0]) + 1
        for action in plan["enum_actions"]:
            if action["action"] != "COPY":
                continue
            source_value = value_by_id.get(action["source_value_id"])
            if source_value is None:
                continue
            db.add(MessageEnumValue(
                message_id=target.id,
                name=source_value.name,
                value=source_value.value,
                description=source_value.description or "",
                order_index=next_order,
            ))
            next_order += 1

    # Tags
    existing_label_ids = {
        row.label_id
        for row in db.query(MessageLabelItem).filter(MessageLabelItem.message_id == target.id).all()
    }
    source_label_ids = {
        row.label_id
        for row in db.query(MessageLabelItem).filter(MessageLabelItem.message_id.in_(source_id_set)).all()
    }
    for label_id in sorted(source_label_ids - existing_label_ids):
        db.add(MessageLabelItem(message_id=target.id, label_id=label_id))

    # TX / RX targets
    existing_tx_ids = {
        row.target_id
        for row in db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id == target.id).all()
    }
    source_tx_ids = {
        row.target_id
        for row in db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id.in_(source_id_set)).all()
    }
    for integration_target_id in sorted(source_tx_ids - existing_tx_ids):
        db.add(MessageTxTargetItem(message_id=target.id, target_id=integration_target_id))

    existing_rx_ids = {
        row.target_id
        for row in db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id == target.id).all()
    }
    source_rx_ids = {
        row.target_id
        for row in db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id.in_(source_id_set)).all()
    }
    for integration_target_id in sorted(source_rx_ids - existing_rx_ids):
        db.add(MessageRxTargetItem(message_id=target.id, target_id=integration_target_id))

    # Group membership
    existing_group_ids = {
        row.group_id
        for row in db.query(MessageGroupItem).filter(MessageGroupItem.message_id == target.id).all()
    }
    source_group_rows = db.query(MessageGroupItem).filter(MessageGroupItem.message_id.in_(source_id_set)).order_by(MessageGroupItem.order_index.asc(), MessageGroupItem.id.asc()).all()
    for row in source_group_rows:
        if row.group_id in existing_group_ids:
            continue
        db.add(MessageGroupItem(group_id=row.group_id, message_id=target.id, order_index=row.order_index))
        existing_group_ids.add(row.group_id)

    db.flush()

    # Redirect references from messages that remain after the merge.
    reference_rows = db.query(MessageField).filter(MessageField.ref_message_id.in_(source_id_set)).all()
    for field in reference_rows:
        if field.message_id in source_id_set:
            continue
        field.ref_message_id = target.id
        if (field.type_kind or "BASIC").upper() in {"MESSAGE", "ENUM"}:
            field.type = _message_name(target)

    # Detach rows that otherwise keep foreign keys to the source messages.
    db.query(MessageGroupItem).filter(MessageGroupItem.message_id.in_(source_id_set)).delete(synchronize_session=False)
    db.query(MessageLabelItem).filter(MessageLabelItem.message_id.in_(source_id_set)).delete(synchronize_session=False)
    db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id.in_(source_id_set)).delete(synchronize_session=False)
    db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id.in_(source_id_set)).delete(synchronize_session=False)
    db.query(MessageChangeHistory).filter(MessageChangeHistory.message_id.in_(source_id_set)).update(
        {MessageChangeHistory.message_id: None},
        synchronize_session=False,
    )

    for source in sources:
        db.delete(source)

    target.version = int(target.version or 1) + 1
    db.flush()

    db.add(MessageChangeHistory(
        project_id=project_id,
        message_id=target.id,
        changed_by=current_user.id,
        change_type=ChangeType.UPDATE,
        before_json={"message_merge": before_snapshot},
        after_json={
            "message_merge": {
                "target": {
                    "id": target.id,
                    "struct_name": _message_name(target),
                    "name": target.name,
                },
                "summary": plan["summary"],
                "merged_protocol": plan["merged_protocol"],
                "removed_sources": plan["sources"],
                "field_actions": plan["field_actions"],
                "enum_actions": plan["enum_actions"],
                "reference_redirects": plan["reference_redirects"],
            }
        },
    ))
    db.commit()

    return {
        "ok": True,
        "target_id": target.id,
        "target_struct_name": _message_name(target),
        "removed_source_count": len(sources),
        "summary": plan["summary"],
    }
