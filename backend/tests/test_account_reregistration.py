"""Accounts are actually deleted, while projects/audit history survive.

Run from backend/: python -m unittest discover -s tests -v
"""
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import verify_password
from app.database import Base
from app.models import (
    MessageChangeHistory, Project, ProjectBackup, ProjectBackupEvent,
    User, UserRole, ChangeType,
)
from app.account_lifecycle import permanently_delete_user, purge_legacy_deleted_users
from app.routers.auth import delete_user, register, withdraw_me
from app.schemas import UserCreate


class AccountDeletionTests(unittest.TestCase):
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
        self.admin = User(email="admin", display_name="admin", password_hash="old-hash", role=UserRole.ADMIN)
        self.db.add(self.admin)
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def make_user_with_history(self, email="12345", deleted=False):
        user = User(email=email, display_name=email if not deleted else None,
                    password_hash="old-hash", role=UserRole.USER, is_deleted=deleted)
        self.db.add(user)
        self.db.flush()
        project = Project(name="Existing", acronym="EXISTING", owner_id=user.id)
        self.db.add(project)
        self.db.flush()
        history = MessageChangeHistory(
            project_id=project.id, changed_by=user.id, change_type=ChangeType.UPDATE,
        )
        backup = ProjectBackup(
            project_id=project.id, created_by=user.id,
            snapshot_json={"test": True},
        )
        self.db.add_all([history, backup])
        self.db.flush()
        event = ProjectBackupEvent(
            project_id=project.id, created_by=user.id,
            event_type="BACKUP", backup_id=backup.id,
        )
        self.db.add(event)
        self.db.commit()
        return user.id, project.id, history.id, backup.id, event.id

    def assert_audit_saved(self, user_id, project_id, history_id, backup_id, event_id, email="12345"):
        self.assertIsNone(self.db.get(User, user_id))
        self.assertEqual(self.db.get(Project, project_id).owner_id, self.admin.id)
        history = self.db.get(MessageChangeHistory, history_id)
        self.assertIsNone(history.changed_by)
        self.assertEqual(history.changed_by_name, email)
        backup = self.db.get(ProjectBackup, backup_id)
        self.assertIsNone(backup.created_by)
        self.assertEqual(backup.created_by_name, email)
        event = self.db.get(ProjectBackupEvent, event_id)
        self.assertIsNone(event.created_by)
        self.assertEqual(event.created_by_name, email)

    def test_admin_delete_is_permanent_and_preserves_projects_and_attribution(self):
        ids = self.make_user_with_history()
        user_id = ids[0]
        result = delete_user(user_id, db=self.db, current_user=self.admin)
        self.assertEqual(result, {"ok": True})
        self.assert_audit_saved(*ids)

        new = register(UserCreate(email="12345", password="newpass"), db=self.db)
        self.assertNotEqual(new.id, user_id)
        self.assertEqual(new.role, UserRole.USER)
        self.assertTrue(verify_password("newpass", new.password_hash))

    def test_legacy_deleted_account_can_reregister_and_old_row_is_purged(self):
        ids = self.make_user_with_history(email="23456", deleted=True)
        new = register(UserCreate(email="23456", password="password"), db=self.db)
        self.assertNotEqual(new.id, ids[0])
        self.assert_audit_saved(*ids, email="23456")

    def test_explicit_cleanup_removes_only_legacy_deleted_users(self):
        old = self.make_user_with_history(email="34567", deleted=True)
        active = register(UserCreate(email="45678", password="keepme"), db=self.db)
        self.assertEqual(purge_legacy_deleted_users(self.db), 1)
        self.db.commit()
        self.assert_audit_saved(*old, email="34567")
        self.assertIsNotNone(self.db.get(User, active.id))
        self.assertEqual(purge_legacy_deleted_users(self.db), 0)

    def test_active_duplicate_registration_is_blocked(self):
        first = register(UserCreate(email="56789", password="initial"), db=self.db)
        with self.assertRaises(HTTPException) as error:
            register(UserCreate(email="56789", password="another"), db=self.db)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.query(User).filter(User.email == "56789").count(), 1)
        self.assertEqual(first.id, self.db.query(User).filter(User.email == "56789").one().id)

    def test_self_withdrawal_removes_row(self):
        user = register(UserCreate(email="67890", password="password"), db=self.db)
        user_id = user.id
        self.assertEqual(withdraw_me(db=self.db, current_user=user), {"ok": True})
        self.assertIsNone(self.db.get(User, user_id))

    def test_repeated_delete_and_register_never_produces_inactive_rows(self):
        ids = []
        for _ in range(3):
            user = register(UserCreate(email="78901", password="password"), db=self.db)
            ids.append(user.id)
            permanently_delete_user(user, self.db, self.admin)
            self.db.commit()
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(self.db.query(User).filter(User.is_deleted.is_(True)).count(), 0)


if __name__ == "__main__":
    unittest.main()
