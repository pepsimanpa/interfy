"""Regression tests for node and message merges.

Run from backend/: python -m unittest discover -s tests -v
These tests deliberately use a disposable in-memory SQLite database.
"""
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    IntegrationTarget, Message, MessageChangeHistory, MessageEnumValue,
    MessageField, MessageGroup, MessageGroupItem, MessageLabel,
    MessageLabelItem, MessageRxTargetItem, MessageTxTargetItem,
    Project, ProjectBackup, User,
)
from app.routers.merge_tools import (
    MergeRequest, _build_message_merge_plan, _target_merge_preview,
    apply_message_merge, apply_target_merge,
)


class MergeToolsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def enable_fk(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(email="tester@example.com", password_hash="test")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Merge test", acronym="TEST", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def node(self, name):
        row = IntegrationTarget(project_id=self.project.id, name=name)
        self.db.add(row)
        self.db.flush()
        return row

    def message(self, struct_name, infocode=None, *, kind="STRUCT", protocol=None):
        row = Message(
            project_id=self.project.id, name=struct_name,
            struct_name=struct_name, period="비주기",
            definition_type=kind, infocode=infocode, protocol=protocol,
            enum_underlying_type="uint32",
        )
        self.db.add(row)
        self.db.flush()
        return row

    def field(self, message, name, data_type, *, kind="BASIC", ref_id=None):
        row = MessageField(
            message_id=message.id, name=name, variable_name=name, type=data_type,
            type_kind=kind, ref_message_id=ref_id, order_index=len(message.fields) + 1,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def test_node_merge_moves_links_without_duplicates_and_backs_up(self):
        a, b, c = self.node("A"), self.node("B"), self.node("C")
        status, heartbeat = self.message("T_STATUS"), self.message("T_HEARTBEAT")
        self.db.add_all([
            MessageTxTargetItem(target_id=a.id, message_id=status.id),
            MessageTxTargetItem(target_id=b.id, message_id=status.id),
            MessageTxTargetItem(target_id=c.id, message_id=status.id),
            MessageRxTargetItem(target_id=c.id, message_id=heartbeat.id),
        ])
        self.db.commit()

        request = MergeRequest(target_id=a.id, source_ids=[b.id, c.id])
        preview = _target_merge_preview(self.db, self.project.id, a.id, [b.id, c.id])
        self.assertEqual(preview["summary"]["affected_message_count"], 2)
        self.assertEqual(preview["summary"]["duplicate_link_count"], 2)

        result = apply_target_merge(self.project.id, request, self.db, self.user)
        self.assertTrue(result["ok"])
        self.assertIsNotNone(self.db.get(IntegrationTarget, a.id))
        self.assertIsNone(self.db.get(IntegrationTarget, b.id))
        self.assertIsNone(self.db.get(IntegrationTarget, c.id))
        self.assertEqual(self.db.query(MessageTxTargetItem).count(), 1)
        self.assertEqual(self.db.query(MessageRxTargetItem).count(), 1)
        self.assertEqual(self.db.query(MessageTxTargetItem).one().target_id, a.id)
        self.assertEqual(self.db.query(MessageRxTargetItem).one().target_id, a.id)
        backup = self.db.get(ProjectBackup, result["backup_id"])
        self.assertEqual(backup.kind, "AUTO_BEFORE_MERGE")
        self.assertEqual(len(backup.snapshot_json["integration_targets"]), 3)

    def test_message_merge_preserves_metadata_and_redirects_reference(self):
        a, b = self.node("A"), self.node("B")
        target = self.message("T_STATUS", "100", protocol="TCP")
        source = self.message("T_STATUS_1", "101", protocol="UDP")
        owner = self.message("T_WRAPPER", "102")
        self.field(target, "status", "uint32")
        self.field(source, "status", "uint16")
        self.field(source, "result", "uint8")
        self.field(owner, "payload", "T_STATUS_1", kind="MESSAGE", ref_id=source.id)

        tag = MessageLabel(project_id=self.project.id, name="Common")
        group = MessageGroup(project_id=self.project.id, name="Status")
        self.db.add_all([tag, group])
        self.db.flush()
        self.db.add_all([
            MessageLabelItem(label_id=tag.id, message_id=source.id),
            MessageGroupItem(group_id=group.id, message_id=source.id, order_index=1),
            MessageTxTargetItem(target_id=a.id, message_id=source.id),
            MessageRxTargetItem(target_id=b.id, message_id=source.id),
        ])
        self.db.commit()

        request = MergeRequest(target_id=target.id, source_ids=[source.id])
        preview = _build_message_merge_plan(self.db, self.project.id, target.id, [source.id])
        self.assertEqual(preview["blockers"], [])
        self.assertEqual(preview["summary"]["field_copy_count"], 2)
        self.assertEqual(preview["summary"]["reference_redirect_count"], 1)

        result = apply_message_merge(self.project.id, request, self.db, self.user)
        self.assertTrue(result["ok"])
        self.assertIsNone(self.db.get(Message, source.id))
        self.db.refresh(target)
        self.assertEqual(target.infocode, "100")
        self.assertEqual(target.protocol, "TCP, UDP")
        self.assertEqual({f.name for f in target.fields}, {"status", "status_1", "result"})
        self.assertEqual(self.db.query(MessageTxTargetItem).filter_by(message_id=target.id).count(), 1)
        self.assertEqual(self.db.query(MessageRxTargetItem).filter_by(message_id=target.id).count(), 1)
        self.assertEqual(self.db.query(MessageLabelItem).filter_by(message_id=target.id).count(), 1)
        self.assertEqual(self.db.query(MessageGroupItem).filter_by(message_id=target.id).count(), 1)
        ref = self.db.query(MessageField).filter_by(message_id=owner.id).one()
        self.assertEqual(ref.ref_message_id, target.id)
        self.assertEqual(ref.type, "T_STATUS")
        self.assertEqual(self.db.get(ProjectBackup, result["backup_id"]).kind, "AUTO_BEFORE_MERGE")
        self.assertGreaterEqual(self.db.query(MessageChangeHistory).count(), 1)

    def test_message_merge_rejects_introduced_self_reference(self):
        target = self.message("T_PARENT")
        source = self.message("T_CHILD")
        self.field(target, "nested", "T_CHILD", kind="MESSAGE", ref_id=source.id)
        self.db.commit()

        request = MergeRequest(target_id=target.id, source_ids=[source.id])
        preview = _build_message_merge_plan(self.db, self.project.id, target.id, [source.id])
        self.assertTrue(preview["blockers"])
        with self.assertRaises(HTTPException) as caught:
            apply_message_merge(self.project.id, request, self.db, self.user)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIsNotNone(self.db.get(Message, source.id))
        self.assertEqual(self.db.query(ProjectBackup).count(), 0)

    def test_enum_conflicts_do_not_remove_sources(self):
        target = self.message("T_MODE", kind="ENUM")
        source = self.message("T_MODE_NEW", kind="ENUM")
        self.db.add_all([
            MessageEnumValue(message_id=target.id, name="WAIT", value=1, order_index=1),
            MessageEnumValue(message_id=source.id, name="RUN", value=1, order_index=1),
        ])
        self.db.commit()

        request = MergeRequest(target_id=target.id, source_ids=[source.id])
        preview = _build_message_merge_plan(self.db, self.project.id, target.id, [source.id])
        self.assertTrue(preview["blockers"])
        with self.assertRaises(HTTPException) as caught:
            apply_message_merge(self.project.id, request, self.db, self.user)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIsNotNone(self.db.get(Message, source.id))


if __name__ == "__main__":
    unittest.main()
