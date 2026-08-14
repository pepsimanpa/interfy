from datetime import datetime
from enum import Enum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum as SAEnum, UniqueConstraint, JSON
from sqlalchemy.orm import relationship
from .database import Base

BASIC_TYPE_BYTE_SIZES = {
    "bool": 1,
    "char": 1,
    "int8": 1,
    "uint8": 1,
    "int16": 2,
    "uint16": 2,
    "int32": 4,
    "uint32": 4,
    "int64": 8,
    "uint64": 8,
    "float": 4,
    "double": 8,
}

def _array_dimension_values(array_dimensions, is_array=False, array_size=None):
    dimensions = array_dimensions
    if not dimensions and is_array and array_size:
        dimensions = str(array_size)
    if not dimensions:
        return []
    values = []
    for part in str(dimensions).split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            values.append(int(part))
    return values

def _array_multiplier(array_dimensions, is_array=False, array_size=None):
    total = 1
    for value in _array_dimension_values(array_dimensions, is_array, array_size):
        total *= value
    return total

class UserRole(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"

class ChangeType(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    FIELD_CREATE = "FIELD_CREATE"
    FIELD_UPDATE = "FIELD_UPDATE"
    FIELD_DELETE = "FIELD_DELETE"
    GROUP_CREATE = "GROUP_CREATE"
    GROUP_UPDATE = "GROUP_UPDATE"
    GROUP_DELETE = "GROUP_DELETE"
    RESTORE = "RESTORE"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    display_name = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.USER, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    acronym = Column(String(40), nullable=True)
    description = Column(Text, default="")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    owner = relationship("User")
    messages = relationship("Message", back_populates="project", cascade="all, delete-orphan", order_by="Message.order_index")
    groups = relationship("MessageGroup", back_populates="project", cascade="all, delete-orphan")
    labels = relationship("MessageLabel", back_populates="project", cascade="all, delete-orphan")
    integration_targets = relationship("IntegrationTarget", back_populates="project", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    # name: user-facing message purpose, struct_name: actual message/Enum type name used for code generation
    name = Column(String(120), nullable=False)
    struct_name = Column(String(120), nullable=True)
    period = Column(String(60), nullable=False)
    description = Column(Text, default="")
    infocode = Column(String(60), nullable=True)
    protocol = Column(String(120), nullable=True)
    definition_type = Column(String(20), default="STRUCT", nullable=False)
    enum_underlying_type = Column(String(20), default="uint32", nullable=False)
    version = Column(Integer, default=1, nullable=False)
    order_index = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @property
    def size_bytes(self):
        if (self.definition_type or "STRUCT").upper() == "ENUM":
            return BASIC_TYPE_BYTE_SIZES.get(self.enum_underlying_type or "uint32", 4)
        return sum((getattr(field, "size_bytes", 0) or 0) for field in (self.fields or []))

    project = relationship("Project", back_populates="messages")
    fields = relationship("MessageField", back_populates="message", cascade="all, delete-orphan", order_by="MessageField.order_index", foreign_keys="MessageField.message_id")
    enum_values = relationship("MessageEnumValue", back_populates="message", cascade="all, delete-orphan", order_by="MessageEnumValue.order_index")
    label_items = relationship("MessageLabelItem", back_populates="message", cascade="all, delete-orphan")
    labels = relationship("MessageLabel", secondary="message_label_items", viewonly=True, order_by="MessageLabel.name")
    # Legacy tx/rx label relationships are kept for DB compatibility with older versions.
    tx_label_items = relationship("MessageTxLabelItem", back_populates="message", cascade="all, delete-orphan")
    rx_label_items = relationship("MessageRxLabelItem", back_populates="message", cascade="all, delete-orphan")
    tx_labels = relationship("MessageLabel", secondary="message_tx_label_items", viewonly=True, order_by="MessageLabel.name")
    rx_labels = relationship("MessageLabel", secondary="message_rx_label_items", viewonly=True, order_by="MessageLabel.name")
    tx_target_items = relationship("MessageTxTargetItem", back_populates="message", cascade="all, delete-orphan")
    rx_target_items = relationship("MessageRxTargetItem", back_populates="message", cascade="all, delete-orphan")
    tx_targets = relationship("IntegrationTarget", secondary="message_tx_target_items", viewonly=True, order_by="IntegrationTarget.name")
    rx_targets = relationship("IntegrationTarget", secondary="message_rx_target_items", viewonly=True, order_by="IntegrationTarget.name")

class MessageLabel(Base):
    __tablename__ = "message_labels"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_label_name"),)
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="labels")
    items = relationship("MessageLabelItem", back_populates="label", cascade="all, delete-orphan")

class MessageLabelItem(Base):
    __tablename__ = "message_label_items"
    __table_args__ = (UniqueConstraint("label_id", "message_id", name="uq_label_message"),)
    id = Column(Integer, primary_key=True, index=True)
    label_id = Column(Integer, ForeignKey("message_labels.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    label = relationship("MessageLabel", back_populates="items")
    message = relationship("Message", back_populates="label_items")

class MessageTxLabelItem(Base):
    __tablename__ = "message_tx_label_items"
    __table_args__ = (UniqueConstraint("label_id", "message_id", name="uq_tx_label_message"),)
    id = Column(Integer, primary_key=True, index=True)
    label_id = Column(Integer, ForeignKey("message_labels.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    label = relationship("MessageLabel")
    message = relationship("Message", back_populates="tx_label_items")

class MessageRxLabelItem(Base):
    __tablename__ = "message_rx_label_items"
    __table_args__ = (UniqueConstraint("label_id", "message_id", name="uq_rx_label_message"),)
    id = Column(Integer, primary_key=True, index=True)
    label_id = Column(Integer, ForeignKey("message_labels.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    label = relationship("MessageLabel")
    message = relationship("Message", back_populates="rx_label_items")

class IntegrationTarget(Base):
    __tablename__ = "integration_targets"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_integration_target_name"),)
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="integration_targets")
    tx_items = relationship("MessageTxTargetItem", back_populates="target", cascade="all, delete-orphan")
    rx_items = relationship("MessageRxTargetItem", back_populates="target", cascade="all, delete-orphan")

class MessageTxTargetItem(Base):
    __tablename__ = "message_tx_target_items"
    __table_args__ = (UniqueConstraint("target_id", "message_id", name="uq_tx_target_message"),)
    id = Column(Integer, primary_key=True, index=True)
    target_id = Column(Integer, ForeignKey("integration_targets.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    target = relationship("IntegrationTarget", back_populates="tx_items")
    message = relationship("Message", back_populates="tx_target_items")

class MessageRxTargetItem(Base):
    __tablename__ = "message_rx_target_items"
    __table_args__ = (UniqueConstraint("target_id", "message_id", name="uq_rx_target_message"),)
    id = Column(Integer, primary_key=True, index=True)
    target_id = Column(Integer, ForeignKey("integration_targets.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    target = relationship("IntegrationTarget", back_populates="rx_items")
    message = relationship("Message", back_populates="rx_target_items")

class MessageEnumValue(Base):
    __tablename__ = "message_enum_values"
    __table_args__ = (
        UniqueConstraint("message_id", "name", name="uq_enum_value_name"),
        UniqueConstraint("message_id", "value", name="uq_enum_value_value"),
    )
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    name = Column(String(120), nullable=False)
    value = Column(Integer, nullable=False)
    description = Column(Text, default="")
    order_index = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    message = relationship("Message", back_populates="enum_values")

class MessageField(Base):
    __tablename__ = "message_fields"
    __table_args__ = (UniqueConstraint("message_id", "name", name="uq_message_field_name"),)
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    type = Column(String(120), nullable=False)
    type_kind = Column(String(20), default="BASIC", nullable=False)
    ref_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    # name: actual field/member name. variable_name is kept as a legacy compatibility alias and mirrors name.
    name = Column(String(120), nullable=False)
    variable_name = Column(String(120), nullable=True)
    description = Column(Text, default="")
    purpose = Column(Text, default="")
    value_range = Column(String(255), default="")
    unit = Column(String(120), default="")
    note = Column(Text, default="")
    is_array = Column(Boolean, default=False, nullable=False)
    array_size = Column(Integer, nullable=True)
    array_dimensions = Column(String(255), nullable=True)
    order_index = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @property
    def size_bytes(self):
        type_kind = (self.type_kind or "BASIC").upper()
        if type_kind in {"MESSAGE", "ENUM"} and self.ref_message is not None:
            base_size = getattr(self.ref_message, "size_bytes", 0) or 0
        else:
            base_size = BASIC_TYPE_BYTE_SIZES.get(self.type, 0)
        return base_size * _array_multiplier(self.array_dimensions, self.is_array, self.array_size)

    message = relationship("Message", back_populates="fields", foreign_keys=[message_id])
    ref_message = relationship("Message", foreign_keys=[ref_message_id])

    @property
    def ref_message_name(self):
        return (self.ref_message.struct_name or self.ref_message.name) if self.ref_message is not None else None

class MessageGroup(Base):
    __tablename__ = "message_groups"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_group_name"),)
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="groups")
    items = relationship("MessageGroupItem", back_populates="group", cascade="all, delete-orphan")

class MessageGroupItem(Base):
    __tablename__ = "message_group_items"
    __table_args__ = (UniqueConstraint("group_id", "message_id", name="uq_group_message"),)
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("message_groups.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    order_index = Column(Integer, default=0, nullable=False)

    group = relationship("MessageGroup", back_populates="items")
    message = relationship("Message")

class MessageChangeHistory(Base):
    __tablename__ = "message_change_histories"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    change_type = Column(SAEnum(ChangeType), nullable=False)
    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")
    message = relationship("Message")

class ProjectBackup(Base):
    __tablename__ = "project_backups"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    snapshot_json = Column(JSON, nullable=False)
    kind = Column(String(40), default="MANUAL", nullable=False)
    source_backup_id = Column(Integer, ForeignKey("project_backups.id"), nullable=True)
    message_count = Column(Integer, default=0, nullable=False)
    field_count = Column(Integer, default=0, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("Project")
    user = relationship("User", foreign_keys=[created_by])

class ProjectBackupEvent(Base):
    __tablename__ = "project_backup_events"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    event_type = Column(String(40), nullable=False)
    backup_id = Column(Integer, ForeignKey("project_backups.id"), nullable=True)
    auto_backup_id = Column(Integer, ForeignKey("project_backups.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("Project")
    backup = relationship("ProjectBackup", foreign_keys=[backup_id])
    auto_backup = relationship("ProjectBackup", foreign_keys=[auto_backup_id])
    user = relationship("User", foreign_keys=[created_by])
