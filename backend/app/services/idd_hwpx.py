"""Export Interfy's existing IDD Word report as native, editable HWPX (OWPML).

We intentionally reuse render_idd_docx() as the single source of document
content, instead of duplicating CSCI/message/field mappings.

The HWPX skeleton, report header, and table cell templates are MIT-licensed
assets adapted from https://github.com/kist-aix/hwpx (see hwpx_assets/LICENSE).
HWPX is a ZIP of XML files. No Hancom Office, LibreOffice, or OS automation
is required on the backend.
"""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from itertools import count
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from docx import Document
from docx.oxml.ns import qn as word_qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree

from .idd_docx import render_idd_docx

ASSETS = Path(__file__).resolve().parent / "hwpx_assets"
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
OPF = "http://www.idpf.org/2007/opf/"
HWP_MIMETYPE = b"application/hwp+zip"

PACKAGE_FILES = (
    "version.xml",
    "settings.xml",
    "META-INF/container.xml",
    "META-INF/container.rdf",
    "META-INF/manifest.xml",
    "Contents/content.hpf",
    "Contents/header.xml",
    "Contents/section0.xml",
    "Preview/PrvText.txt",
)

_XML_PARSER = etree.XMLParser(
    resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False
)


def _asset_xml(path):
    return etree.parse(str(ASSETS / path), parser=_XML_PARSER)


def _set_run_text(run, value):
    """Preserve line breaks as editable HWPX text instead of literal newlines."""
    for text_node in list(run.findall("{%s}t" % HP)):
        run.remove(text_node)
    parts = str(value or "").split("\n")
    for index, part in enumerate(parts):
        if index:
            etree.SubElement(run, "{%s}lineBreak" % HP)
        node = etree.SubElement(run, "{%s}t" % HP)
        node.text = part or None


def _paragraph(text, ids, *, heading=False):
    p = etree.Element("{%s}p" % HP, {
        "id": str(next(ids)),
        "paraPrIDRef": "2" if heading else "22",
        "styleIDRef": "0",
        "pageBreak": "0",
        "columnBreak": "0",
        "merged": "0",
    })
    run = etree.SubElement(p, "{%s}run" % HP, {
        "charPrIDRef": "10" if heading else "25",
    })
    _set_run_text(run, text)
    return p


def _column_widths(table, available=42520):
    """Scale source Word column widths to the HWPX A4 printable width."""
    if not table.rows:
        return []
    raw = [
        int(cell.width or 0)
        for cell in table.rows[0].cells
    ]
    if not any(raw):
        raw = [1] * len(raw)
    raw = [max(1, x) for x in raw]
    total = sum(raw)
    widths = [max(1, round(available * width / total)) for width in raw]
    widths[-1] += available - sum(widths)
    return widths


def _fill_cell(tc, text, row, col, width, ids):
    addr = tc.find("{%s}cellAddr" % HP)
    addr.set("rowAddr", str(row))
    addr.set("colAddr", str(col))
    cell_sz = tc.find("{%s}cellSz" % HP)
    cell_sz.set("width", str(width))
    paragraphs = tc.findall(".//{%s}p" % HP)
    for p in paragraphs:
        p.set("id", str(next(ids)))
    run = tc.find(".//{%s}run" % HP)
    _set_run_text(run, text)


def _table(table, ids, table_template):
    """Create actual hp:tbl / hp:tr / hp:tc objects, not tab-delimited text."""
    if not table.rows:
        return None

    layout = _column_widths(table)
    width_total = sum(layout)
    source = table_template.find(".//{%s}tbl" % HP)
    head_row = source.find("{%s}tr" % HP)
    body_row = source.findall("{%s}tr" % HP)[1]
    head_cell = head_row.find("{%s}tc" % HP)
    body_cell = body_row.find("{%s}tc" % HP)

    tbl = deepcopy(source)
    tbl.set("id", str(next(ids)))
    tbl.set("rowCnt", str(len(table.rows)))
    tbl.set("colCnt", str(len(layout)))
    tbl.set("noAdjust", "0")
    shape = tbl.find("{%s}sz" % HP)
    shape.set("width", str(width_total))
    shape.set("height", str(2363 + max(0, len(table.rows) - 1) * 1984))
    for tr in list(tbl.findall("{%s}tr" % HP)):
        tbl.remove(tr)

    for row_index, docx_row in enumerate(table.rows):
        tr = deepcopy(head_row if row_index == 0 else body_row)
        tr.attrib.pop("row-type", None)
        for existing in list(tr.findall("{%s}tc" % HP)):
            tr.remove(existing)
        prototype = head_cell if row_index == 0 else body_cell
        for col_index, (cell, cell_width) in enumerate(zip(docx_row.cells, layout)):
            tc = deepcopy(prototype)
            _fill_cell(
                tc,
                "\n".join(p.text for p in cell.paragraphs),
                row_index, col_index, cell_width, ids
            )
            tr.append(tc)
        tbl.append(tr)

    # A table is a control embedded in a paragraph/run in HWPX.
    p = etree.Element("{%s}p" % HP, {
        "id": str(next(ids)), "paraPrIDRef": "2", "styleIDRef": "0",
        "pageBreak": "0", "columnBreak": "0", "merged": "0",
    })
    run = etree.SubElement(p, "{%s}run" % HP, {"charPrIDRef": "27"})
    run.append(tbl)
    etree.SubElement(run, "{%s}t" % HP)
    return p


def _hwpx_section(docx):
    tree = _asset_xml("Contents/section0.xml")
    root = tree.getroot()
    ids = count(1000000100)
    basic = _asset_xml("basic-table.xml").getroot()

    for child in docx.element.body.iterchildren():
        if child.tag == word_qn("w:p"):
            paragraph = Paragraph(child, docx)
            is_heading = paragraph.style is not None and (
                paragraph.style.name.startswith("Heading")
                or paragraph.style.name.startswith("Title")
            )
            root.append(_paragraph(paragraph.text, ids, heading=is_heading))
        elif child.tag == word_qn("w:tbl"):
            table = Table(child, docx)
            element = _table(table, ids, basic)
            if element is not None:
                root.append(element)

    return etree.tostring(tree, encoding="UTF-8", xml_declaration=True)


def _manifest(project_name):
    tree = _asset_xml("Contents/content.hpf")
    root = tree.getroot()
    title = root.find(".//{%s}title" % OPF)
    if title is not None:
        title.text = str(project_name or "Interfy") + " 인터페이스설계기술서(IDD)"
    return etree.tostring(tree, encoding="UTF-8", xml_declaration=True)


def render_idd_hwpx(project, messages) -> bytes:
    """Generate a Korean-editable HWPX with the same 3.1/3.2 tables as Word."""
    word_bytes = render_idd_docx(project, messages)
    word_doc = Document(BytesIO(word_bytes))
    section_xml = _hwpx_section(word_doc)
    manifest_xml = _manifest(getattr(project, "name", ""))

    preview = "\n".join(
        paragraph.text for paragraph in word_doc.paragraphs if paragraph.text
    )[:2048].encode("utf-8")

    result = BytesIO()
    with ZipFile(result, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", HWP_MIMETYPE, compress_type=ZIP_STORED)
        for path in PACKAGE_FILES:
            if path == "Contents/section0.xml":
                data = section_xml
            elif path == "Contents/content.hpf":
                data = manifest_xml
            elif path == "Preview/PrvText.txt":
                data = preview
            else:
                data = (ASSETS / path).read_bytes()
            archive.writestr(path, data)

    return result.getvalue()
