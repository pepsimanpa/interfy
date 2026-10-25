"""Collaboration package export/import regression tests.

Run from backend/: python -m unittest discover -s tests -v
"""
import asyncio
import io
import json
import unittest

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import IntegrationTarget, Message, MessageField, MessageTxTargetItem, Project, ProjectBackup, User
from app.routers.collaboration import build_partner_package, _node_plan, apply_partner_nodes, _message_delete_plan, _message_rename_plan, apply_partner_message_renames, apply_partner_message_deletions
from app.routers.project_json import export_project_json


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(email="tester@example.com", password_hash="test")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Partner", acronym="PARTNER", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def node(self, name):
        item = IntegrationTarget(project_id=self.project.id, name=name, description=name)
        self.db.add(item)
        self.db.flush()
        return item

    def message(self, name):
        item = Message(
            project_id=self.project.id,
            struct_name=name,
            name=name,
            period="비주기",
            definition_type="STRUCT",
        )
        self.db.add(item)
        self.db.flush()
        return item

    def package(self, selected, mapping):
        full = json.loads(export_project_json(self.project.id, self.db, self.user).body)
        return build_partner_package(
            full, selected, mapping, self.project.id
        )

    @staticmethod
    def upload(data):
        return UploadFile(
            filename="edited.json",
            file=io.BytesIO(json.dumps(data, ensure_ascii=False).encode("utf-8")),
        )

    def test_export_subset_preserves_cross_node_relationships(self):
        a, b, c = self.node("A"), self.node("B"), self.node("C")
        status, other = self.message("T_STATUS"), self.message("T_OTHER")
        self.db.add_all([
            MessageTxTargetItem(message_id=status.id, target_id=a.id),
            MessageTxTargetItem(message_id=other.id, target_id=c.id),
        ])
        self.db.flush()
        # A is selected; only A's message should be included.
        pack = self.package(["A"], {"a": a.id, "b": b.id, "c": c.id})
        self.assertEqual([m["struct_name"] for m in pack["messages"]], ["T_STATUS"])
        self.assertEqual([n["name"] for n in pack["integration_targets"]], ["A"])
        self.assertEqual(pack["integration_targets"][0]["interfy_id"], a.id)
        self.assertEqual(pack["collaboration"]["project_id"], self.project.id)
        self.assertEqual(len(pack["collaboration"]["base_messages"]), 1)

    def test_node_rename_keeps_existing_message_link_and_backup(self):
        a = self.node("AUV")
        status = self.message("T_STATUS")
        self.db.add(MessageTxTargetItem(message_id=status.id, target_id=a.id))
        self.db.commit()
        pack = self.package(["AUV"], {"auv": a.id})
        pack["integration_targets"][0]["name"] = "AUV_NEW"
        plan = _node_plan(self.db, self.project.id, pack)
        self.assertEqual(plan["summary"]["updated"], 1)
        self.assertEqual(plan["blockers"], [])
        result = asyncio.run(apply_partner_nodes(
            self.project.id, self.upload(pack), self.db, self.user
        ))
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(self.db.get(IntegrationTarget, a.id).name, "AUV_NEW")
        self.assertEqual(self.db.query(MessageTxTargetItem).one().target_id, a.id)
        self.assertEqual(self.db.get(ProjectBackup, result["backup_id"]).kind, "AUTO_BEFORE_MERGE")
        self.assertEqual(_node_plan(self.db, self.project.id, pack)["node_actions"], [])

    def test_new_node_addition_is_idempotent(self):
        a = self.node("AUV")
        self.db.commit()
        pack = self.package(["AUV"], {"auv": a.id})
        pack["integration_targets"].append({"name": "USV", "description": "new"})
        result = asyncio.run(apply_partner_nodes(
            self.project.id, self.upload(pack), self.db, self.user
        ))
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(_node_plan(self.db, self.project.id, pack)["node_actions"], [])
        self.assertEqual(self.db.query(IntegrationTarget).count(), 2)

    def test_message_struct_rename_preserves_reference_identity(self):
        node = self.node("AUV")
        status = self.message("T_STATUS")
        wrapper = self.message("T_WRAPPER")
        self.db.add_all([
            MessageTxTargetItem(message_id=status.id, target_id=node.id),
            MessageField(message_id=wrapper.id, name="payload", variable_name="payload",
                         type="T_STATUS", type_kind="MESSAGE", ref_message_id=status.id),
        ])
        self.db.commit()
        pack = self.package(["AUV"], {"auv": node.id})
        # Referenced types are part of the package, including their stable IDs.
        edited = next(item for item in pack["messages"] if item["struct_name"] == "T_STATUS")
        edited["struct_name"] = "T_STATUS_NEW"
        planned = _message_rename_plan(self.db, self.project.id, pack)
        self.assertEqual(len(planned["message_renames"]), 1)
        self.assertEqual(_message_delete_plan(self.db, self.project.id, pack)["message_deletions"], [])
        result = asyncio.run(apply_partner_message_renames(
            self.project.id, self.upload(pack), self.db, self.user
        ))
        self.assertEqual(result["renamed_count"], 1)
        self.db.refresh(status)
        self.assertEqual(status.struct_name, "T_STATUS_NEW")
        ref = self.db.query(MessageField).one()
        self.assertEqual(ref.ref_message_id, status.id)
        self.assertEqual(ref.type, "T_STATUS_NEW")
        self.assertEqual(_message_rename_plan(self.db, self.project.id, pack)["message_renames"], [])

    def test_deleted_message_is_detected_and_removed_with_backup(self):
        node = self.node("AUV")
        status = self.message("T_STATUS")
        self.db.add(MessageTxTargetItem(message_id=status.id, target_id=node.id))
        self.db.commit()
        pack = self.package(["AUV"], {"auv": node.id})
        pack["messages"] = []
        preview = _message_delete_plan(self.db, self.project.id, pack)
        self.assertEqual(len(preview["message_deletions"]), 1)
        self.assertEqual(preview["blockers"], [])
        result = asyncio.run(apply_partner_message_deletions(
            self.project.id, self.upload(pack), self.db, self.user
        ))
        self.assertEqual(result["deleted_count"], 1)
        self.assertIsNone(self.db.get(Message, status.id))
        self.assertEqual(_message_delete_plan(self.db, self.project.id, pack)["message_deletions"], [])
        self.assertEqual(self.db.get(ProjectBackup, result["backup_id"]).kind, "AUTO_BEFORE_MERGE")

    def test_message_deletion_blocked_when_other_message_references_it(self):
        node = self.node("AUV")
        status = self.message("T_STATUS")
        wrapper = self.message("T_WRAPPER")
        self.db.add_all([
            MessageTxTargetItem(message_id=status.id, target_id=node.id),
            MessageField(message_id=wrapper.id, name="payload", variable_name="payload",
                         type="T_STATUS", type_kind="MESSAGE", ref_message_id=status.id),
        ])
        self.db.commit()
        pack = self.package(["AUV"], {"auv": node.id})
        pack["messages"] = []
        preview = _message_delete_plan(self.db, self.project.id, pack)
        self.assertTrue(preview["blockers"])
        with self.assertRaises(HTTPException) as failure:
            asyncio.run(apply_partner_message_deletions(
                self.project.id, self.upload(pack), self.db, self.user
            ))
        self.assertEqual(failure.exception.status_code, 409)
        self.assertIsNotNone(self.db.get(Message, status.id))

    def test_conflicting_exported_node_is_blocked(self):
        a = self.node("AUV")
        self.db.commit()
        pack = self.package(["AUV"], {"auv": a.id})
        a.name = "AUV_CHANGED_ELSEWHERE"
        self.db.commit()
        pack["integration_targets"][0]["name"] = "AUV_NEW"
        plan = _node_plan(self.db, self.project.id, pack)
        self.assertTrue(plan["blockers"])
        with self.assertRaises(HTTPException) as failure:
            asyncio.run(apply_partner_nodes(
                self.project.id, self.upload(pack), self.db, self.user
            ))
        self.assertEqual(failure.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
