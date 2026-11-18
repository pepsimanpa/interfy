"""Project-scoped system configuration using existing Interfy integration nodes.

A node is registered once in integration_targets. Extra device identification,
IP allocations and transport connections reference that identity, so renaming a
node in Interface Design never breaks the system configuration.
"""
import ipaddress

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import (
    IntegrationTarget, Project, SystemNodeProfile,
    SystemIpAssignment, SystemPortBinding, SystemTransportConnection, User,
)
from ..schemas import (
    SystemNodeProfileUpdate, SystemIpCreate, SystemIpUpdate,
    SystemConnectionCreate, SystemConnectionUpdate,
    SystemPortBindingCreate, SystemPortBindingUpdate,
)

router = APIRouter(tags=["system-configuration"])


def _project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다.")
    return project


def _node(db: Session, project_id: int, node_id: int) -> IntegrationTarget:
    node = db.get(IntegrationTarget, node_id)
    if node is None or node.project_id != project_id:
        raise HTTPException(status_code=422, detail="현재 프로젝트에 없는 노드입니다.")
    return node


def _ip(db: Session, project_id: int, ip_id: int) -> SystemIpAssignment:
    assignment = db.get(SystemIpAssignment, ip_id)
    if assignment is None or assignment.project_id != project_id:
        raise HTTPException(status_code=404, detail="현재 프로젝트의 IP 할당을 찾을 수 없습니다.")
    return assignment


def _binding(db: Session, project_id: int, binding_id: int) -> SystemPortBinding:
    binding = db.get(SystemPortBinding, binding_id)
    if binding is None or binding.project_id != project_id:
        raise HTTPException(status_code=422, detail="현재 프로젝트에 등록되지 않은 포트 바인딩입니다.")
    return binding


def _read_binding(row: SystemPortBinding, ips: dict[int, SystemIpAssignment], node_names: dict[int, str]) -> dict:
    ip = ips.get(row.ip_assignment_id)
    return {
        "id": row.id, "ip_assignment_id": row.ip_assignment_id,
        "ip_address": ip.ip_address if ip else "",
        "interface_name": ip.interface_name if ip else "",
        "node_id": ip.node_id if ip else None,
        "node_name": node_names.get(ip.node_id, "") if ip else "",
        "protocol": row.protocol, "port_mode": row.port_mode,
        "port": row.port, "description": row.description,
    }


def _connection(db: Session, project_id: int, connection_id: int) -> SystemTransportConnection:
    row = db.get(SystemTransportConnection, connection_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="현재 프로젝트의 통신 연결을 찾을 수 없습니다.")
    return row


def _normalized_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="올바른 IPv4 또는 IPv6 주소를 입력하세요.") from exc


def _commit(db: Session, conflict: str):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=conflict) from exc


def _read_profile(node: IntegrationTarget, profile: SystemNodeProfile | None) -> dict:
    return {
        "node_id": node.id, "name": node.name, "description": node.description or "",
        "device_id": profile.device_id if profile else None,
        "hardware_name": profile.hardware_name if profile else "",
        "hostname": profile.hostname if profile else "",
        "software_id": profile.software_id if profile else "",
        "hardware_id": profile.hardware_id if profile else "",
        "note": profile.note if profile else "",
    }


def _read_assignment(row: SystemIpAssignment, node_names: dict[int, str]) -> dict:
    return {
        "id": row.id, "node_id": row.node_id,
        "node_name": node_names.get(row.node_id, ""),
        "interface_name": row.interface_name, "ip_address": row.ip_address,
        "is_reserved": row.is_reserved, "note": row.note,
    }


def _read_connection(row: SystemTransportConnection, ips: dict[int, SystemIpAssignment], nodes: dict[int, str]) -> dict:
    server = ips.get(row.server_ip_id)
    client = ips.get(row.client_ip_id)
    server_binding = row.server_binding
    client_binding = row.client_binding
    return {
        "id": row.id,
        "server_ip_id": row.server_ip_id,
        "client_ip_id": row.client_ip_id,
        "server_binding_id": row.server_binding_id,
        "client_binding_id": row.client_binding_id,
        "server_port": None if server_binding and server_binding.port_mode == "AUTO" else row.server_port,
        "client_port": None if client_binding and client_binding.port_mode == "AUTO" else row.client_port,
        "server_port_mode": server_binding.port_mode if server_binding else ("AUTO" if row.server_port == 0 else "FIXED"),
        "client_port_mode": client_binding.port_mode if client_binding else ("AUTO" if row.client_port is None else "FIXED"),
        "protocol": row.protocol, "note": row.note,
        "server_ip": server.ip_address if server else "",
        "client_ip": client.ip_address if client else "",
        "server_node_id": server.node_id if server else None,
        "client_node_id": client.node_id if client else None,
        "server_node_name": nodes.get(server.node_id, "") if server else "",
        "client_node_name": nodes.get(client.node_id, "") if client else "",
    }


