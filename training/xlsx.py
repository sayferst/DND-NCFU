"""Minimal OOXML workbook I/O: literal text, editable labels, bounded ZIP reading."""

import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", NS)
ET.register_namespace("r", REL)


def node(parent, tag, attributes=None, text=None):
    child = ET.SubElement(parent, "{" + NS + "}" + tag, attributes or {})
    child.text = text
    return child


def col(index):
    value = ""
    while index:
        index, rest = divmod(index - 1, 26)
        value = chr(65 + rest) + value
    return value


def xml(value):
    return ET.tostring(value, encoding="utf-8", xml_declaration=True)


def worksheet(rows, *, lists=None, status_column=None):
    root = ET.Element("{" + NS + "}worksheet")
    views = node(root, "sheetViews")
    view = node(views, "sheetView", {"workbookViewId": "0"})
    node(
        view,
        "pane",
        {"ySplit": "1", "topLeftCell": "A2", "activePane": "bottomLeft", "state": "frozen"},
    )
    columns = node(root, "cols")
    for n in range(1, len(rows[0]) + 1):
        node(
            columns,
            "col",
            {"min": str(n), "max": str(n), "width": "22" if n < 3 else "40", "customWidth": "1"},
        )
    data = node(root, "sheetData")
    for index, row in enumerate(rows, 1):
        element = node(data, "row", {"r": str(index)})
        for column, value in enumerate(row, 1):
            cell = node(
                element,
                "c",
                {
                    "r": col(column) + str(index),
                    "s": "1" if index == 1 else "0" if column == 1 else "2",
                },
            )
            if isinstance(value, dict) and set(value) == {"formula"}:
                node(cell, "f", text=value["formula"])
            elif type(value) in (int, float):
                node(cell, "v", text=str(value))
            else:
                cell.set("t", "inlineStr")
                inline = node(cell, "is")
                # Text beginning with '=', '+', '-' or '@' stays literal, never an Excel command.
                node(
                    inline,
                    "t",
                    {"{http://www.w3.org/XML/1998/namespace}space": "preserve"},
                    str(value or ""),
                )
    node(
        root, "sheetProtection", {"sheet": "1", "objects": "1", "scenarios": "1", "autoFilter": "0"}
    )
    node(root, "autoFilter", {"ref": f"A1:{col(len(rows[0]))}{len(rows)}"})
    if status_column:
        letter = col(status_column)
        formatting = node(
            root, "conditionalFormatting", {"sqref": f"{letter}2:{letter}{len(rows)}"}
        )
        for priority, (status, style) in enumerate(
            (("HUMAN_APPROVED", 0), ("HUMAN_REJECTED", 1)), 1
        ):
            rule = node(
                formatting,
                "cfRule",
                {"type": "expression", "dxfId": str(style), "priority": str(priority)},
            )
            node(rule, "formula", text=f'{letter}2="{status}"')
    if lists:
        validations = node(root, "dataValidations", {"count": str(len(lists))})
        for column, choices in lists.items():
            validation = node(
                validations,
                "dataValidation",
                {
                    "type": "list",
                    "allowBlank": "1",
                    "showErrorMessage": "1",
                    "sqref": f"{col(column)}2:{col(column)}{len(rows)}",
                },
            )
            node(validation, "formula1", text='"' + ",".join(choices) + '"')
    return xml(root)


def styles():
    root = ET.Element("{" + NS + "}styleSheet")
    fonts = node(root, "fonts", {"count": "2"})
    for header in (False, True):
        font = node(fonts, "font")
        node(font, "sz", {"val": "11"})
        node(font, "name", {"val": "Calibri"})
        if header:
            node(font, "b")
            node(font, "color", {"rgb": "FFFFFFFF"})
    fills = node(root, "fills", {"count": "3"})
    for pattern in ("none", "gray125", "solid"):
        fill = node(fills, "fill")
        p = node(fill, "patternFill", {"patternType": pattern})
        if pattern == "solid":
            node(p, "fgColor", {"rgb": "FF203864"})
    borders = node(root, "borders", {"count": "1"})
    node(borders, "border")
    formats = node(root, "cellStyleXfs", {"count": "1"})
    node(formats, "xf", {"numFmtId": "0", "fontId": "0", "fillId": "0", "borderId": "0"})
    formats = node(root, "cellXfs", {"count": "3"})
    for style in range(3):
        xf = node(
            formats,
            "xf",
            {
                "numFmtId": "0",
                "fontId": "1" if style == 1 else "0",
                "fillId": "2" if style == 1 else "0",
                "borderId": "0",
                "xfId": "0",
                "applyAlignment": "1",
                "applyProtection": "1",
            },
        )
        node(xf, "alignment", {"wrapText": "1", "vertical": "top"})
        node(xf, "protection", {"locked": "0" if style == 2 else "1"})
    cell_styles = node(root, "cellStyles", {"count": "1"})
    node(cell_styles, "cellStyle", {"name": "Normal", "xfId": "0", "builtinId": "0"})
    differentials = node(root, "dxfs", {"count": "2"})
    for color in ("FFC6EFCE", "FFFFC7CE"):
        dxf = node(differentials, "dxf")
        p = node(node(dxf, "fill"), "patternFill", {"patternType": "solid"})
        node(p, "fgColor", {"rgb": color})
    return xml(root)


