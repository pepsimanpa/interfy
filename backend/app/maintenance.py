"""One-time database maintenance. Run only after a verified PostgreSQL backup.

Usage (Rancher Desktop / Docker Engine):
  docker exec interfy-backend python -m app.maintenance purge-deleted-users
  docker exec interfy-backend python -m app.maintenance purge-deleted-users --apply

Preview is read-only. --apply permanently deletes previously soft-deleted user
rows, preserving projects and freezing historical author names.
"""
import argparse
import sys

from sqlalchemy import inspect

from .database import SessionLocal, engine
from .models import User
from .account_lifecycle import purge_legacy_deleted_users


def check_schema_ready() -> None:
    inspector = inspect(engine)
    for table, reference_column, archived_name in (
        ("message_change_histories", "changed_by", "changed_by_name"),
        ("project_backups", "created_by", "created_by_name"),
        ("project_backup_events", "created_by", "created_by_name"),
    ):
        columns = {item["name"]: item for item in inspector.get_columns(table)}
        if archived_name not in columns or not columns[reference_column]["nullable"]:
            raise RuntimeError(
                f"{table} 테이블의 삭제 계정 정리 마이그레이션이 필요합니다. "
                "먼저 업데이트된 백엔드를 정상 실행해 주세요."
            )


def main():
    parser = argparse.ArgumentParser(description="Clean up legacy deactivated Interfy accounts")
    parser.add_argument("action", choices=["purge-deleted-users"])
    parser.add_argument("--apply", action="store_true", help="Permanently delete these users")
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = db.query(User).filter(User.is_deleted.is_(True)).order_by(User.id).all()
        print(f"기존 비활성화(삭제) 계정: {len(rows)}건")
        if not rows:
            return 0
        print("대상 계정:", ", ".join(
            str(row.display_name or row.email) for row in rows
        ))
        if not args.apply:
            print("조회만 수행했습니다. 백업 완료 후 --apply를 추가하여 정리할 수 있습니다.")
            return 0

        try:
            check_schema_ready()
            removed = purge_legacy_deleted_users(db)
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"계정 정리 중단(변경사항 취소): {exc}", file=sys.stderr)
            return 1
        print(f"완료: {removed}개 계정을 실제 삭제했습니다. 프로젝트와 기존 이력은 보존됩니다.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
