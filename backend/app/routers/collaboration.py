"""Export a scoped, editable partner package based on Interfy's native JSON schema.

Only selected nodes' related messages and transitive STRUCT/ENUM references are
included; external nodes mentioned in those messages remain in the node list
so the standalone editor can preserve complete TX/RX relationships.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Project, IntegrationTarget, User
from .project_json import export_project_json, _json_response, _safe_filename_part


router = APIRouter(tags=["collaboration"])


class PartnerExportRequest(BaseModel):
    target_ids: list[int] = Field(min_length=1)


def build_partner_package(project_data: dict[str, Any], selected_names: list[str]) -> dict[str, Any]:
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
    package["messages"] = [row for row in messages if row["struct_name"].lower() in included]
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
        node for node in project_data.get("integration_targets", [])
        if node["name"].lower() in related_nodes
    ]
    package["collaboration"] = {
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
    content = build_partner_package(project_data, [target.name for target in targets])
    base = _safe_filename_part(project.acronym or project.name or "interfy")
    return _json_response(content, f"{base}-partner-package.json")