def write(path, sheets):
    """sheets: (name, rows, validation options). Never overwrite an annotated file."""
    path = Path(path)
    book = ET.Element("{" + NS + "}workbook")
    listing = node(book, "sheets")
    node(book, "calcPr", {"calcId": "191029", "fullCalcOnLoad": "1"})
    relationships = ET.Element("Relationships", {"xmlns": PACKAGE})
    content = ET.Element(
        "Types", {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"}
    )
    for extension, type in (
        ("rels", "application/vnd.openxmlformats-package.relationships+xml"),
        ("xml", "application/xml"),
    ):
        ET.SubElement(content, "Default", {"Extension": extension, "ContentType": type})
    for name, type in (("workbook.xml", "sheet.main"), ("styles.xml", "styles")):
        ET.SubElement(
            content,
            "Override",
            {
                "PartName": "/xl/" + name,
                "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml."
                + type
                + "+xml",
            },
        )
    with ZipFile(path, "x", ZIP_DEFLATED) as archive:
        for index, (name, rows, options) in enumerate(sheets, 1):
            node(
                listing,
                "sheet",
                {"name": name, "sheetId": str(index), "{" + REL + "}id": f"rId{index}"},
            )
            ET.SubElement(
                relationships,
                "Relationship",
                {
                    "Id": f"rId{index}",
                    "Type": REL + "/worksheet",
                    "Target": f"worksheets/sheet{index}.xml",
                },
            )
            ET.SubElement(
                content,
                "Override",
                {
                    "PartName": f"/xl/worksheets/sheet{index}.xml",
                    "ContentType": (
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
                    ),
                },
            )
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet(rows, **options))
        ET.SubElement(
            relationships,
            "Relationship",
            {"Id": "styles", "Type": REL + "/styles", "Target": "styles.xml"},
        )
        root_rel = ET.Element("Relationships", {"xmlns": PACKAGE})
        ET.SubElement(
            root_rel,
            "Relationship",
            {"Id": "book", "Type": REL + "/officeDocument", "Target": "xl/workbook.xml"},
        )
        archive.writestr("_rels/.rels", xml(root_rel))
        archive.writestr("xl/_rels/workbook.xml.rels", xml(relationships))
        archive.writestr("xl/workbook.xml", xml(book))
        archive.writestr("xl/styles.xml", styles())
        archive.writestr("[Content_Types].xml", xml(content))


def read(path, *, sheet=1):
    with ZipFile(path) as archive:
        if (
            len(archive.infolist()) > 100
            or sum(i.file_size for i in archive.infolist()) > 32 * 1024 * 1024
        ):
            raise ValueError("Workbook exceeds annotation limits")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            tree = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(t.itertext()) for t in tree]
        tree = ET.fromstring(archive.read(f"xl/worksheets/sheet{sheet}.xml"))
        result = []
        for row in tree.findall(f"{{{NS}}}sheetData/{{{NS}}}row"):
            values = {}
            for cell in row:
                column = re.match(r"[A-Z]+", cell.attrib["r"])[0]
                if cell.find(f"{{{NS}}}f") is not None:
                    raise ValueError("Formula is forbidden in annotation cells")
                kind = cell.attrib.get("t")
                value = cell.findtext(f"{{{NS}}}v", "")
                values[column] = (
                    "".join(cell.find(f"{{{NS}}}is").itertext())
                    if kind == "inlineStr"
                    else shared[int(value)]
                    if kind == "s"
                    else value
                )
            result.append(values)
        return result
