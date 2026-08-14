from datetime import datetime
import re
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from .models import UserRole, ChangeType
from .protocols import normalize_protocol_string

SUPPORTED_TYPES = [
    "bool", "char", "int8", "uint8", "int16", "uint16", "int32", "uint32",
    "int64", "uint64", "float", "double"
]
TYPE_KINDS = {"BASIC", "MESSAGE", "ENUM"}
DEFINITION_TYPES = {"STRUCT", "ENUM"}
ENUM_UNDERLYING_TYPES = ["int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64"]

IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
IDENTIFIER_ERROR = "영문, 숫자, _ 만 사용할 수 있으며 숫자로 시작할 수 없습니다."

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserCreate(BaseModel):
    email: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=3)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        value = (v or "").strip()
        if not value:
            raise ValueError("아이디를 입력하세요.")
        if value != "admin" and not re.fullmatch(r"\d{5}", value):
            raise ValueError("아이디는 사번으로 입력하세요.")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        value = str(v or "")
        if len(value) < 3:
            raise ValueError("패스워드는 3자리 이상으로 설정하세요.")
        return value

class UserRead(BaseModel):
    id: int
    email: str
    display_name: Optional[str] = None
    role: UserRole
    created_at: datetime
    model_config = {"from_attributes": True}


class UserRoleUpdate(BaseModel):
    role: UserRole

    @field_validator("role", mode="before")
    @classmethod
    def validate_role(cls, v):
        value = str(v or "").strip().upper()
        if value not in {"ADMIN", "USER"}:
            raise ValueError("권한은 ADMIN 또는 USER만 가능합니다.")
        return value

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    acronym: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    description: str = ""

class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    acronym: Optional[str] = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    description: Optional[str] = None

