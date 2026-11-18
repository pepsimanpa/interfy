"""System configuration integration tests (SQLite with enforced foreign keys)."""
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    User, Project, IntegrationTarget, SystemNodeProfile,
    SystemIpAssignment, SystemTransportConnection,
)
from app.schemas import (
    SystemNodeProfileUpdate, SystemIpCreate,
    SystemConnectionCreate, SystemConnectionUpdate,
)
from app.routers.system_configuration import (
    upsert_node_profile, read_system_configuration,
    add_ip_assignment, add_connection, update_connection,
    delete_ip_assignment,
)
from app.routers.backups import _build_database_backup, _restore_database_backup


class SystemConfigurationTests(unittest.TestCase):
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
        self.user = User(email="tester", password_hash="test")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="System test", acronym="SYS", owner_id=self.user.id)
        self.other_project = Project(name="Other", acronym="OTHER", owner_id=self.user.id)
        self.db.add_all([self.project, self.other_project])
        self.db.flush()
        self.node1 = IntegrationTarget(project_id=self.project.id, name="체계관리")
        self.node2 = IntegrationTarget(project_id=self.project.id, name="예인몸체연동제어")
        self.foreign_node = IntegrationTarget(project_id=self.other_project.id, name="타 프로젝트")
        self.db.add_all([self.node1, self.node2, self.foreign_node])
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def create_ip(self, node_id, ip, reserved=False):
        return add_ip_assignment(self.project.id, SystemIpCreate(
            node_id=node_id, ip_address=ip, is_reserved=reserved,
            interface_name="NIC1" if not reserved else "reserved1",
        ), db=self.db, current_user=self.user)

    def test_existing_node_reused_and_device_id_unique(self):
        row = upsert_node_profile(self.project.id, self.node1.id, SystemNodeProfileUpdate(
            device_id=7, hardware_name="체계관리기",
            hostname="SYS-HOST", software_id="SW-7",
        ), db=self.db, current_user=self.user)
        self.assertEqual(row["device_id"], 7)
        self.assertEqual(row["name"], "체계관리")
        self.assertEqual(row["hardware_name"], "체계관리기")

        # Changing the original node name does not lose system configuration.
        self.node1.name = "체계관리#1"
        self.db.commit()
        self.assertEqual(
            next(row["name"] for row in read_system_configuration(self.project.id, db=self.db, current_user=self.user)["nodes"] if row["node_id"] == self.node1.id),
            "체계관리#1",
        )

        with self.assertRaises(HTTPException) as err:
            upsert_node_profile(self.project.id, self.node2.id, SystemNodeProfileUpdate(
                device_id=7,
            ), db=self.db, current_user=self.user)
        self.assertEqual(err.exception.status_code, 409)
        self.assertEqual(self.db.query(SystemNodeProfile).count(), 1)

    def test_reserved_ips_and_project_wide_uniqueness(self):
        self.create_ip(self.node1.id, "192.168.7.70")
        self.create_ip(self.node1.id, "192.168.7.73", reserved=True)
        rows = read_system_configuration(self.project.id, db=self.db, current_user=self.user)["ip_assignments"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(row["ip_address"] == "192.168.7.73" and row["is_reserved"] for row in rows))

        with self.assertRaises(HTTPException) as err:
            self.create_ip(self.node2.id, "192.168.7.70")
        self.assertEqual(err.exception.status_code, 409)
        with self.assertRaises(HTTPException) as invalid:
            self.create_ip(self.node2.id, "192.168.7.999")
        self.assertEqual(invalid.exception.status_code, 422)

        with self.assertRaises(HTTPException) as foreign:
            self.create_ip(self.foreign_node.id, "192.168.7.80")
        self.assertEqual(foreign.exception.status_code, 422)

    def test_connection_references_allocated_ips_and_blocks_ip_removal(self):
        server = self.create_ip(self.node1.id, "192.168.7.70")
        client = self.create_ip(self.node2.id, "192.168.7.10")
        connection = add_connection(
            self.project.id, SystemConnectionCreate(
                server_ip_id=server["id"], server_port=15010,
                client_ip_id=client["id"], client_port=16010,
            ), db=self.db, current_user=self.user,
        )
        self.assertIsInstance(connection["id"], int)
        rows = read_system_configuration(self.project.id, db=self.db, current_user=self.user)["connections"]
        self.assertEqual(rows[0]["server_node_name"], "체계관리")
        self.assertEqual(rows[0]["client_ip"], "192.168.7.10")

        with self.assertRaises(HTTPException) as conflict:
            add_connection(
                self.project.id, SystemConnectionCreate(
                    server_ip_id=server["id"], server_port=15010,
                    client_ip_id=client["id"], client_port=16010,
                ), db=self.db, current_user=self.user,
            )
        self.assertEqual(conflict.exception.status_code, 409)

        with self.assertRaises(HTTPException) as dependent:
            delete_ip_assignment(self.project.id, server["id"], db=self.db, current_user=self.user)
        self.assertEqual(dependent.exception.status_code, 409)

        updated = update_connection(
            self.project.id, connection["id"], SystemConnectionUpdate(
                server_port=15011,
            ), db=self.db, current_user=self.user,
        )
        self.assertEqual(updated["id"], connection["id"])

    def test_project_backup_round_trip_includes_system_configuration(self):
        upsert_node_profile(self.project.id, self.node1.id, SystemNodeProfileUpdate(
            device_id=7, hardware_name="체계관리기",
        ), db=self.db, current_user=self.user)
        server = self.create_ip(self.node1.id, "192.168.7.70")
        client = self.create_ip(self.node2.id, "192.168.7.10")
        add_connection(self.project.id, SystemConnectionCreate(
            server_ip_id=server["id"], server_port=15010,
            client_ip_id=client["id"], client_port=16010,
        ), db=self.db, current_user=self.user)
        backup = _build_database_backup(self.db, self.project.id)
        self.assertEqual(len(backup["system_node_profiles"]), 1)
        self.assertEqual(len(backup["system_ip_assignments"]), 2)
        self.assertEqual(len(backup["system_transport_connections"]), 1)

        _restore_database_backup(self.db, self.project, backup)
        self.db.commit()
        after = read_system_configuration(self.project.id, db=self.db, current_user=self.user)
        self.assertEqual(len(after["nodes"]), 2)
        self.assertEqual(len(after["ip_assignments"]), 2)
        self.assertEqual(len(after["connections"]), 1)
        self.assertEqual(next(node["device_id"] for node in after["nodes"] if node["name"] == "체계관리"), 7)


if __name__ == "__main__":
    unittest.main()