def _validate_binding_fields(db: Session, project_id: int, ip_id: int, protocol: str, mode: str, port: int | None, exclude: int | None = None) -> int | None:
    _ip(db, project_id, ip_id)
    if mode == "FIXED" and port is None:
        raise HTTPException(status_code=422, detail="고정 포트에는 포트 번호가 필요합니다.")
    if mode == "AUTO" and port is not None:
        raise HTTPException(status_code=422, detail="AUTO 바인딩은 포트 번호를 지정하지 않습니다.")
    query = db.query(SystemPortBinding).filter(
        SystemPortBinding.project_id == project_id,
        SystemPortBinding.ip_assignment_id == ip_id,
        SystemPortBinding.protocol == protocol,
        SystemPortBinding.port_mode == mode,
        SystemPortBinding.port == port,
    )
    if exclude is not None:
        query = query.filter(SystemPortBinding.id != exclude)
    with db.no_autoflush:
        if query.first():
            raise HTTPException(status_code=409, detail="해당 IP에 동일한 프로토콜·포트 바인딩이 이미 존재합니다.")
    return port


def _apply_binding_to_connection(db: Session, project_id: int, row: SystemTransportConnection) -> None:
    if row.server_binding_id is None or row.client_binding_id is None:
        raise HTTPException(status_code=422, detail="Server와 Client 바인딩을 모두 선택해 주세요.")
    server = _binding(db, project_id, row.server_binding_id)
    client = _binding(db, project_id, row.client_binding_id)
    if server.protocol != client.protocol:
        raise HTTPException(status_code=422, detail="Server와 Client 바인딩의 TCP/UDP 프로토콜이 달라 연결할 수 없습니다.")
    _check_endpoints(db, project_id, server.ip_assignment_id, client.ip_assignment_id)
    row.server_ip_id = server.ip_assignment_id
    row.client_ip_id = client.ip_assignment_id
    row.protocol = server.protocol
    # Existing feature-branch DBs keep server_port NOT NULL. The internal
    # value 0 denotes dynamic AUTO, never a real listening port.
    row.server_port = server.port if server.port_mode == "FIXED" else 0
    row.client_port = client.port if client.port_mode == "FIXED" else None


