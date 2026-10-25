from io import BytesIO
from types import SimpleNamespace

from docx import Document

from app.services.idd_docx import render_idd_docx


def node(name):
    return SimpleNamespace(name=name)


def field(name, *, size=2, unit="", value_range="", description="", purpose="", type="uint16"):
    return SimpleNamespace(
        id=1, name=name, type=type, type_kind="BASIC", ref_message=None,
        size_bytes=size, unit=unit, value_range=value_range,
        description=description, purpose=purpose, note="", order_index=1,
    )


def message(mid, name, *, tx=(), rx=(), protocol="TCP", fields=(), period="100",
            definition_type="STRUCT", order_index=0, size_bytes=2):
    return SimpleNamespace(
        id=mid, struct_name="MSG_" + str(mid), name=name,
        tx_targets=[node(x) for x in tx], rx_targets=[node(x) for x in rx],
        period=period, protocol=protocol, definition_type=definition_type,
        fields=list(fields), order_index=order_index, size_bytes=size_bytes,
    )


def document_text(doc):
    return "\n".join(
        [paragraph.text for paragraph in doc.paragraphs] +
        [cell.text for table in doc.tables for row in table.rows for cell in row.cells]
    )


def test_idd_docx_produces_editable_tables_with_saved_data():
    project = SimpleNamespace(name="CSU 연동")
    messages = [
        message(1, "항법정보", tx=("CSU",), rx=("AUV",), protocol="UDP, DDS",
                fields=[field("latitude", size=4, unit="deg",
                              value_range="-90~90", description="위도")],
                size_bytes=4),
        message(2, "임무명령", tx=("CSU",), rx=("AUV",), protocol="DDS",
                fields=[field("command")], order_index=2),
    ]
    content = render_idd_docx(project, messages)
    assert content[:2] == b"PK"
    doc = Document(BytesIO(content))
    text = document_text(doc)
    for value in ["3.1 인터페이스간 연동 개념", "3.2 인터페이스간 연동 설계",
                  "CSU", "AUV", "항법정보", "임무명령", "latitude",
                  "deg", "-90~90", "위도", "100 ms", "4 Byte", "UDP", "DDS",
                  "사용자 인터페이스 목록", "통신방법", "프로토콜"]:
        assert value in text
    assert doc.tables


def test_idd_does_not_infer_missing_transport_details_or_pairwise_edges():
    project = SimpleNamespace(name="TEST")
    messages = [
        message(1, "A", tx=("CSU", "MDV"), rx=("AUV",), protocol="", fields=[]),
        message(2, "Only enum", definition_type="ENUM"),
    ]
    doc = Document(BytesIO(render_idd_docx(project, messages)))
    text = document_text(doc)
    assert "Only enum" not in text
    assert "CSU, MDV" in text
    # A two-sender relationship is preserved as a single source set.
    relation_table = next(table for table in doc.tables if table.rows[0].cells[0].text == "송신 CSCI")
    assert len(relation_table.rows) == 2
    # Unknown communication fields stay blank, rather than fabricated.
    comm_table = next(
        table for table in doc.tables
        if table.rows[1].cells[0].text == "통신 구분명(식별자)"
    )
    assert comm_table.rows[1].cells[1].text == ""
    assert "3a" not in text


def test_idd_generates_template_when_project_is_empty():
    doc = Document(BytesIO(render_idd_docx(SimpleNamespace(name="Empty"), [])))
    assert doc.tables
    assert "등록된 메시지가 없습니다." in document_text(doc)
