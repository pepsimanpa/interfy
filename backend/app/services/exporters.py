import re
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:  # pragma: no cover
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception
from ..models import Message

C_TYPE_MAP = {
    "bool": "bool",
    "char": "char",
    "int8": "int8_t",
    "uint8": "uint8_t",
    "int16": "int16_t",
    "uint16": "uint16_t",
    "int32": "int32_t",
    "uint32": "uint32_t",
    "int64": "int64_t",
    "uint64": "uint64_t",
    "float": "float",
    "double": "double",
}

IDL_TYPE_MAP = {
    "bool": "boolean",
    "char": "char",
    "int8": "int8",
    "uint8": "octet",
    "int16": "short",
    "uint16": "unsigned short",
    "int32": "long",
    "uint32": "unsigned long",
    "int64": "long long",
    "uint64": "unsigned long long",
    "float": "float",
    "double": "double",
}

CSHARP_TYPE_MAP = {
    # bool and char are represented as one-byte values to keep binary layout
    # compatible with the generated C header.
    "bool": "byte",
    "char": "byte",
    "int8": "sbyte",
    "uint8": "byte",
    "int16": "short",
    "uint16": "ushort",
    "int32": "int",
    "uint32": "uint",
    "int64": "long",
    "uint64": "ulong",
    "float": "float",
    "double": "double",
}


def to_macro_name(name: str) -> str:
    out = []
    for ch in name or "PROJECT_MESSAGES":
        if ch.isascii() and ch.isalnum():
            out.append(ch.upper())
        else:
            out.append("_")
    value = "".join(out).strip("_") or "PROJECT_MESSAGES"
    if value[0].isdigit():
        value = "P_" + value
    return value


def to_idl_identifier(name: str, fallback: str = "GeneratedType") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name or fallback)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_") or fallback
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def definition_type(message: Message) -> str:
    return (getattr(message, "definition_type", "STRUCT") or "STRUCT").upper()


def is_enum_definition(message: Message) -> bool:
    return definition_type(message) == "ENUM"


def is_message_type(field) -> bool:
    return (getattr(field, "type_kind", "BASIC") or "BASIC").upper() == "MESSAGE"


def is_enum_type(field) -> bool:
    return (getattr(field, "type_kind", "BASIC") or "BASIC").upper() == "ENUM"


def is_ref_type(field) -> bool:
    return is_message_type(field) or is_enum_type(field)


def generated_type_name(message: Message) -> str:
    return getattr(message, "struct_name", None) or getattr(message, "name", None) or "MessageType"

def message_type_name(field) -> str:
    if getattr(field, "ref_message", None) is not None:
        return generated_type_name(field.ref_message)
    return getattr(field, "type", None) or "MessageType"

def field_variable_name(field) -> str:
    return getattr(field, "variable_name", None) or getattr(field, "name", None) or "field"

def field_comment_text(field) -> str:
    parts = []
    purpose = getattr(field, "purpose", None) or ""
    value_range = getattr(field, "value_range", None) or ""
    unit = getattr(field, "unit", None) or ""
    note = getattr(field, "note", None) or ""
    description = getattr(field, "description", None) or ""
    if purpose:
        parts.append(f"용도: {purpose}")
    if value_range:
        parts.append(f"허용값: {value_range}")
    if unit:
        parts.append(f"단위: {unit}")
    if note:
        parts.append(f"비고: {note}")
    if description:
        parts.append(description)
    return " / ".join(parts)


def _message_sort_key(message: Message):
    return (message.order_index or 0, generated_type_name(message).lower(), message.id or 0)


def order_messages_for_export(messages: list[Message]) -> list[Message]:
    """Return definitions in dependency-first order for nested message/enum fields."""
    message_by_id = {message.id: message for message in messages}
    ordered: list[Message] = []
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(message: Message):
        if message.id in visited:
            return
        if message.id in visiting:
            # Cycles are blocked at save time. If legacy data has a cycle, keep output deterministic.
            return
        visiting.add(message.id)
        if not is_enum_definition(message):
            for field in sorted(message.fields, key=lambda f: (f.order_index or 0, f.id or 0)):
                if is_ref_type(field) and field.ref_message_id in message_by_id:
                    visit(message_by_id[field.ref_message_id])
        visiting.remove(message.id)
        visited.add(message.id)
        ordered.append(message)

    for message in sorted(messages, key=_message_sort_key):
        visit(message)
    return ordered


def _get_display_timezone(timezone_name: str | None):
    if timezone_name and ZoneInfo is not None:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            pass
    return timezone.utc


def _as_utc(value: datetime) -> datetime:
    # DB timestamps are stored as UTC. SQLAlchemy currently returns naive datetimes,
    # so treat naive values as UTC before converting for display/export.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_last_modified_at(messages: list[Message], timezone_name: str | None = None) -> str:
    timestamps = [message.updated_at for message in messages if getattr(message, "updated_at", None)]
    if not timestamps:
        return "-"
    latest = max(timestamps)
    if isinstance(latest, datetime):
        display_tz = _get_display_timezone(timezone_name)
        local_value = _as_utc(latest).astimezone(display_tz)
        tz_label = local_value.tzname() or timezone_name or "UTC"
        return f"{local_value.strftime('%Y-%m-%d %H:%M:%S')} {tz_label}"
    return str(latest)