@router.get("/projects/{project_id}/system-configuration")
def read_system_configuration(
    project_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _project(db, project_id)
    nodes = db.query(IntegrationTarget).filter(
        IntegrationTarget.project_id == project_id
    ).order_by(IntegrationTarget.name.asc(), IntegrationTarget.id.asc()).all()
    node_names = {node.id: node.name for node in nodes}
    profiles = {
        profile.node_id: profile
        for profile in db.query(SystemNodeProfile).filter(
            SystemNodeProfile.project_id == project_id
        ).all()
    }
    allocations = db.query(SystemIpAssignment).filter(
        SystemIpAssignment.project_id == project_id
    ).order_by(SystemIpAssignment.ip_address.asc()).all()
    ips = {ip.id: ip for ip in allocations}
    bindings = db.query(SystemPortBinding).filter(
        SystemPortBinding.project_id == project_id
    ).order_by(SystemPortBinding.id.asc()).all()
    connections = db.query(SystemTransportConnection).filter(
        SystemTransportConnection.project_id == project_id
    ).order_by(SystemTransportConnection.id.asc()).all()
    return {
        "nodes": [_read_profile(node, profiles.get(node.id)) for node in nodes],
        "ip_assignments": [_read_assignment(row, node_names) for row in allocations],
        "port_bindings": [_read_binding(row, ips, node_names) for row in bindings],
        "connections": [_read_connection(row, ips, node_names) for row in connections],
    }


@router.put("/projects/{project_id}/system-configuration/nodes/{node_id}")
def upsert_node_profile(
    project_id: int, node_id: int, payload: SystemNodeProfileUpdate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    node = _node(db, project_id, node_id)
    profile = db.query(SystemNodeProfile).filter(
        SystemNodeProfile.node_id == node_id
    ).first()
    if profile is None:
        profile = SystemNodeProfile(node_id=node_id, project_id=project_id)
        db.add(profile)
    for field, value in payload.model_dump().items():
        setattr(profile, field, value.strip() if isinstance(value, str) else value)
    _commit(db, "이 프로젝트에 같은 장비 ID가 이미 등록되어 있습니다.")
    return _read_profile(node, profile)


@router.post("/projects/{project_id}/system-configuration/ips")
def add_ip_assignment(
    project_id: int, payload: SystemIpCreate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    _project(db, project_id)
    _node(db, project_id, payload.node_id)
    row = SystemIpAssignment(
        project_id=project_id, node_id=payload.node_id,
        interface_name=payload.interface_name.strip(),
        ip_address=_normalized_ip(payload.ip_address),
        is_reserved=payload.is_reserved, note=payload.note.strip(),
    )
    db.add(row)
    _commit(db, "현재 프로젝트에 동일한 IP 주소가 이미 등록되어 있습니다.")
    return _read_assignment(row, {payload.node_id: _node(db, project_id, payload.node_id).name})


@router.patch("/projects/{project_id}/system-configuration/ips/{ip_id}")
def update_ip_assignment(
    project_id: int, ip_id: int, payload: SystemIpUpdate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    row = _ip(db, project_id, ip_id)
    changes = payload.model_dump(exclude_unset=True)
    if "node_id" in changes:
        _node(db, project_id, changes["node_id"])
    if "ip_address" in changes:
        changes["ip_address"] = _normalized_ip(changes["ip_address"])
    for field, value in changes.items():
        setattr(row, field, value.strip() if isinstance(value, str) else value)
    _commit(db, "현재 프로젝트에 동일한 IP 주소가 이미 등록되어 있습니다.")
    return _read_assignment(row, {row.node_id: _node(db, project_id, row.node_id).name})


@router.delete("/projects/{project_id}/system-configuration/ips/{ip_id}")
def delete_ip_assignment(
    project_id: int, ip_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _ip(db, project_id, ip_id)
    if db.query(SystemPortBinding).filter(
        SystemPortBinding.project_id == project_id,
        SystemPortBinding.ip_assignment_id == ip_id,
    ).first():
        raise HTTPException(status_code=409, detail="이 IP에 포트 바인딩이 등록되어 있습니다. 포트 바인딩부터 삭제해 주세요.")
    if db.query(SystemTransportConnection).filter(
        SystemTransportConnection.project_id == project_id,
        or_(SystemTransportConnection.server_ip_id == ip_id,
            SystemTransportConnection.client_ip_id == ip_id),
    ).first():
        raise HTTPException(status_code=409, detail="통신 연결에서 사용 중인 IP입니다. 연결부터 삭제해 주세요.")
    db.delete(row)
    db.commit()
    return {"ok": True}



@router.post("/projects/{project_id}/system-configuration/ports")
def add_port_binding(
    project_id: int, payload: SystemPortBindingCreate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    _project(db, project_id)
    _validate_binding_fields(db, project_id, payload.ip_assignment_id, payload.protocol, payload.port_mode, payload.port)
    row = SystemPortBinding(project_id=project_id, **payload.model_dump())
    db.add(row)
    _commit(db, "포트 바인딩을 등록하지 못했습니다.")
    ip = _ip(db, project_id, row.ip_assignment_id)
    return _read_binding(row, {ip.id: ip}, {ip.node_id: _node(db, project_id, ip.node_id).name})


@router.patch("/projects/{project_id}/system-configuration/ports/{binding_id}")
def update_port_binding(
    project_id: int, binding_id: int, payload: SystemPortBindingUpdate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    row = _binding(db, project_id, binding_id)
    changes = payload.model_dump(exclude_unset=True)
    protocol = changes.get("protocol", row.protocol)
    mode = changes.get("port_mode", row.port_mode)
    port = changes.get("port", row.port)
    if mode == "AUTO" and "port" not in changes:
        port = None
    # Require an explicit port when switching AUTO -> FIXED.
    _validate_binding_fields(db, project_id, row.ip_assignment_id, protocol, mode, port, exclude=binding_id)
    row.protocol = protocol
    row.port_mode = mode
    row.port = port
    if "description" in changes:
        row.description = changes["description"] or ""
    # Updating a binding updates its existing connections' effective endpoint.
    links = db.query(SystemTransportConnection).filter(
        SystemTransportConnection.project_id == project_id,
        or_(SystemTransportConnection.server_binding_id == binding_id,
            SystemTransportConnection.client_binding_id == binding_id),
    ).all()
    for link in links:
        _apply_binding_to_connection(db, project_id, link)
        if _duplicate_connection(db, project_id, link, excluding_id=link.id):
            db.rollback()
            raise HTTPException(status_code=409, detail="변경한 포트로 인해 통신 연결이 중복됩니다.")
    _commit(db, "포트 변경 중 통신 연결이 중복되었습니다.")
    ip = _ip(db, project_id, row.ip_assignment_id)
    return _read_binding(row, {ip.id: ip}, {ip.node_id: _node(db, project_id, ip.node_id).name})


@router.delete("/projects/{project_id}/system-configuration/ports/{binding_id}")
def delete_port_binding(
    project_id: int, binding_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _binding(db, project_id, binding_id)
    in_use = db.query(SystemTransportConnection).filter(
        SystemTransportConnection.project_id == project_id,
        or_(SystemTransportConnection.server_binding_id == binding_id,
            SystemTransportConnection.client_binding_id == binding_id),
    ).first()
    if in_use:
        raise HTTPException(status_code=409, detail="통신 연결에서 사용 중인 바인딩입니다. 연결부터 삭제해 주세요.")
    db.delete(row)
    _commit(db, "포트 바인딩을 삭제할 수 없습니다.")
    return {"ok": True}


def _check_endpoints(db: Session, project_id: int, server_ip_id: int, client_ip_id: int) -> None:
    _ip(db, project_id, server_ip_id)
    _ip(db, project_id, client_ip_id)
    if server_ip_id == client_ip_id:
        raise HTTPException(status_code=422, detail="서버와 클라이언트에는 서로 다른 IP를 선택하세요.")


@router.post("/projects/{project_id}/system-configuration/connections")
def add_connection(
    project_id: int, payload: SystemConnectionCreate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    _project(db, project_id)
    data = payload.model_dump()
    row = SystemTransportConnection(project_id=project_id)
    row.note = data["note"]
    if data["server_binding_id"] is not None or data["client_binding_id"] is not None:
        row.server_binding_id = data["server_binding_id"]
        row.client_binding_id = data["client_binding_id"]
        _apply_binding_to_connection(db, project_id, row)
    else:
        if data["server_ip_id"] is None or data["client_ip_id"] is None or data["server_port"] is None:
            raise HTTPException(status_code=422, detail="Server/Client 포트 바인딩을 선택하거나 IP와 Server 포트를 입력하세요.")
        _check_endpoints(db, project_id, data["server_ip_id"], data["client_ip_id"])
        row.server_ip_id = data["server_ip_id"]
        row.server_port = data["server_port"]
        row.client_ip_id = data["client_ip_id"]
        row.client_port = data["client_port"]
        row.protocol = data["protocol"]
    # A dynamic endpoint remains unassigned until the network stack binds it.
    if _duplicate_connection(db, project_id, row):
        raise HTTPException(status_code=409, detail="동일한 통신 연결이 이미 있습니다.")
    db.add(row)
    _commit(db, "동일한 통신 연결이 이미 있습니다.")
    return {"id": row.id}


def _duplicate_connection(db: Session, project_id: int, row: SystemTransportConnection, excluding_id: int | None = None) -> bool:
    query = db.query(SystemTransportConnection).filter(
        SystemTransportConnection.project_id == project_id,
        SystemTransportConnection.server_ip_id == row.server_ip_id,
        SystemTransportConnection.client_ip_id == row.client_ip_id,
        SystemTransportConnection.server_port == row.server_port,
        SystemTransportConnection.client_port == row.client_port,
        SystemTransportConnection.protocol == row.protocol,
    )
    if excluding_id is not None:
        query = query.filter(SystemTransportConnection.id != excluding_id)
    # Pending edits must not flush before the duplicate check can report a 409.
    with db.no_autoflush:
        return query.first() is not None


@router.patch("/projects/{project_id}/system-configuration/connections/{connection_id}")
def update_connection(
    project_id: int, connection_id: int, payload: SystemConnectionUpdate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    row = _connection(db, project_id, connection_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(row, field, value)
    if row.server_binding_id is not None or row.client_binding_id is not None:
        _apply_binding_to_connection(db, project_id, row)
    else:
        if row.server_port is None or row.server_ip_id is None or row.client_ip_id is None:
            raise HTTPException(status_code=422, detail="Server/Client 포트 설정이 필요합니다.")
        _check_endpoints(db, project_id, row.server_ip_id, row.client_ip_id)
    if _duplicate_connection(db, project_id, row, excluding_id=row.id):
        raise HTTPException(status_code=409, detail="동일한 통신 연결이 이미 있습니다.")
    _commit(db, "동일한 통신 연결이 이미 있습니다.")
    return {"id": row.id}


@router.delete("/projects/{project_id}/system-configuration/connections/{connection_id}")
def delete_connection(
    project_id: int, connection_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _connection(db, project_id, connection_id)
    db.delete(row)
    db.commit()
    return {"ok": True}
