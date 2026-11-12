"""User deletion and legacy soft-deleted user cleanup.

Accounts are removed from users entirely. Historical project activity and backup
attribution is frozen in text columns before clearing foreign-key references.
Callers own the transaction and must commit or roll back.
"""
from sqlalchemy.orm import Session

from .models import (
    User, UserRole, Project, MessageChangeHistory,
    ProjectBackup, ProjectBackupEvent,
)


def active_users_query(db: Session):
    # Legacy is_deleted is only retained to read pre-upgrade databases safely.
    return db.query(User).filter(User.is_deleted.is_(False))


def find_replacement_admin(db: Session, excluding_user_id: int | None = None) -> User | None:
    query = active_users_query(db).filter(User.role == UserRole.ADMIN)
    if excluding_user_id is not None:
        query = query.filter(User.id != excluding_user_id)
    return query.order_by(User.id.asc()).first()


def user_audit_name(user: User) -> str:
    if user.display_name:
        return user.display_name
    if user.email.startswith(("__deleted_user_", "deleted_user_")):
        return f"탈퇴 사용자 #{user.id}"
    return user.email


def permanently_delete_user(user: User, db: Session, replacement_admin: User) -> None:
    """Delete one account without removing projects, history, or backups."""
    if replacement_admin is None or replacement_admin.id == user.id:
        raise ValueError("계정 삭제에는 다른 관리자 계정이 필요합니다.")
    display_name = user_audit_name(user)

    # Existing projects stay available and are transferred to an active admin.
    db.query(Project).filter(Project.owner_id == user.id).update(
        {Project.owner_id: replacement_admin.id}, synchronize_session=False
    )

    # Do not attribute somebody else's actions to the replacement administrator.
    # Instead retain their display name and clear the foreign key to the user.
    for model, user_id_field, name_field in (
        (MessageChangeHistory, "changed_by", "changed_by_name"),
        (ProjectBackup, "created_by", "created_by_name"),
        (ProjectBackupEvent, "created_by", "created_by_name"),
    ):
        rows = db.query(model).filter(getattr(model, user_id_field) == user.id).all()
        for row in rows:
            if not getattr(row, name_field):
                setattr(row, name_field, display_name)
            setattr(row, user_id_field, None)

    db.flush()
    db.delete(user)
    db.flush()


def purge_legacy_deleted_users(db: Session) -> int:
    """One-time cleanup for accounts deleted by older Interfy versions."""
    users = db.query(User).filter(User.is_deleted.is_(True)).order_by(User.id).all()
    if not users:
        return 0
    admin = find_replacement_admin(db)
    if admin is None:
        raise ValueError("기존 삭제 계정 정리 전에 활성 관리자 계정이 필요합니다.")
    for user in users:
        permanently_delete_user(user, db, admin)
    return len(users)
