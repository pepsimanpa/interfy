"""Deleted employee login IDs can be reused without merging historical accounts.

Run from backend/: python -m unittest tests/test_account_reregistration.py -v
"""
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import verify_password
from app.database import Base
from app.models import Project, User, UserRole
from app.routers.auth import deleted_user_email, register, soft_delete_user
from app.schemas import UserCreate


class AccountReregistrationTests(unittest.TestCase):
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
        self.admin = User(email="admin", password_hash="old-hash", role=UserRole.ADMIN)
        self.db.add(self.admin)
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_delete_releases_login_id_and_keeps_history_identity(self):
        old = User(email="12345", password_hash="old-hash", role=UserRole.USER)
        self.db.add(old)
        self.db.flush()
        old_id = old.id
        project = Project(name="Existing", acronym="EXISTING", owner_id=old_id)
        self.db.add(project)
        self.db.commit()

        soft_delete_user(old, self.db, self.admin)
        self.db.commit()
        self.assertTrue(old.is_deleted)
        self.assertEqual(old.email, deleted_user_email(old))
        self.assertEqual(old.display_name, "12345")
        self.assertEqual(project.owner_id, self.admin.id)

        new = register(UserCreate(email="12345", password="newpass"), db=self.db)
        self.assertNotEqual(new.id, old_id)
        self.assertEqual(new.email, "12345")
        self.assertEqual(new.role, UserRole.USER)
        self.assertTrue(verify_password("newpass", new.password_hash))
        self.assertEqual(self.db.get(User, old_id).display_name, "12345")
        self.assertTrue(self.db.get(User, old_id).is_deleted)
        self.assertEqual(self.db.get(Project, project.id).owner_id, self.admin.id)

    def test_legacy_deleted_account_with_held_login_id_can_reregister(self):
        old = User(email="23456", display_name=None, password_hash="old-hash",
                   is_deleted=True, role=UserRole.USER)
        self.db.add(old)
        self.db.commit()
        old_id = old.id

        new = register(UserCreate(email="23456", password="password"), db=self.db)
        self.assertNotEqual(new.id, old_id)
        self.assertEqual(new.email, "23456")
        self.assertFalse(new.is_deleted)
        self.assertEqual(old.email, deleted_user_email(old))
        self.assertEqual(old.display_name, "23456")
        self.assertTrue(old.is_deleted)

    def test_existing_active_user_still_blocks_duplicate_registration(self):
        first = register(UserCreate(email="34567", password="initial"), db=self.db)
        with self.assertRaises(HTTPException) as error:
            register(UserCreate(email="34567", password="another"), db=self.db)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.query(User).filter(User.email == "34567").count(), 1)
        self.assertEqual(first.id, self.db.query(User).filter(User.email == "34567").one().id)

    def test_reregister_after_multiple_deletions_creates_distinct_audit_id(self):
        first = register(UserCreate(email="45678", password="password"), db=self.db)
        soft_delete_user(first, self.db, self.admin)
        self.db.commit()
        second = register(UserCreate(email="45678", password="password"), db=self.db)
        second_id = second.id
        soft_delete_user(second, self.db, self.admin)
        self.db.commit()
        third = register(UserCreate(email="45678", password="password"), db=self.db)
        self.assertEqual(len({first.id, second_id, third.id}), 3)
        self.assertNotEqual(first.email, second.email)
        self.assertEqual(third.email, "45678")


if __name__ == "__main__":
    unittest.main()
