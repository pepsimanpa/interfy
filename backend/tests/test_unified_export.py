"""Regression tests for the consolidated export screen's backend operations."""
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    User, Project, IntegrationTarget, Message, MessageField, MessageEnumValue,
    MessageTxTargetItem, MessageRxTargetItem,
)
from app.routers.export import (
    SelectedNodeExportRequest, selected_node_messages, export_selected_nodes,
)
from app.routers.collaboration import build_partner_package, PartnerExportRequest


class UnifiedExportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def enable_fk(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(email="exporter", password_hash="pass")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Scope Test", acronym="SCOPE", owner_id=self.user.id)
        self.other = Project(name="Foreign", acronym="FOREIGN", owner_id=self.user.id)
        self.db.add_all([self.project, self.other])
        self.db.flush()
        self.a = IntegrationTarget(project_id=self.project.id, name="Node_A")
        self.b = IntegrationTarget(project_id=self.project.id, name="Node_B")
        self.foreign = IntegrationTarget(project_id=self.other.id, name="Foreign_Node")
        self.db.add_all([self.a, self.b, self.foreign])
        self.db.flush()

        self.sent = Message(project_id=self.project.id, name="Sent", struct_name="T_SENT", period="비주기", definition_type="STRUCT")
        self.received = Message(project_id=self.project.id, name="Received", struct_name="T_RECEIVED", period="비주기", definition_type="STRUCT")
        self.ref = Message(project_id=self.project.id, name="Shared type", struct_name="T_SHARED", period="비주기", definition_type="ENUM")
        self.unrelated = Message(project_id=self.project.id, name="Other", struct_name="T_OTHER", period="비주기", definition_type="STRUCT")
        self.db.add_all([self.sent, self.received, self.ref, self.unrelated])
        self.db.flush()
        self.db.add_all([
            MessageField(message_id=self.sent.id, name="status", variable_name="status", type="T_SHARED",
                         type_kind="ENUM", ref_message_id=self.ref.id, order_index=1),
            MessageEnumValue(message_id=self.ref.id, name="READY", value=1, order_index=1),
            MessageTxTargetItem(message_id=self.sent.id, target_id=self.a.id),
            MessageRxTargetItem(message_id=self.received.id, target_id=self.a.id),
            MessageTxTargetItem(message_id=self.received.id, target_id=self.b.id),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def names_for(self, ids, direction):
        return {
            item.struct_name for item in selected_node_messages(self.db, self.project.id, ids, direction)[1]
        }

    def test_tx_rx_all_for_one_node(self):
        self.assertEqual(self.names_for([self.a.id], "tx"), {"T_SENT", "T_SHARED"})
        self.assertEqual(self.names_for([self.a.id], "rx"), {"T_RECEIVED"})
        self.assertEqual(self.names_for([self.a.id], "all"), {"T_SENT", "T_SHARED", "T_RECEIVED"})

    def test_multi_node_union_is_deduplicated_and_preserves_referenced_types(self):
        ids = [self.a.id, self.b.id, self.a.id]
        result = selected_node_messages(self.db, self.project.id, ids, "tx")[1]
        self.assertEqual({item.struct_name for item in result}, {"T_SENT", "T_RECEIVED", "T_SHARED"})
        self.assertEqual(len(result), 3)

    def test_invalid_targets_and_direction_are_rejected(self):
        for ids, direction in [
            ([], "all"),
            ([self.foreign.id], "all"),
            ([self.a.id, self.foreign.id], "tx"),
            ([self.a.id], "other"),
        ]:
            with self.subTest(ids=ids, direction=direction):
                with self.assertRaises(HTTPException) as exc:
                    selected_node_messages(self.db, self.project.id, ids, direction)
                self.assertEqual(exc.exception.status_code, 422)

    def test_code_output_for_selected_nodes(self):
        payload = SelectedNodeExportRequest(target_ids=[self.a.id], direction="tx")
        for output_format, extension in [("header", ".h"), ("idl", ".idl"), ("csharp", ".cs")]:
            with self.subTest(output_format=output_format):
                response = export_selected_nodes(
                    self.project.id, output_format, payload, timezone="Asia/Seoul",
                    db=self.db, current_user=self.user,
                )
                self.assertIn(extension, response.headers["content-disposition"])
                self.assertTrue(response.body)
        with self.assertRaises(HTTPException) as exc:
            export_selected_nodes(
                self.project.id, "invalid", payload, db=self.db, current_user=self.user,
            )
        self.assertEqual(exc.exception.status_code, 422)

    def test_partner_json_direction_respects_selected_node_roles(self):
        sample = {
            "format": "interfy-project", "version": 1,
            "project": {"name": "Scope Test"},
            "messages": [
                {"name": "TX", "struct_name": "T_TX", "tx_targets": ["Node_A"], "rx_targets": ["Node_B"], "fields": []},
                {"name": "RX", "struct_name": "T_RX", "tx_targets": ["Node_B"], "rx_targets": ["Node_A"], "fields": []},
            ],
            "groups": [], "labels": [],
            "integration_targets": [{"name": "Node_A"}, {"name": "Node_B"}],
        }
        self.assertEqual(PartnerExportRequest(target_ids=[1]).direction, "all")
        tx = build_partner_package(sample, ["Node_A"], direction="tx")
        rx = build_partner_package(sample, ["Node_A"], direction="rx")
        both = build_partner_package(sample, ["Node_A"], direction="all")
        self.assertEqual([item["struct_name"] for item in tx["messages"]], ["T_TX"])
        self.assertEqual([item["struct_name"] for item in rx["messages"]], ["T_RX"])
        self.assertEqual(len(both["messages"]), 2)
        self.assertEqual(tx["collaboration"]["selected_targets"], ["Node_A"])
        self.assertEqual(tx["collaboration"]["base_messages"], tx["messages"])


if __name__ == "__main__":
    unittest.main()
