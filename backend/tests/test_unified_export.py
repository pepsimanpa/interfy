"""Regression tests for the consolidated export screen's backend operations."""
import asyncio
import io
import json
import unittest

from fastapi import HTTPException, UploadFile
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
from app.routers.partial_update import _partner_relation_baseline, _prepare_partial_messages, _load_existing_messages, apply_partial_update
from app.routers.project_json import export_project_json


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


    def test_scoped_partner_json_hides_other_nodes_even_in_comparison_snapshot(self):
        example = {
            "format": "interfy-project", "version": 1,
            "project": {"name": "Scope Test"},
            "messages": [
                {"name": "Test", "struct_name": "T_TEST",
                 "tx_targets": ["Node_A", "Node_C"],
                 "rx_targets": ["Node_B", "Node_D", "Node_E"], "fields": []},
            ],
            "groups": [], "labels": [],
            "integration_targets": [
                {"name": name} for name in ["Node_A", "Node_B", "Node_C", "Node_D", "Node_E"]
            ],
        }
        self.assertFalse(PartnerExportRequest(target_ids=[1]).restrict_relations)
        normal = build_partner_package(example, ["Node_A", "Node_B"])
        self.assertEqual(normal["messages"][0]["rx_targets"], ["Node_B", "Node_D", "Node_E"])
        scoped = build_partner_package(
            example, ["Node_A", "Node_B"], restrict_relations=True,
        )
        self.assertEqual(scoped["messages"][0]["tx_targets"], ["Node_A"])
        self.assertEqual(scoped["messages"][0]["rx_targets"], ["Node_B"])
        self.assertEqual(
            {n["name"] for n in scoped["integration_targets"]}, {"Node_A", "Node_B"},
        )
        self.assertTrue(scoped["collaboration"]["restrict_relations"])
        self.assertEqual(scoped["collaboration"]["base_messages"], scoped["messages"])
        self.assertEqual(scoped["collaboration"]["base_targets"], scoped["integration_targets"])
        self.assertNotIn("Node_C", json.dumps(scoped))
        self.assertNotIn("Node_D", json.dumps(scoped))
        self.assertNotIn("Node_E", json.dumps(scoped))

    def test_scoped_partner_relation_modes_and_new_nodes(self):
        c = IntegrationTarget(project_id=self.project.id, name="Node_C")
        d = IntegrationTarget(project_id=self.project.id, name="Node_D")
        self.db.add_all([c, d])
        self.db.flush()
        self.db.add_all([
            MessageTxTargetItem(message_id=self.sent.id, target_id=c.id),
            MessageRxTargetItem(message_id=self.sent.id, target_id=self.b.id),
            MessageRxTargetItem(message_id=self.sent.id, target_id=d.id),
        ])
        self.db.commit()

        original = json.loads(export_project_json(self.project.id, self.db, self.user).body)
        pack = build_partner_package(
            original, ["Node_A", "Node_B"], project_id=self.project.id, restrict_relations=True,
        )
        edited = next(m for m in pack["messages"] if m["struct_name"] == "T_SENT")
        self.assertEqual(edited["tx_targets"], ["Node_A"])
        self.assertEqual(edited["rx_targets"], ["Node_B"])
        edited["rx_targets"] = ["Node_F"]  # B removed; F added in offline editor
        pack["integration_targets"].append({"name": "Node_F", "description": "Partner created node"})

        old_messages = _load_existing_messages(self.db, self.project.id)
        baseline = _partner_relation_baseline(pack, "PARTIAL")
        partial = _prepare_partial_messages(
            old_messages, [edited], "REPLACE", "REPLACE", "PARTIAL", baseline,
        )[0]
        self.assertEqual(partial["tx_targets"], ["Node_A", "Node_C"])
        self.assertEqual(partial["rx_targets"], ["Node_D", "Node_F"])

        ignored = _prepare_partial_messages(
            old_messages, [edited], "REPLACE", "REPLACE", "IGNORE",
        )[0]
        self.assertEqual(ignored["rx_targets"], ["Node_B", "Node_D"])
        replaced = _prepare_partial_messages(
            old_messages, [edited], "REPLACE", "REPLACE", "REPLACE",
        )[0]
        self.assertEqual(replaced["rx_targets"], ["Node_F"])

        upload = UploadFile(
            filename="partner.json",
            file=io.BytesIO(json.dumps(pack, ensure_ascii=False).encode("utf-8")),
        )
        result = asyncio.run(apply_partial_update(
            self.project.id, file=upload, selected_names='["T_SENT"]',
            field_mode="REPLACE", protocol_mode="REPLACE", relation_mode="PARTIAL",
            db=self.db, current_user=self.user,
        ))
        self.assertEqual(result["updated_count"], 1)
        updated = next(m for m in _load_existing_messages(self.db, self.project.id) if m.id == self.sent.id)
        self.assertEqual({n.name for n in updated.tx_targets}, {"Node_A", "Node_C"})
        self.assertEqual({n.name for n in updated.rx_targets}, {"Node_D", "Node_F"})
        self.assertIsNotNone(self.db.query(IntegrationTarget).filter_by(project_id=self.project.id, name="Node_F").first())
        # Reapplying the same delta must not add duplicate nodes or relationships.
        same_again = _prepare_partial_messages(
            _load_existing_messages(self.db, self.project.id), [edited],
            "REPLACE", "REPLACE", "PARTIAL", baseline,
        )[0]
        self.assertEqual(same_again["rx_targets"], ["Node_D", "Node_F"])



if __name__ == "__main__":
    unittest.main()