def export_metadata_comment(messages: list[Message], prefix: str = "//", timezone_name: str | None = None) -> list[str]:
    return [
        f"{prefix} Last modified at across exported definitions: {format_last_modified_at(messages, timezone_name)}",
        f"{prefix} Exported definition count: {len(messages)}",
        "",
    ]


def array_suffix(field) -> str:
    dimensions = getattr(field, "array_dimensions", None)
    if not dimensions and getattr(field, "is_array", False) and getattr(field, "array_size", None):
        dimensions = str(field.array_size)
    if not dimensions:
        return ""
    parts = []
    for part in str(dimensions).split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            parts.append(str(int(part)))
    return "".join(f"[{part}]" for part in parts)


def render_field_h(field) -> str:
    comment_text = field_comment_text(field)
    comment = f" // {comment_text}" if comment_text else ""
    suffix = array_suffix(field)
    member_name = to_idl_identifier(field_variable_name(field), "field")
    if is_ref_type(field):
        c_type = to_idl_identifier(message_type_name(field), "MessageType")
        return f"    {c_type} {member_name}{suffix};{comment}"
    c_type = C_TYPE_MAP.get(field.type, field.type)
    return f"    {c_type} {member_name}{suffix};{comment}"


def render_header(project_name: str, messages: list[Message], project_acronym: str | None = None, timezone_name: str | None = None) -> str:
    messages = order_messages_for_export(messages)
    guard = to_macro_name(project_acronym or project_name or "PROJECT_MESSAGES") + "_H"
    lines = export_metadata_comment(messages, timezone_name=timezone_name) + [
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        "#include <stdbool.h>",
        "",
        "#pragma pack(push, 1)",
        "",
    ]
    for message in messages:
        macro = to_macro_name(generated_type_name(message))
        type_name = to_idl_identifier(generated_type_name(message), "Message")
        display_comment = message.name if message.name != generated_type_name(message) else message.description
        lines.append(f"// {display_comment}" if display_comment else f"// {generated_type_name(message)}")
        lines.append(f"#define {macro}_VERSION {message.version}")
        if getattr(message, "infocode", None):
            lines.append(f"#define {macro}_INFOCODE \"{message.infocode}\"")
        if is_enum_definition(message):
            underlying = C_TYPE_MAP.get(getattr(message, "enum_underlying_type", "uint32") or "uint32", "uint32_t")
            lines.append(f"typedef {underlying} {type_name};")
            for enum_value in sorted(message.enum_values or [], key=lambda value: ((value.order_index or 0), (value.id or 0))):
                value_macro = to_macro_name(enum_value.name)
                comment = f" // {enum_value.description}" if enum_value.description else ""
                lines.append(f"#define {value_macro} (({type_name}){enum_value.value}){comment}")
        else:
            lines.append(f"#define {macro}_PERIOD \"{message.period}\"")
            lines.append("typedef struct")
            lines.append("{")
            for field in sorted(message.fields, key=lambda f: f.order_index):
                lines.append(render_field_h(field))
            lines.append(f"}} {type_name};")
        lines.append("")
    lines.append("#pragma pack(pop)")
    lines.append("")
    lines.append(f"#endif // {guard}")
    return "\n".join(lines) + "\n"


def render_field_idl(field) -> str:
    name = to_idl_identifier(field_variable_name(field), "field")
    suffix = array_suffix(field)
    if is_ref_type(field):
        idl_type = to_idl_identifier(message_type_name(field), "MessageType")
        return f"    {idl_type} {name}{suffix};"
    idl_type = IDL_TYPE_MAP.get(field.type, field.type)
    return f"    {idl_type} {name}{suffix};"


def render_idl(project_name: str, messages: list[Message], project_acronym: str | None = None, timezone_name: str | None = None) -> str:
    messages = order_messages_for_export(messages)
    module_name = to_idl_identifier(project_acronym or project_name or "ProjectMessages", "ProjectMessages")
    lines = export_metadata_comment(messages, timezone_name=timezone_name) + [
        f"module {module_name}",
        "{",
    ]
    for message in messages:
        type_name = to_idl_identifier(generated_type_name(message), "Message")
        if message.name or message.description:
            meta = message.name if message.name != generated_type_name(message) else message.description
            if meta:
                lines.append(f"  // {meta}")
        if is_enum_definition(message):
            lines.append(f"  enum {type_name}")
            lines.append("  {")
            enum_values = sorted(message.enum_values or [], key=lambda value: ((value.order_index or 0), (value.id or 0)))
            for index, enum_value in enumerate(enum_values):
                suffix = "," if index < len(enum_values) - 1 else ""
                comment = f" // {enum_value.description}" if enum_value.description else ""
                lines.append(f"    {to_idl_identifier(enum_value.name, 'ENUM_VALUE')} = {enum_value.value}{suffix}{comment}")
            lines.append("  };")
            lines.append("")
            continue
        if getattr(message, "infocode", None):
            lines.append(f"  // infocode: {message.infocode}")
        lines.append(f"  // period: {message.period}")
        lines.append(f"  // version: {message.version}")
        lines.append(f"  struct {type_name}")
        lines.append("  {")
        for field in sorted(message.fields, key=lambda f: f.order_index):
            field_line = render_field_idl(field)
            comment_text = field_comment_text(field)
            if comment_text:
                field_line += f" // {comment_text}"
            lines.append(field_line)
        lines.append("  };")
        lines.append("")
    lines.append("};")
    return "\n".join(lines) + "\n"