class ProjectRead(BaseModel):
    id: int
    name: str
    acronym: Optional[str] = None
    description: str
    owner_id: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class MessageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    struct_name: str = Field(min_length=1, max_length=120, pattern=IDENTIFIER_PATTERN)
    period: str = Field(default="", max_length=60)
    description: str = ""
    infocode: Optional[str] = None
    protocol: Optional[str] = None
    tx_label_ids: list[int] = []
    rx_label_ids: list[int] = []
    tx_target_ids: list[int] = []
    rx_target_ids: list[int] = []
    definition_type: str = "STRUCT"
    enum_underlying_type: str = "uint32"
    label_ids: list[int] = []

    @field_validator("definition_type", mode="before")
    @classmethod
    def validate_definition_type(cls, v) -> str:
        value = str(v or "STRUCT").strip().upper()
        if value not in DEFINITION_TYPES:
            raise ValueError("정의 유형은 메시지 또는 Enum만 가능합니다.")
        return value

    @field_validator("enum_underlying_type", mode="before")
    @classmethod
    def validate_enum_underlying_type(cls, v) -> str:
        value = str(v or "uint32").strip()
        if value not in ENUM_UNDERLYING_TYPES:
            raise ValueError("Enum 기본 자료형은 정수형만 가능합니다.")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("메시지 용도를 입력하세요.")
        return v.strip()

    @field_validator("struct_name")
    @classmethod
    def validate_struct_name(cls, v: str) -> str:
        value = str(v or "").strip()
        if not value:
            raise ValueError("메시지 이름을 입력하세요.")
        return value

    @field_validator("protocol", mode="before")
    @classmethod
    def validate_protocol(cls, v) -> Optional[str]:
        return normalize_protocol_string(v)

    @field_validator("period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        value = str(v or "").strip()
        if value == "" or value == "0" or value == "비주기":
            return ""
        if not value.isdigit():
            raise ValueError("주기는 숫자만 입력할 수 있습니다.")
        return value

    @field_validator("infocode", mode="before")
    @classmethod
    def validate_infocode(cls, v) -> Optional[str]:
        if v is None:
            return None
        value = str(v or "").strip()
        if value == "":
            return None
        if not value.isdigit():
            raise ValueError("정보코드는 숫자만 입력할 수 있습니다.")
        return value

class MessageUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    struct_name: Optional[str] = Field(default=None, min_length=1, max_length=120, pattern=IDENTIFIER_PATTERN)
    period: Optional[str] = Field(default=None, max_length=60)
    description: Optional[str] = None
    infocode: Optional[str] = None
    protocol: Optional[str] = None
    enum_underlying_type: Optional[str] = None

    @field_validator("infocode", mode="before")
    @classmethod
    def validate_infocode(cls, v) -> Optional[str]:
        if v is None:
            return None
        value = str(v or "").strip()
        if value == "":
            return None
        if not value.isdigit():
            raise ValueError("정보코드는 숫자만 입력할 수 있습니다.")
        return value

    @field_validator("enum_underlying_type", mode="before")
    @classmethod
    def validate_enum_underlying_type(cls, v) -> Optional[str]:
        if v is None:
            return None
        value = str(v or "").strip()
        if value not in ENUM_UNDERLYING_TYPES:
            raise ValueError("Enum 기본 자료형은 정수형만 가능합니다.")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError("메시지 용도를 입력하세요.")
            return v.strip()
        return v

    @field_validator("struct_name")
    @classmethod
    def validate_struct_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            value = str(v or "").strip()
            if not value:
                raise ValueError("메시지 이름을 입력하세요.")
            return value
        return v

    @field_validator("protocol", mode="before")
    @classmethod
    def validate_protocol(cls, v) -> Optional[str]:
        if v is None:
            return None
        return normalize_protocol_string(v)

    @field_validator("period")
    @classmethod
    def validate_period(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = str(v or "").strip()
        if value == "" or value == "0" or value == "비주기":
            return ""
        if not value.isdigit():
            raise ValueError("주기는 숫자만 입력할 수 있습니다.")
        return value

class FieldCreate(BaseModel):
    type: str = "uint32"
    type_kind: str = "BASIC"
    ref_message_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=120, pattern=IDENTIFIER_PATTERN)
    variable_name: str = Field(min_length=1, max_length=120, pattern=IDENTIFIER_PATTERN)
    description: str = ""
    purpose: str = ""
    value_range: str = ""
    unit: str = ""
    note: str = ""
    is_array: bool = False
    array_size: Optional[int] = None
    array_dimensions: Optional[str] = None
    order_index: int = 0

    @field_validator("type_kind", mode="before")
    @classmethod
    def validate_type_kind(cls, v) -> str:
        value = str(v or "BASIC").strip().upper()
        if value not in TYPE_KINDS:
            raise ValueError("자료형 종류는 BASIC, MESSAGE 또는 ENUM만 가능합니다.")
        return value

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        value = str(v or "").strip()
        if not value:
            raise ValueError("자료형을 선택하세요.")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("필드 이름을 입력하세요.")
        return v.strip()

    @field_validator("variable_name")
    @classmethod
    def validate_variable_name(cls, v: str) -> str:
        value = str(v or "").strip()
        if not value:
            raise ValueError("필드 이름을 입력하세요.")
        return value

    @field_validator("array_size")
    @classmethod
    def validate_array_size(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("array_size must be greater than 0")
        return v

    @field_validator("array_dimensions")
    @classmethod
    def validate_array_dimensions(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = str(v or "").strip()
        if value == "":
            return None
        if value == "0":
            return value
        parts = [part.strip() for part in value.split(",")]
        if not parts or any(part == "" or not part.isdigit() or int(part) <= 0 for part in parts):
            raise ValueError("배열 크기는 빈칸, 0, 또는 10 / 3,4 형식으로 입력하세요.")
        return ",".join(str(int(part)) for part in parts)

    @model_validator(mode="after")
    def validate_type_payload(self):
        if self.type_kind == "BASIC":
            if self.type not in SUPPORTED_TYPES:
                raise ValueError(f"Unsupported type: {self.type}")
            self.ref_message_id = None
        else:
            if self.ref_message_id is None:
                raise ValueError("자료형을 선택하세요.")
        return self

class FieldBulkSaveItem(FieldCreate):
    id: Optional[int] = None

class FieldBulkSave(BaseModel):
    fields: list[FieldBulkSaveItem] = []

class FieldReorder(BaseModel):
    field_ids: list[int]

class MessageReorder(BaseModel):
    message_ids: list[int]

class FieldUpdate(BaseModel):
    type: Optional[str] = None
    type_kind: Optional[str] = None
    ref_message_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=120, pattern=IDENTIFIER_PATTERN)
    variable_name: Optional[str] = Field(default=None, min_length=1, max_length=120, pattern=IDENTIFIER_PATTERN)
    description: Optional[str] = None
    purpose: Optional[str] = None
    value_range: Optional[str] = None
    unit: Optional[str] = None
    note: Optional[str] = None
    is_array: Optional[bool] = None
    array_size: Optional[int] = None
    array_dimensions: Optional[str] = None
    order_index: Optional[int] = None

    @field_validator("type_kind", mode="before")
    @classmethod
    def validate_type_kind(cls, v) -> Optional[str]:
        if v is None:
            return None
        value = str(v or "").strip().upper()
        if value not in TYPE_KINDS:
            raise ValueError("자료형 종류는 BASIC, MESSAGE 또는 ENUM만 가능합니다.")
        return value

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not str(v).strip():
            raise ValueError("자료형을 선택하세요.")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError("필드 이름을 입력하세요.")
            return v.strip()
        return v

    @field_validator("variable_name")
    @classmethod
    def validate_variable_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            value = str(v or "").strip()
            if not value:
                raise ValueError("필드 이름을 입력하세요.")
            return value
        return v

class EnumValueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=IDENTIFIER_PATTERN)
    value: int
    description: str = ""
    order_index: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Enum 값 이름을 입력하세요.")
        return v.strip()

class EnumValueBulkSaveItem(EnumValueCreate):
    id: Optional[int] = None

class EnumValueBulkSave(BaseModel):
    values: list[EnumValueBulkSaveItem] = []

class EnumValueRead(BaseModel):
    id: int
    message_id: int
    name: str
    value: int
    description: str
    order_index: int
    size_bytes: int = 0
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        value = str(v or "").strip()
        if not value:
            raise ValueError("라벨 이름을 입력하세요.")
        return value

class LabelUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = str(v or "").strip()
        if not value:
            raise ValueError("라벨 이름을 입력하세요.")
        return value

class LabelRead(BaseModel):
    id: int
    project_id: int
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class MessageLabelAssign(BaseModel):
    label_ids: list[int] = []
    # Legacy fields retained for backward compatibility. 송신/수신은 IntegrationTarget을 사용합니다.
    tx_label_ids: Optional[list[int]] = None
    rx_label_ids: Optional[list[int]] = None

class IntegrationTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        value = str(v or "").strip()
        if not value:
            raise ValueError("노드 이름을 입력하세요.")
        return value

class IntegrationTargetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        value = str(v or "").strip()
        if not value:
            raise ValueError("노드 이름을 입력하세요.")
        return value

class IntegrationTargetRead(BaseModel):
    id: int
    project_id: int
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class MessageIntegrationTargetAssign(BaseModel):
    tx_target_ids: list[int] = []
    rx_target_ids: list[int] = []

class FieldRead(BaseModel):
    id: int
    message_id: int
    type: str
    type_kind: str = "BASIC"
    ref_message_id: Optional[int] = None
    ref_message_name: Optional[str] = None
    name: str
    variable_name: Optional[str] = None
    description: str
    purpose: str = ""
    value_range: str = ""
    unit: str = ""
    note: str = ""
    is_array: bool
    array_size: Optional[int]
    array_dimensions: Optional[str] = None
    order_index: int
    size_bytes: int = 0
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class MessageRead(BaseModel):
    id: int
    project_id: int
    name: str
    struct_name: Optional[str] = None
    period: str
    description: str
    infocode: Optional[str] = None
    protocol: Optional[str] = None
    definition_type: str = "STRUCT"
    enum_underlying_type: str = "uint32"
    version: int
    order_index: int
    size_bytes: int = 0
    created_at: datetime
    updated_at: datetime
    fields: list[FieldRead] = []
    enum_values: list[EnumValueRead] = []
    labels: list[LabelRead] = []
    tx_labels: list[LabelRead] = []
    rx_labels: list[LabelRead] = []
    tx_targets: list[IntegrationTargetRead] = []
    rx_targets: list[IntegrationTargetRead] = []
    model_config = {"from_attributes": True}

class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""

class GroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None


class GroupMessageReorder(BaseModel):
    message_ids: list[int]

class GroupRead(BaseModel):
    id: int
    project_id: int
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    message_ids: list[int] = []

class HistoryRead(BaseModel):
    id: int
    message_id: Optional[int]
    message_name: Optional[str] = None
    project_id: int
    changed_by: int
    changed_by_name: Optional[str] = None
    change_type: ChangeType
    before_json: Optional[Any]
    after_json: Optional[Any]
    created_at: datetime
    model_config = {"from_attributes": True}


class BackupCreate(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, v):
        value = str(v or "").strip()
        return value or None


class BackupRead(BaseModel):
    id: int
    project_id: int
    created_by: int
    created_by_name: Optional[str] = None
    kind: str = "MANUAL"
    source_backup_id: Optional[int] = None
    message_count: int
    field_count: int
    note: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}

class BackupEventRead(BaseModel):
    id: int
    project_id: int
    event_type: str
    backup_id: Optional[int] = None
    auto_backup_id: Optional[int] = None
    created_by: int
    created_by_name: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}
