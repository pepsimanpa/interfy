import os
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect
from .database import Base, engine, SessionLocal
from .models import User, UserRole, Project, Message, MessageField
from .auth import hash_password
from .schemas import SUPPORTED_TYPES
from .routers import auth, projects, messages, groups, export, history, backups, project_json, partial_update, labels, integration_targets

app = FastAPI(title="Interfy", version="0.1.0")


def to_default_acronym(name: str) -> str:
    chars = []
    for ch in (name or "PROJECT"):
        if ch.isascii() and ch.isalnum():
            chars.append(ch.upper())
        elif ch == "_":
            chars.append("_")
    value = "".join(chars).strip("_") or "PROJECT"
    if not value[0].isalpha():
        value = "P_" + value
    return value[:40]

def _column_exists(conn, table_name: str, column_name: str) -> bool:
    try:
        return column_name in {column["name"] for column in inspect(conn).get_columns(table_name)}
    except Exception:
        return False


def _add_column_if_missing(conn, table_name: str, column_name: str, column_definition: str) -> None:
    if not _column_exists(conn, table_name, column_name):
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}"))


def apply_lightweight_migrations():
    with engine.begin() as conn:
        dialect = conn.dialect.name

        # SQLAlchemy create_all() creates missing tables, but existing deployments may
        # need small additive migrations. Avoid PostgreSQL-only IF NOT EXISTS syntax
        # so the default SQLite dev database can also start normally.
        _add_column_if_missing(conn, "projects", "acronym", "acronym VARCHAR(40)")
        _add_column_if_missing(conn, "messages", "order_index", "order_index INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "messages", "definition_type", "definition_type VARCHAR(20) DEFAULT 'STRUCT' NOT NULL")
        _add_column_if_missing(conn, "messages", "infocode", "infocode VARCHAR(60)")
        _add_column_if_missing(conn, "messages", "struct_name", "struct_name VARCHAR(120)")
        _add_column_if_missing(conn, "messages", "protocol", "protocol VARCHAR(120)")
        _add_column_if_missing(conn, "messages", "enum_underlying_type", "enum_underlying_type VARCHAR(20) DEFAULT 'uint32' NOT NULL")
        _add_column_if_missing(conn, "message_fields", "type_kind", "type_kind VARCHAR(20) DEFAULT 'BASIC' NOT NULL")
        _add_column_if_missing(conn, "message_fields", "ref_message_id", "ref_message_id INTEGER NULL REFERENCES messages(id)")
        _add_column_if_missing(conn, "message_fields", "array_dimensions", "array_dimensions VARCHAR(255)")
        _add_column_if_missing(conn, "message_fields", "variable_name", "variable_name VARCHAR(120)")
        _add_column_if_missing(conn, "message_fields", "purpose", "purpose TEXT")
        _add_column_if_missing(conn, "message_fields", "value_range", "value_range VARCHAR(255)")
        _add_column_if_missing(conn, "message_fields", "unit", "unit VARCHAR(120)")
        _add_column_if_missing(conn, "message_fields", "note", "note TEXT")
        _add_column_if_missing(conn, "users", "is_deleted", "is_deleted BOOLEAN DEFAULT FALSE NOT NULL")
        _add_column_if_missing(conn, "users", "display_name", "display_name VARCHAR(255)")
        _add_column_if_missing(conn, "project_backups", "kind", "kind VARCHAR(40) DEFAULT 'MANUAL' NOT NULL")
        _add_column_if_missing(conn, "project_backups", "source_backup_id", "source_backup_id INTEGER NULL REFERENCES project_backups(id)")
        _add_column_if_missing(conn, "project_backups", "message_count", "message_count INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing(conn, "project_backups", "field_count", "field_count INTEGER DEFAULT 0 NOT NULL")
        _add_column_if_missing(conn, "project_backups", "note", "note TEXT")
        _add_column_if_missing(conn, "message_group_items", "order_index", "order_index INTEGER DEFAULT 0 NOT NULL")

        if dialect == "postgresql":
            # The messages.name column is now a human-readable message purpose.
            # It may be duplicated; the actual unique type name remains messages.struct_name.
            conn.execute(text("ALTER TABLE messages DROP CONSTRAINT IF EXISTS uq_project_message_name"))
            try:
                conn.execute(text("ALTER TYPE changetype ADD VALUE IF NOT EXISTS 'RESTORE'"))
            except Exception:
                # Fresh databases or VARCHAR-backed enums do not need this migration.
                pass
            conn.execute(text("""
                UPDATE users
                SET display_name = CASE
                    WHEN email LIKE 'deleted_user_%@deleted.local' THEN CONCAT('탈퇴 사용자 #', id)
                    ELSE email
                END
                WHERE display_name IS NULL OR display_name = ''
            """))
        else:
            conn.execute(text("""
                UPDATE users
                SET display_name = CASE
                    WHEN email LIKE 'deleted_user_%@deleted.local' THEN '탈퇴 사용자 #' || id
                    ELSE email
                END
                WHERE display_name IS NULL OR display_name = ''
            """))

def get_cors_origins():
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX", r"^https?://.*:3000$"),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    apply_lightweight_migrations()
    db: Session = SessionLocal()
    try:
        admin_email = os.getenv("ADMIN_EMAIL", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin1234")
        for project in db.query(Project).filter(Project.acronym.is_(None)).all():
            project.acronym = to_default_acronym(project.name)
        db.execute(text("UPDATE messages SET definition_type = 'STRUCT' WHERE definition_type IS NULL OR definition_type = ''"))
        db.execute(text("UPDATE messages SET struct_name = name WHERE struct_name IS NULL OR struct_name = ''"))
        db.execute(text("UPDATE messages SET infocode = NULL WHERE infocode = ''"))
        db.execute(text("UPDATE messages SET protocol = NULL WHERE protocol = ''"))
        db.execute(text("UPDATE messages SET enum_underlying_type = 'uint32' WHERE enum_underlying_type IS NULL OR enum_underlying_type = ''"))
        db.execute(text("UPDATE message_fields SET type_kind = 'BASIC' WHERE type_kind IS NULL OR type_kind = ''"))
        db.execute(text("UPDATE message_fields SET variable_name = name WHERE variable_name IS NULL OR variable_name = ''"))
        db.execute(text("UPDATE message_fields SET purpose = '' WHERE purpose IS NULL"))
        # Field model normalization (2026-07): the generated member identifier is now
        # the single user-facing field name. Preserve the old display name by folding
        # it into purpose once, then keep the legacy variable_name column mirrored.
        used_field_names: dict[int, set[str]] = {}
        fields_for_migration = db.query(MessageField).order_by(MessageField.message_id.asc(), MessageField.order_index.asc(), MessageField.id.asc()).all()
        for field in fields_for_migration:
            old_display_name = str(field.name or "").strip()
            legacy_variable_name = str(field.variable_name or "").strip()
            if re.fullmatch(r"^[A-Za-z_][A-Za-z0-9_]*$", legacy_variable_name):
                base_name = legacy_variable_name
            elif re.fullmatch(r"^[A-Za-z_][A-Za-z0-9_]*$", old_display_name):
                base_name = old_display_name
            else:
                base_name = f"field_{field.id}"

            used_names = used_field_names.setdefault(field.message_id, set())
            field_name = base_name[:120]
            suffix_number = 2
            while field_name.lower() in used_names:
                suffix = f"_{suffix_number}"
                field_name = f"{base_name[:120 - len(suffix)]}{suffix}"
                suffix_number += 1
            used_names.add(field_name.lower())

            if old_display_name and old_display_name != field_name:
                current_purpose = str(field.purpose or "").strip()
                if not current_purpose:
                    field.purpose = old_display_name
                elif old_display_name.lower() not in current_purpose.lower():
                    field.purpose = f"{old_display_name} - {current_purpose}"

            field.name = field_name
            field.variable_name = field_name
        db.execute(text("UPDATE message_fields SET value_range = '' WHERE value_range IS NULL"))
        db.execute(text("UPDATE message_fields SET unit = '' WHERE unit IS NULL"))
        db.execute(text("UPDATE message_fields SET note = description WHERE (note IS NULL OR note = '') AND description IS NOT NULL AND description != ''"))
        db.execute(text("UPDATE message_fields SET note = '' WHERE note IS NULL"))
        # Convert old single-dimension array_size data into the new comma-separated
        # array_dimensions model. Existing string fields are migrated to char arrays
        # because Interfy now represents strings as char + array dimensions.
        db.execute(text("""
            UPDATE message_fields
            SET array_dimensions = CAST(array_size AS VARCHAR)
            WHERE (array_dimensions IS NULL OR array_dimensions = '')
              AND is_array = TRUE
              AND array_size IS NOT NULL
              AND array_size > 0
        """))
        db.execute(text("""
            UPDATE message_fields
            SET type = 'char',
                is_array = TRUE,
                array_dimensions = CASE
                    WHEN array_dimensions IS NOT NULL AND array_dimensions != '' THEN array_dimensions
                    WHEN is_array = TRUE AND array_size IS NOT NULL AND array_size > 0 THEN CAST(array_size AS VARCHAR)
                    ELSE '256'
                END,
                array_size = CASE
                    WHEN array_size IS NOT NULL AND array_size > 0 THEN array_size
                    ELSE 256
                END
            WHERE type_kind = 'BASIC'
              AND type = 'string'
        """))
        db.commit()
        for project in db.query(Project).all():
            ordered_messages = db.query(Message).filter_by(project_id=project.id).order_by(Message.order_index.asc(), Message.id.asc()).all()
            for idx, message in enumerate(ordered_messages, start=1):
                if not message.order_index:
                    message.order_index = idx
        db.commit()

        # Existing group-message links did not have an explicit order in older versions.
        # Initialize empty/zero order values so each group can be reordered independently.
        from .models import MessageGroup, MessageGroupItem
        for group in db.query(MessageGroup).all():
            ordered_items = db.query(MessageGroupItem).filter_by(group_id=group.id).order_by(MessageGroupItem.order_index.asc(), MessageGroupItem.id.asc()).all()
            for idx, item in enumerate(ordered_items, start=1):
                if not item.order_index:
                    item.order_index = idx
        db.commit()

        # Version 2026-06: 송신/수신은 라벨에서 별도 연동 대상으로 분리되었습니다.
        # Existing tx/rx label assignments are copied once into integration targets so
        # older data remains visible after upgrade. The label classification itself remains intact.
        from .models import IntegrationTarget, MessageTxTargetItem, MessageRxTargetItem, MessageLabel, MessageTxLabelItem, MessageRxLabelItem
        for legacy_item_model, target_item_model in ((MessageTxLabelItem, MessageTxTargetItem), (MessageRxLabelItem, MessageRxTargetItem)):
            legacy_items = db.query(legacy_item_model).all()
            for legacy_item in legacy_items:
                label = db.get(MessageLabel, legacy_item.label_id)
                message = db.get(Message, legacy_item.message_id)
                if not label or not message or label.project_id != message.project_id:
                    continue
                target = db.query(IntegrationTarget).filter(IntegrationTarget.project_id == message.project_id, IntegrationTarget.name == label.name).first()
                if target is None:
                    target = IntegrationTarget(project_id=message.project_id, name=label.name, description=label.description or "")
                    db.add(target)
                    db.flush()
                exists = db.query(target_item_model).filter(target_item_model.message_id == message.id, target_item_model.target_id == target.id).first()
                if exists is None:
                    db.add(target_item_model(message_id=message.id, target_id=target.id))
        db.commit()
        admin = db.query(User).filter(User.email == admin_email).first()
        if not admin:
            db.add(User(email=admin_email, display_name=admin_email, password_hash=hash_password(admin_password), role=UserRole.ADMIN))
            db.commit()
    finally:
        db.close()

@app.get("/")
def root():
    return {"service": "Interfy API", "docs": "/docs"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/meta/types")
def supported_types():
    return {"types": SUPPORTED_TYPES}

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(messages.router)
app.include_router(groups.router)
app.include_router(export.router)
app.include_router(history.router)
app.include_router(backups.router)
app.include_router(project_json.router)
app.include_router(partial_update.router)
app.include_router(labels.router)
app.include_router(integration_targets.router)
