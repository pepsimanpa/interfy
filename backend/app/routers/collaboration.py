"""Export a scoped, editable partner package based on Interfy's native JSON schema.

Only selected nodes' related messages and transitive STRUCT/ENUM references are
included; external nodes mentioned in those messages remain in the node list
so the standalone editor can preserve complete TX/RX relationships.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..auth import get_current_user
from ..database import get_db
from ..models import Project, IntegrationTarget, User, Message, MessageField, MessageEnumValue, MessageGroupItem, MessageLabelItem, MessageTxLabelItem, MessageRxLabelItem, MessageTxTargetItem, MessageRxTargetItem, MessageChangeHistory, ChangeType
from .project_json import export_project_json, _json_response, _safe_filename_part, _load_project_json
from .backups import _create_project_backup


router = APIRouter(tags=["collaboration"])


class PartnerExportRequest(BaseModel):
    target_ids: list[int] = Field(min_length=1)


def build_partner_package(project_data: dict[str, Any], selected_names: list[str], node_ids: dict[str, int] | None = None, project_id: int | None = None, message_ids: dict[str, int] | None = None) -> dict[str, Any]:
    """Pure subset builder, also useful from regression tests."""
    selected = {name.lower() for name in selected_names}
    messages = project_data.get("messages", [])
    indexed = {str(row.get("struct_name") or row.get("name") or "").lower(): row for row in messages}

    initial = [
        row for row in messages
        if selected.intersection({
            *(str(name).lower() for name in row.get("tx_targets", [])),
            *(str(name).lower() for name in row.get("rx_targets", [])),
        })
    ]
    included = {row["struct_name"].lower() for row in initial}
    pending = list(included)
    while pending:
        row = indexed.get(pending.pop())
        if row is None:
            continue
        for field in row.get("fields", []):
            if field.get("type_kind") not in {"MESSAGE", "ENUM"}:
                continue
            ref = str(field.get("ref_message") or field.get("data_type") or "").lower()
            if ref in indexed and ref not in included:
                included.add(ref)
                pending.append(ref)

    package = copy.deepcopy(project_data)
    package["messages"] = [
        {**row, **({"interfy_id": message_ids[row["struct_name"].lower()]} if message_ids and row["struct_name"].lower() in message_ids else {})}
        for row in messages if row["struct_name"].lower() in included
    ]
    available_names = {row["struct_name"].lower() for row in package["messages"]}
    package["groups"] = [
        {**group, "messages": [name for name in group.get("messages", []) if str(name).lower() in available_names]}
        for group in project_data.get("groups", [])
        if any(str(name).lower() in available_names for name in group.get("messages", []))
    ]
    package["labels"] = [
        {**label, "messages": [name for name in label.get("messages", []) if str(name).lower() in available_names]}
        for label in project_data.get("labels", [])
        if any(str(name).lower() in available_names for name in label.get("messages", []))
    ]
    related_nodes = selected.copy()
    for row in package["messages"]:
        related_nodes.update(str(name).lower() for name in row.get("tx_targets", []) + row.get("rx_targets", []))
    package["integration_targets"] = [
        {**node, **({"interfy_id": node_ids[node["name"].lower()]} if node_ids and node["name"].lower() in node_ids else {})}
        for node in project_data.get("integration_targets", [])
        if node["name"].lower() in related_nodes
    ]
    package["collaboration"] = {
        "project_id": project_id,
        "format": "interfy-partner-v1",
        "exported_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "selected_targets": [
            node["name"] for node in package["integration_targets"]
            if node["name"].lower() in selected
        ],
        # These snapshots are comparison aids, not access control or a signature.
        "base_messages": copy.deepcopy(package["messages"]),
        "base_targets": copy.deepcopy(package["integration_targets"]),
    }
    return package


@router.post("/projects/{project_id}/collaboration/export")
def export_partner_package(
    project_id: int,
    payload: PartnerExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    ids = set(payload.target_ids)
    targets = db.query(IntegrationTarget).filter(
        IntegrationTarget.project_id == project_id, IntegrationTarget.id.in_(ids)
    ).all()
    if len(targets) != len(ids):
        raise HTTPException(status_code=422, detail="현재 프로젝트에 없는 노드가 포함되어 있습니다.")

    full_json = export_project_json(project_id, db, current_user)
    project_data = json.loads(full_json.body)
    all_nodes = db.query(IntegrationTarget).filter(IntegrationTarget.project_id == project_id).all()
    node_ids = {node.name.lower(): node.id for node in all_nodes}
    all_messages = db.query(Message).filter(Message.project_id == project_id).all()
    message_ids = {(message.struct_name or message.name).lower(): message.id for message in all_messages}
    content = build_partner_package(project_data, [target.name for target in targets], node_ids, project_id, message_ids)
    base = _safe_filename_part(project.acronym or project.name or "interfy")
    return _json_response(content, f"{base}-partner-package.json")


async def _read_partner_json(file: UploadFile) -> dict[str, Any]:
    try:
        data = json.loads((await file.read()).decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="유효한 UTF-8 JSON 파일이 아닙니다.") from exc
    _load_project_json(data)
    meta = data.get("collaboration")
    if not isinstance(meta, dict) or meta.get("format") != "interfy-partner-v1":
        raise HTTPException(status_code=422, detail="Interfy 협력사 작업 패키지가 아닙니다.")
    if not isinstance(meta.get("base_targets"), list):
        raise HTTPException(status_code=422, detail="패키지 원본 노드 정보가 없습니다.")
    return data


def _node_plan(db: Session, project_id: int, data: dict[str, Any]) -> dict[str, Any]:
    meta = data["collaboration"]
    if meta.get("project_id") != project_id:
        raise HTTPException(status_code=409, detail="다른 프로젝트에서 내보낸 협력사 패키지입니다.")

    bases = meta["base_targets"]
    incoming = data.get("integration_targets") or []
    if not isinstance(incoming, list):
        raise HTTPException(status_code=422, detail="노드 목록이 올바르지 않습니다.")

    current_rows = db.query(IntegrationTarget).filter(IntegrationTarget.project_id == project_id).all()
    by_id = {item.id: item for item in current_rows}
    base_by_id = {}
    blockers = []
    for item in bases:
        try:
            identity = int(item.get("interfy_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="노드 식별자가 없는 오래된 패키지입니다. 다시 내보내 주세요.")
        if identity in base_by_id:
            raise HTTPException(status_code=422, detail="패키지 노드 식별자가 중복되었습니다.")
        base_by_id[identity] = item

    seen_names = set()
    seen_ids = set()
    current_by_name = {row.name.lower(): row for row in current_rows}
    intended_names = {}
    actions = []
    for item in incoming:
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "")
        if not name or len(name) > 120 or name.lower() in seen_names:
            raise HTTPException(status_code=422, detail=f"노드 이름이 비었거나 중복됩니다: {name}")
        seen_names.add(name.lower())
        raw_id = item.get("interfy_id")
        try:
            identity = int(raw_id) if raw_id is not None else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"노드 식별자가 올바르지 않습니다: {name}")
        if identity is None:
            already = current_by_name.get(name.lower())
            if already is not None and (already.description or "") == description:
                # A repeated import after the node was created is a no-op.
                continue
            actions.append({"action": "ADD", "name": name, "description": description})
            continue
        if identity in seen_ids or identity not in base_by_id:
            raise HTTPException(status_code=422, detail="패키지에 알 수 없는 노드 식별자가 포함되어 있습니다.")
        seen_ids.add(identity)
        base = base_by_id[identity]
        current = by_id.get(identity)
        if current is None:
            blockers.append(f"{base.get('name')}: 원본 노드가 현재 프로젝트에서 삭제되었습니다.")
            continue
        original = (str(base.get("name") or ""), str(base.get("description") or ""))
        actual = (current.name, current.description or "")
        proposed = (name, description)
        if actual != original and actual != proposed:
            blockers.append(f"{original[0]}: 내보낸 이후 DB의 노드가 변경되었습니다. 다시 내보내 주세요.")
        intended_names[identity] = name
        if proposed != actual:
            actions.append({"action": "UPDATE", "id": identity, "before_name": current.name, "name": name, "description": description})

    for identity, base in base_by_id.items():
        if identity in seen_ids:
            continue
        current = by_id.get(identity)
        if current is None:
            continue
        if current.name != str(base.get("name") or ""):
            blockers.append(f"{base.get('name')}: 원본 노드 이름이 변경되어 삭제할 수 없습니다.")
        tx_count = db.query(MessageTxTargetItem).filter(MessageTxTargetItem.target_id == identity).count()
        rx_count = db.query(MessageRxTargetItem).filter(MessageRxTargetItem.target_id == identity).count()
        actions.append({"action": "DELETE", "id": identity, "name": current.name, "tx_count": tx_count, "rx_count": rx_count})

    # Compare projected final names (including untouched DB nodes), so swaps and
    # conflicts are caught before the transaction mutates anything.
    deleted = {item["id"] for item in actions if item["action"] == "DELETE"}
    final_names = {}
    for current in current_rows:
        if current.id in deleted:
            continue
        name = intended_names.get(current.id, current.name)
        if name.lower() in final_names:
            blockers.append(f"최종 노드 이름 중복: {name}")
        final_names[name.lower()] = current.id
    for action in actions:
        if action["action"] == "ADD":
            if action["name"].lower() in final_names:
                blockers.append(f"이미 존재하는 노드 이름: {action['name']}")
            final_names[action["name"].lower()] = None
    return {
        "node_actions": actions,
        "summary": {
            "added": sum(item["action"] == "ADD" for item in actions),
            "updated": sum(item["action"] == "UPDATE" for item in actions),
            "deleted": sum(item["action"] == "DELETE" for item in actions),
        },
        "blockers": sorted(set(blockers)),
    }


@router.post("/projects/{project_id}/collaboration/nodes/preview")
async def preview_partner_nodes(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    data = await _read_partner_json(file)
    return _node_plan(db, project_id, data)


@router.post("/projects/{project_id}/collaboration/nodes/apply")
async def apply_partner_nodes(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    data = await _read_partner_json(file)
    plan = _node_plan(db, project_id, data)
    if plan["blockers"]:
        raise HTTPException(status_code=409, detail=" / ".join(plan["blockers"]))
    actions = plan["node_actions"]
    if not actions:
        return {"ok": True, "updated_count": 0, "backup_id": None}

    backup = _create_project_backup(
        db, project_id, current_user, kind="AUTO_BEFORE_MERGE",
        note="협력사 작업 패키지 노드 변경 반영 전 자동 백업",
    )

    # Temporarily release names in the same transaction, including rename swaps.
    for action in actions:
        if action["action"] == "UPDATE":
            row = db.get(IntegrationTarget, action["id"])
            row.name = f"_interfy_partner_tmp_{row.id}"
    db.flush()

    for action in actions:
        kind = action["action"]
        if kind == "UPDATE":
            row = db.get(IntegrationTarget, action["id"])
            row.name = action["name"]
            row.description = action["description"]
        elif kind == "ADD":
            db.add(IntegrationTarget(project_id=project_id, name=action["name"], description=action["description"]))
        elif kind == "DELETE":
            db.delete(db.get(IntegrationTarget, action["id"]))
    try:
        db.flush()
        db.add(MessageChangeHistory(
            project_id=project_id,
            message_id=None,
            changed_by=current_user.id,
            change_type=ChangeType.UPDATE,
            before_json={"partner_nodes": {"filename": file.filename}},
            after_json={"partner_nodes": {"actions": actions, "backup_id": backup.id}},
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="노드 변경 중 중복/참조 충돌이 발생했습니다.") from exc

    return {"ok": True, "updated_count": len(actions), "backup_id": backup.id}


def _message_delete_plan(db: Session, project_id: int, data: dict[str, Any]) -> dict[str, Any]:
    if data["collaboration"].get("project_id") != project_id:
        raise HTTPException(status_code=409, detail="다른 프로젝트의 협력사 작업 패키지입니다.")

    original = data["collaboration"].get("base_messages")
    if not isinstance(original, list):
        raise HTTPException(status_code=422, detail="패키지 원본 메시지 정보가 없습니다.")

    current_export = json.loads(export_project_json(project_id, db, None).body)
    current_by_name = {
        row["struct_name"].lower(): row
        for row in current_export["messages"]
    }
    incoming_names = {
        str(row.get("struct_name") or "").lower()
        for row in data.get("messages", [])
    }
    original_by_name = {
        str(row.get("struct_name") or "").lower(): row
        for row in original
    }
    removed = sorted(set(original_by_name) - incoming_names)
    actions = []
    blockers = []
    for key in removed:
        before = original_by_name[key]
        current = current_by_name.get(key)
        if current is None:
            continue
        base_compare = {key: value for key, value in before.items() if key != "interfy_id"}
        if current != base_compare:
            blockers.append(f"{before['struct_name']}: 내보낸 이후 DB에서 변경되어 자동 삭제할 수 없습니다.")
            continue
        message = db.query(Message).filter(
            Message.project_id == project_id,
            Message.struct_name == current["struct_name"],
        ).first()
        if message is None:
            continue
        refs = db.query(MessageField).filter(MessageField.ref_message_id == message.id).all()
        in_removed = [
            ref for ref in refs
            if ref.message_id != message.id
            and db.get(Message, ref.message_id)
            and (db.get(Message, ref.message_id).struct_name or "").lower() in removed
        ]
        outside = [ref for ref in refs if ref not in in_removed and ref.message_id != message.id]
        if outside:
            blockers.append(
                f"{current['struct_name']}: 다른 메시지 {len(outside)}개 필드에서 참조하고 있어 삭제할 수 없습니다."
            )
        actions.append({
            "id": message.id,
            "struct_name": current["struct_name"],
            "reference_count": len(refs),
        })
    return {"message_deletions": actions, "blockers": sorted(set(blockers))}


@router.post("/projects/{project_id}/collaboration/messages/delete-preview")
async def preview_partner_message_deletions(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _message_delete_plan(db, project_id, await _read_partner_json(file))


@router.post("/projects/{project_id}/collaboration/messages/delete-apply")
async def apply_partner_message_deletions(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    plan = _message_delete_plan(db, project_id, await _read_partner_json(file))
    if plan["blockers"]:
        raise HTTPException(status_code=409, detail=" / ".join(plan["blockers"]))
    actions = plan["message_deletions"]
    if not actions:
        return {"ok": True, "deleted_count": 0, "backup_id": None}
    ids = [action["id"] for action in actions]

    backup = _create_project_backup(
        db, project_id, current_user, kind="AUTO_BEFORE_MERGE",
        note="협력사 작업 패키지 메시지 삭제 전 자동 백업",
    )
    # All referencing fields outside the selected messages were rejected
    # in preview, so removing dependent rows cannot break any remaining type.
    db.query(MessageField).filter(MessageField.message_id.in_(ids)).delete(synchronize_session=False)
    db.query(MessageEnumValue).filter(MessageEnumValue.message_id.in_(ids)).delete(synchronize_session=False)
    db.query(MessageGroupItem).filter(MessageGroupItem.message_id.in_(ids)).delete(synchronize_session=False)
    db.query(MessageLabelItem).filter(MessageLabelItem.message_id.in_(ids)).delete(synchronize_session=False)
    db.query(MessageTxLabelItem).filter(MessageTxLabelItem.message_id.in_(ids)).delete(synchronize_session=False)
    db.query(MessageRxLabelItem).filter(MessageRxLabelItem.message_id.in_(ids)).delete(synchronize_session=False)
    db.query(MessageTxTargetItem).filter(MessageTxTargetItem.message_id.in_(ids)).delete(synchronize_session=False)
    db.query(MessageRxTargetItem).filter(MessageRxTargetItem.message_id.in_(ids)).delete(synchronize_session=False)
    db.query(MessageChangeHistory).filter(MessageChangeHistory.message_id.in_(ids)).update(
        {MessageChangeHistory.message_id: None}, synchronize_session=False,
    )
    db.query(Message).filter(Message.id.in_(ids)).delete(synchronize_session=False)
    db.add(MessageChangeHistory(
        project_id=project_id, message_id=None,
        changed_by=current_user.id, change_type=ChangeType.DELETE,
        before_json={"partner_deleted_messages": plan["message_deletions"]},
        after_json={"partner_deleted_messages": {"backup_id": backup.id, "deleted_count": len(ids)}},
    ))
    db.commit()
    return {"ok": True, "deleted_count": len(ids), "backup_id": backup.id}


def _message_rename_plan(db: Session, project_id: int, data: dict[str, Any]) -> dict[str, Any]:
    if data["collaboration"].get("project_id") != project_id:
        raise HTTPException(status_code=409, detail="다른 프로젝트의 협력사 작업 패키지입니다.")

    bases = data["collaboration"].get("base_messages")
    if not isinstance(bases, list):
        raise HTTPException(status_code=422, detail="패키지 원본 메시지 정보가 없습니다.")
    base_by_id = {}
    for item in bases:
        try:
            identity = int(item["interfy_id"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=422, detail="메시지 식별자가 없는 패키지입니다. 다시 내보내 주세요.")
        base_by_id[identity] = item

    current_rows = db.query(Message).filter(Message.project_id == project_id).all()
    by_id = {row.id: row for row in current_rows}
    found_ids = set()
    actions = []
    blockers = []

    for incoming in data.get("messages", []):
        original_id = incoming.get("interfy_id")
        if original_id is None:
            continue
        try:
            identity = int(original_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="메시지 식별자가 올바르지 않습니다.")
        if identity not in base_by_id or identity in found_ids:
            raise HTTPException(status_code=422, detail="패키지 내 메시지 식별자가 중복되거나 알 수 없습니다.")
        found_ids.add(identity)
        base = base_by_id[identity]
        row = by_id.get(identity)
        if row is None:
            blockers.append(f"{base.get('struct_name')}: 원본 메시지가 삭제되었습니다.")
            continue
        new_name = str(incoming.get("struct_name") or "").strip()
        if not re.fullmatch(r"^[A-Za-z_][A-Za-z0-9_]*$", new_name) or len(new_name) > 120:
            raise HTTPException(status_code=422, detail=f"잘못된 구조체 이름: {new_name}")
        original_name = str(base.get("struct_name") or "")
        actual_name = str(row.struct_name or row.name)
        if actual_name not in {original_name, new_name}:
            blockers.append(f"{original_name}: 내보낸 뒤 원본 메시지명이 변경되었습니다.")
            continue
        if actual_name != new_name:
            actions.append({"id": identity, "before_name": actual_name, "name": new_name})

    # Validate final type-name uniqueness across this project, including swaps.
    renamed = {item["id"]: item["name"] for item in actions}
    projected = {}
    for row in current_rows:
        name = renamed.get(row.id, row.struct_name or row.name)
        key = name.lower()
        if key in projected:
            blockers.append(f"구조체/Enum 이름 중복: {name}")
        projected[key] = row.id
    return {"message_renames": actions, "blockers": sorted(set(blockers))}


@router.post("/projects/{project_id}/collaboration/messages/rename-preview")
async def preview_partner_message_renames(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _message_rename_plan(db, project_id, await _read_partner_json(file))


@router.post("/projects/{project_id}/collaboration/messages/rename-apply")
async def apply_partner_message_renames(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    plan = _message_rename_plan(db, project_id, await _read_partner_json(file))
    if plan["blockers"]:
        raise HTTPException(status_code=409, detail=" / ".join(plan["blockers"]))
    actions = plan["message_renames"]
    if not actions:
        return {"ok": True, "renamed_count": 0, "backup_id": None}

    backup = _create_project_backup(
        db, project_id, current_user, kind="AUTO_BEFORE_MERGE",
        note="협력사 패키지 메시지/Enum 이름 변경 전 자동 백업",
    )
    for action in actions:
        db.get(Message, action["id"]).struct_name = f"_interfy_type_tmp_{action['id']}"
    db.flush()

    for action in actions:
        row = db.get(Message, action["id"])
        row.struct_name = action["name"]
        for field in db.query(MessageField).filter(
            MessageField.ref_message_id == row.id,
            MessageField.type_kind.in_(("MESSAGE", "ENUM")),
        ).all():
            field.type = action["name"]

    db.add(MessageChangeHistory(
        project_id=project_id, message_id=None, changed_by=current_user.id,
        change_type=ChangeType.UPDATE,
        before_json={"partner_message_renames": {"filename": file.filename}},
        after_json={"partner_message_renames": {"actions": actions, "backup_id": backup.id}},
    ))
    db.commit()
    return {"ok": True, "renamed_count": len(actions), "backup_id": backup.id}
