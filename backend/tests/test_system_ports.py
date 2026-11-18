"""IP/NIC port-binding and topology-endpoint behavior, SQLite FK enabled."""
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import User, Project, IntegrationTarget, SystemPortBinding
from app.schemas import (
    SystemIpCreate, SystemPortBindingCreate, SystemPortBindingUpdate,
    SystemConnectionCreate,
)
from app.routers.system_configuration import (
    add_ip_assignment, add_port_binding, update_port_binding, delete_port_binding,
    add_connection, read_system_configuration, delete_ip_assignment,
)
from app.routers.integration_targets import delete_integration_target
from app.routers.backups import _build_database_backup, _restore_database_backup


class SystemPortBindingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def enforce_fk(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.actor = User(email="ports-test", password_hash="pass")
        self.db.add(self.actor)
        self.db.flush()
        self.project = Project(name="Test", acronym="TEST", owner_id=self.actor.id)
        self.db.add(self.project)
        self.db.flush()
        self.server_node = IntegrationTarget(project_id=self.project.id, name="Server")
        self.client_node = IntegrationTarget(project_id=self.project.id, name="Client")
        self.db.add_all([self.server_node, self.client_node])
        self.db.commit()

        self.server = add_ip_assignment(
            self.project.id, SystemIpCreate(node_id=self.server_node.id, ip_address="192.168.7.70", interface_name="NIC1"),
            db=self.db, current_user=self.actor,
        )
        self.client = add_ip_assignment(
            self.project.id, SystemIpCreate(node_id=self.client_node.id, ip_address="192.168.7.10", interface_name="NIC1"),
            db=self.db, current_user=self.actor,
        )

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def bind(self, ip, protocol="TCP", mode="FIXED", port=None):
        return add_port_binding(
            self.project.id,
            SystemPortBindingCreate(
                ip_assignment_id=ip["id"], protocol=protocol,
                port_mode=mode, port=port,
            ),
            db=self.db, current_user=self.actor,
        )

    def connect(self, server, client):
        return add_connection(
            self.project.id,
            SystemConnectionCreate(
                server_binding_id=server["id"],
                client_binding_id=client["id"],
            ),
            db=self.db, current_user=self.actor,
        )

    def test_fixed_server_and_automatic_client(self):
        server = self.bind(self.server, port=15010)
        client = self.bind(self.client, mode="AUTO")
        created = self.connect(server, client)
        details = read_system_configuration(self.project.id, db=self.db, current_user=self.actor)
        self.assertEqual(len(details["port_bindings"]), 2)
        self.assertEqual(len(details["connections"]), 1)
        row = details["connections"][0]
        self.assertEqual(row["id"], created["id"])
        self.assertEqual(row["server_port"], 15010)
        self.assertEqual(row["client_port"], None)
        self.assertEqual(row["client_port_mode"], "AUTO")
        self.assertEqual(row["server_node_id"], self.server_node.id)
        self.assertEqual(row["client_node_id"], self.client_node.id)
        self.assertEqual(row["protocol"], "TCP")

    def test_automatic_server_is_not_reported_as_port_zero(self):
        server = self.bind(self.server, mode="AUTO")
        client = self.bind(self.client, port=16100)
        self.connect(server, client)
        row = read_system_configuration(self.project.id, db=self.db, current_user=self.actor)["connections"][0]
        self.assertIsNone(row["server_port"])
        self.assertEqual(row["server_port_mode"], "AUTO")
        self.assertEqual(row["client_port"], 16100)

    def test_reject_same_binding_duplicate_protocol_mismatch_and_in_use_delete(self):
        server = self.bind(self.server, port=15010)
        client = self.bind(self.client, mode="AUTO")
        with self.assertRaises(HTTPException) as duplicate:
            self.bind(self.server, port=15010)
        self.assertEqual(duplicate.exception.status_code, 409)
        mismatch = self.bind(self.client, protocol="UDP", mode="AUTO")
        with self.assertRaises(HTTPException) as invalid:
            self.connect(server, mismatch)
        self.assertEqual(invalid.exception.status_code, 422)
        self.connect(server, client)
        with self.assertRaises(HTTPException) as linked:
            delete_port_binding(self.project.id, server["id"], db=self.db, current_user=self.actor)
        self.assertEqual(linked.exception.status_code, 409)
        with self.assertRaises(HTTPException) as ip_conflict:
            delete_ip_assignment(self.project.id, self.server["id"], db=self.db, current_user=self.actor)
        self.assertEqual(ip_conflict.exception.status_code, 409)

    def test_update_binding_updates_connection_snapshot(self):
        server = self.bind(self.server, port=15010)
        client = self.bind(self.client, mode="AUTO")
        self.connect(server, client)
        update_port_binding(
            self.project.id, server["id"], SystemPortBindingUpdate(port=15011),
            db=self.db, current_user=self.actor,
        )
        row = read_system_configuration(self.project.id, db=self.db, current_user=self.actor)["connections"][0]
        self.assertEqual(row["server_port"], 15011)
        update_port_binding(
            self.project.id, server["id"], SystemPortBindingUpdate(port_mode="AUTO", port=None),
            db=self.db, current_user=self.actor,
        )
        row = read_system_configuration(self.project.id, db=self.db, current_user=self.actor)["connections"][0]
        self.assertEqual(row["server_port_mode"], "AUTO")
        self.assertIsNone(row["server_port"])

    def test_backup_restore_round_trip_retains_binding_ids(self):
        server = self.bind(self.server, port=15010)
        client = self.bind(self.client, mode="AUTO")
        self.connect(server, client)
        backup = _build_database_backup(self.db, self.project.id)
        self.assertEqual(len(backup["system_port_bindings"]), 2)
        self.assertEqual(len(backup["system_transport_connections"]), 1)
        self.assertEqual(backup["system_transport_connections"][0]["server_binding_id"], server["id"])
        _restore_database_backup(self.db, self.project, backup)
        self.db.commit()
        data = read_system_configuration(self.project.id, db=self.db, current_user=self.actor)
        self.assertEqual(len(data["port_bindings"]), 2)
        self.assertEqual(len(data["connections"]), 1)
        self.assertEqual(data["connections"][0]["client_binding_id"], client["id"])

    def test_configured_node_cannot_be_deleted_without_ip_cleanup(self):
        with self.assertRaises(HTTPException) as error:
            delete_integration_target(self.server_node.id, db=self.db, current_user=self.actor)
        self.assertEqual(error.exception.status_code, 409)

    def test_binding_is_project_scoped(self):
        other = Project(name="Other", acronym="OTHER", owner_id=self.actor.id)
        self.db.add(other)
        self.db.commit()
        with self.assertRaises(HTTPException) as error:
            add_port_binding(other.id, SystemPortBindingCreate(
                ip_assignment_id=self.server["id"], port=15010,
            ), db=self.db, current_user=self.actor)
        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