def array_dimensions(field) -> list[int]:
    dimensions = getattr(field, "array_dimensions", None)
    if not dimensions and getattr(field, "is_array", False) and getattr(field, "array_size", None):
        dimensions = str(field.array_size)
    if not dimensions:
        return []
    values: list[int] = []
    for part in str(dimensions).split(","):
        part = part.strip()
        if part.isdigit() and int(part) > 0:
            values.append(int(part))
    return values


def array_total_size(field) -> int:
    total = 1
    for dimension in array_dimensions(field):
        total *= dimension
    return total


def csharp_type_name(field) -> str:
    if is_ref_type(field):
        return to_idl_identifier(message_type_name(field), "MessageType")
    return CSHARP_TYPE_MAP.get(field.type, field.type)


def csharp_original_type_comment(field) -> str:
    if is_ref_type(field):
        base_type = to_idl_identifier(message_type_name(field), "MessageType")
    else:
        base_type = field.type
    suffix = array_suffix(field)
    if suffix:
        return f" // {base_type}{suffix}"
    if field.type in {"bool", "char"}:
        return f" // {field.type}"
    return ""


def render_field_csharp(field) -> list[str]:
    name = to_idl_identifier(field_variable_name(field), "field")
    dimensions = array_dimensions(field)
    total_size = array_total_size(field) if dimensions else 0
    comment_text = field_comment_text(field)
    description = f" // {comment_text}" if comment_text else ""
    original_comment = csharp_original_type_comment(field)

    if is_ref_type(field):
        cs_type = csharp_type_name(field)
        if dimensions:
            return [
                f"        [MarshalAs(UnmanagedType.ByValArray, SizeConst = {total_size})]",
                f"        public {cs_type}[] {name};{original_comment}{description}",
            ]
        return [f"        public {cs_type} {name};{description}"]

    cs_type = csharp_type_name(field)
    if dimensions:
        return [f"        public fixed {cs_type} {name}[{total_size}];{original_comment}{description}"]
    return [f"        public {cs_type} {name};{original_comment}{description}"]


def csharp_enum_underlying_type(message: Message) -> str:
    return CSHARP_TYPE_MAP.get(getattr(message, "enum_underlying_type", "uint32") or "uint32", "uint")


def render_csharp(project_name: str, messages: list[Message], project_acronym: str | None = None, timezone_name: str | None = None) -> str:
    messages = order_messages_for_export(messages)
    namespace_name = to_idl_identifier(project_acronym or project_name or "ProjectMessages", "ProjectMessages")
    lines = export_metadata_comment(messages, timezone_name=timezone_name) + [
        "using System.Runtime.InteropServices;",
        "",
        "// C# fixed buffers require AllowUnsafeBlocks=true in the C# project.",
        "// Multi-dimensional arrays are flattened to one-dimensional fixed buffers.",
        f"namespace {namespace_name}",
        "{",
    ]
    for message in messages:
        type_name = to_idl_identifier(generated_type_name(message), "Message")
        if message.name or message.description:
            meta = message.name if message.name != generated_type_name(message) else message.description
            if meta:
                lines.append(f"    // {meta}")
        if getattr(message, "infocode", None):
            lines.append(f"    // infocode: {message.infocode}")
        if is_enum_definition(message):
            lines.append(f"    public enum {type_name} : {csharp_enum_underlying_type(message)}")
            lines.append("    {")
            enum_values = sorted(message.enum_values or [], key=lambda value: ((value.order_index or 0), (value.id or 0)))
            for index, enum_value in enumerate(enum_values):
                suffix = "," if index < len(enum_values) - 1 else ""
                comment = f" // {enum_value.description}" if enum_value.description else ""
                lines.append(f"        {to_idl_identifier(enum_value.name, 'EnumValue')} = {enum_value.value}{suffix}{comment}")
            lines.append("    }")
            lines.append("")
            continue
        lines.append(f"    // period: {message.period}")
        lines.append(f"    // version: {message.version}")
        lines.append("    [StructLayout(LayoutKind.Sequential, Pack = 1)]")
        lines.append(f"    public unsafe struct {type_name}")
        lines.append("    {")
        for field in sorted(message.fields, key=lambda f: f.order_index):
            lines.extend(render_field_csharp(field))
        lines.append("    }")
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


# Backward-compatible alias for older frontend builds.
render_ldl = render_idl
