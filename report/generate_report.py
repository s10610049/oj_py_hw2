"""Build the course OJ experiment report from REPORT_SOURCE.md.

Document dependencies are imported only when their corresponding validation or
build path runs. Use the locked project environment for reproducible source
checks and PDF builds.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

REPORT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = REPORT_DIR.parent
DEFAULT_SOURCE = REPORT_DIR / "REPORT_SOURCE.md"
DEFAULT_OUTPUT = PROJECT_ROOT / "output" / "pdf" / "实验报告.pdf"
DEFAULT_BUILD = PROJECT_ROOT / "tmp" / "pdfs" / "实验报告-building.pdf"

INK = "#17202D"
MUTED = "#667282"
PAPER = "#FFFFFF"
CANVAS = "#F3F5F7"
LINE = "#DFE4EA"
GREEN = "#2D7658"
GREEN_DARK = "#1E5842"
GREEN_SOFT = "#E8F2ED"
AMBER = "#A66A16"
AMBER_SOFT = "#FBF2E4"
RED = "#A33D45"

PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
PAGE_RE = re.compile(r"^##\s+第\s*(\d+)\s*页[｜|]\s*(.+?)\s*$")
DIRECTIVE_RE = re.compile(r"^:::([a-z][a-z0-9_-]*)\s*$")


class SourceError(ValueError):
    """The report source is malformed or contains unresolved final facts."""


@dataclass(frozen=True)
class Block:
    kind: str
    value: Any
    language: str = ""


@dataclass(frozen=True)
class Page:
    number: int
    title: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class ReportSource:
    metadata: Mapping[str, Any]
    pages: tuple[Page, ...]
    unresolved: tuple[str, ...] = field(default_factory=tuple)


def _yaml_load(text: str) -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised in clean doc envs
        raise RuntimeError(
            "PyYAML is required to parse the report source. Install project dependencies first."
        ) from exc
    value = yaml.safe_load(text)
    return {} if value is None else value


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise SourceError("REPORT_SOURCE.md must start with YAML front matter")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise SourceError("YAML front matter is not closed") from exc
    metadata = _yaml_load("\n".join(lines[1:end]))
    if not isinstance(metadata, dict):
        raise SourceError("YAML front matter must be an object")
    return metadata, "\n".join(lines[end + 1 :])


def _facts(metadata: Mapping[str, Any], overrides: Mapping[str, str]) -> dict[str, str]:
    raw = metadata.get("facts", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise SourceError("front matter facts must be an object")
    result = {str(key): str(value) for key, value in raw.items()}
    for key, value in overrides.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise SourceError(f"invalid fact name: {key!r}")
        result[key] = value
    return result


def _substitute(text: str, facts: Mapping[str, str]) -> tuple[str, tuple[str, ...]]:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in facts:
            missing.add(key)
            return match.group(0)
        return facts[key]

    rendered = PLACEHOLDER_RE.sub(replace, text)
    unresolved = set(missing)
    for key, value in facts.items():
        if value.strip().upper().startswith("TODO:") and f"{{{{{key}}}}}" in text:
            unresolved.add(key)
    unresolved.update(PLACEHOLDER_RE.findall(rendered))
    return rendered, tuple(sorted(unresolved))


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _table(lines: list[str], start: int) -> tuple[Block, int] | None:
    if not lines[start].lstrip().startswith("|") or start + 1 >= len(lines):
        return None
    divider = lines[start + 1].strip()
    if not re.fullmatch(r"\|?(?:\s*:?-{3,}:?\s*\|)+\s*", divider):
        return None
    rows: list[list[str]] = []
    index = start
    while index < len(lines) and lines[index].lstrip().startswith("|"):
        cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
        rows.append(cells)
        index += 1
    rows.pop(1)
    width = len(rows[0])
    if width < 2 or any(len(row) != width for row in rows):
        raise SourceError(f"inconsistent Markdown table near line {start + 1}")
    return Block("table", rows), index


def _parse_blocks(text: str) -> tuple[Block, ...]:
    lines = text.split("\n")
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        directive = DIRECTIVE_RE.fullmatch(stripped)
        if directive:
            kind = directive.group(1)
            end = index + 1
            while end < len(lines) and lines[end].strip() != ":::":
                end += 1
            if end >= len(lines):
                raise SourceError(f"unclosed :::{kind} directive")
            payload = _yaml_load("\n".join(lines[index + 1 : end]))
            if not isinstance(payload, Mapping):
                raise SourceError(f"::{kind} payload must be an object")
            blocks.append(Block(kind, dict(payload)))
            index = end + 1
            continue
        if stripped.startswith("```"):
            language = stripped[3:].strip()
            end = index + 1
            while end < len(lines) and not lines[end].strip().startswith("```"):
                end += 1
            if end >= len(lines):
                raise SourceError(f"unclosed code fence near line {index + 1}")
            blocks.append(Block("code", "\n".join(lines[index + 1 : end]), language))
            index = end + 1
            continue
        parsed_table = _table(lines, index)
        if parsed_table is not None:
            block, index = parsed_table
            blocks.append(block)
            continue
        if stripped.startswith("### "):
            blocks.append(Block("heading", stripped[4:].strip()))
            index += 1
            continue
        if stripped.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(lines[index].strip()[2:].strip())
                index += 1
            blocks.append(Block("bullets", items))
            continue
        paragraph = [stripped]
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if (
                not candidate
                or candidate.startswith(("### ", "- ", "```", ":::"))
                or candidate.startswith("|")
            ):
                break
            paragraph.append(candidate)
            index += 1
        blocks.append(Block("paragraph", " ".join(paragraph)))
    return tuple(blocks)


def parse_source(
    path: Path = DEFAULT_SOURCE,
    *,
    overrides: Mapping[str, str] | None = None,
) -> ReportSource:
    text = path.read_text(encoding="utf-8")
    metadata, body = _front_matter(text)
    facts = _facts(metadata, overrides or {})
    substituted, unresolved = _substitute(_strip_comments(body), facts)
    pages: list[Page] = []
    current_number: int | None = None
    current_title = ""
    current_lines: list[str] = []
    for line in substituted.split("\n"):
        match = PAGE_RE.fullmatch(line.strip())
        if match:
            if current_number is not None:
                pages.append(
                    Page(current_number, current_title, _parse_blocks("\n".join(current_lines)))
                )
            current_number = int(match.group(1))
            current_title = match.group(2).strip()
            current_lines = []
        elif current_number is not None:
            current_lines.append(line)
        elif line.strip():
            raise SourceError("content before the first page heading is not allowed")
    if current_number is not None:
        pages.append(Page(current_number, current_title, _parse_blocks("\n".join(current_lines))))
    if not pages:
        raise SourceError("no report pages were found")
    expected_numbers = list(range(1, len(pages) + 1))
    actual_numbers = [page.number for page in pages]
    if actual_numbers != expected_numbers:
        raise SourceError(f"page headings must be sequential: found {actual_numbers}")
    expected_pages = int(metadata.get("expected_pages", len(pages)))
    if len(pages) != expected_pages:
        raise SourceError(f"source declares {expected_pages} pages but contains {len(pages)}")
    required = {"title", "subtitle", "author", "student_id", "course", "date"}
    missing = sorted(key for key in required if not str(metadata.get(key, "")).strip())
    if missing:
        raise SourceError(f"front matter fields are missing: {', '.join(missing)}")
    return ReportSource(metadata=metadata, pages=tuple(pages), unresolved=unresolved)


def _font_candidates() -> dict[str, list[Path]]:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
    return {
        "body": [
            windows / "Noto Sans SC.ttf",
            windows / "NotoSansSC-VF.ttf",
            windows / "Deng.ttf",
            windows / "msyh.ttc",
        ],
        "bold": [
            windows / "NotoSansSC-Medium.otf",
            windows / "Dengb.ttf",
            windows / "msyhbd.ttc",
        ],
        "mono": [
            windows / "JetBrainsMono-Regular.ttf",
            local / "JetBrainsMono-Regular.ttf",
            windows / "consola.ttf",
        ],
        "mono_bold": [
            windows / "JetBrainsMono-Bold.ttf",
            local / "JetBrainsMono-Bold.ttf",
            windows / "consolab.ttf",
        ],
    }


def _register_fonts(pdfmetrics: Any, TTFont: Any, UnicodeCIDFont: Any) -> dict[str, str]:
    # ReportLab's Base-14 Helvetica/Courier fonts cannot encode Chinese.  Start
    # with a bundled CID fallback so a clean Linux checkout remains capable of
    # rebuilding the report, then prefer local fonts where they are available.
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    result = {
        "body": "STSong-Light",
        "bold": "STSong-Light",
        "mono": "STSong-Light",
        "mono_bold": "STSong-Light",
    }
    candidates = _font_candidates()
    names = {
        "body": "ReportNoto",
        "bold": "ReportNotoMedium",
        "mono": "ReportMono",
        "mono_bold": "ReportMonoBold",
    }
    for role, paths in candidates.items():
        for path in paths:
            if not path.is_file():
                continue
            try:
                pdfmetrics.registerFont(TTFont(names[role], str(path)))
            except Exception:
                continue
            result[role] = names[role]
            break
    pdfmetrics.registerFontFamily(
        "ReportBody",
        normal=result["body"],
        bold=result["bold"],
        italic=result["body"],
        boldItalic=result["bold"],
    )
    return result


def _inline(text: Any, fonts: Mapping[str, str]) -> str:
    escaped = html.escape(str(text), quote=False)
    parts = escaped.split("`")
    rendered: list[str] = []
    for index, part in enumerate(parts):
        if index % 2:
            rendered.append(f'<font name="{fonts["mono"]}" color="{GREEN_DARK}">{part}</font>')
        else:
            rendered.append(part)
    return "".join(rendered)


def _safe_asset(path_text: str) -> Path:
    value = Path(path_text)
    if value.is_absolute():
        raise SourceError("report image paths must be repository-relative")
    candidate = (REPORT_DIR / value).resolve()
    allowed = [REPORT_DIR.resolve(), (PROJECT_ROOT / "static").resolve()]
    if not any(candidate == root or root in candidate.parents for root in allowed):
        raise SourceError(f"report image leaves allowed roots: {path_text}")
    return candidate


def _paragraph_styles(rl: Mapping[str, Any], fonts: Mapping[str, str]) -> dict[str, Any]:
    ParagraphStyle = rl["ParagraphStyle"]
    TA_CENTER = rl["TA_CENTER"]
    TA_LEFT = rl["TA_LEFT"]
    colors = rl["colors"]
    mm = rl["mm"]
    return {
        "body": ParagraphStyle(
            "Body",
            fontName=fonts["body"],
            fontSize=8.7,
            leading=13.8,
            textColor=colors.HexColor(INK),
            spaceAfter=4.0,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "h1": ParagraphStyle(
            "PageTitle",
            fontName=fonts["bold"],
            fontSize=19,
            leading=25,
            textColor=colors.HexColor(INK),
            spaceAfter=7,
            wordWrap="CJK",
        ),
        "h2": ParagraphStyle(
            "SectionTitle",
            fontName=fonts["bold"],
            fontSize=11.4,
            leading=16,
            textColor=colors.HexColor(GREEN_DARK),
            spaceBefore=4,
            spaceAfter=3,
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "Small",
            fontName=fonts["body"],
            fontSize=7.2,
            leading=10.8,
            textColor=colors.HexColor(MUTED),
            wordWrap="CJK",
        ),
        "caption": ParagraphStyle(
            "Caption",
            fontName=fonts["body"],
            fontSize=6.8,
            leading=9.6,
            textColor=colors.HexColor(MUTED),
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            fontName=fonts["bold"],
            fontSize=27,
            leading=34,
            textColor=colors.HexColor(INK),
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            fontName=fonts["body"],
            fontSize=12,
            leading=18,
            textColor=colors.HexColor(MUTED),
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "eyebrow": ParagraphStyle(
            "Eyebrow",
            fontName=fonts["bold"],
            fontSize=7.2,
            leading=10,
            textColor=colors.HexColor(GREEN),
            tracking=1.2,
            wordWrap="CJK",
        ),
        "metric_value": ParagraphStyle(
            "MetricValue",
            fontName=fonts["bold"],
            fontSize=14,
            leading=17,
            textColor=colors.HexColor(INK),
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            fontName=fonts["body"],
            fontSize=6.7,
            leading=9,
            textColor=colors.HexColor(MUTED),
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "Code",
            fontName=fonts["mono"],
            fontSize=6.7,
            leading=9.7,
            textColor=colors.HexColor(INK),
            leftIndent=4 * mm,
            rightIndent=4 * mm,
            borderPadding=(3 * mm, 3 * mm, 3 * mm, 3 * mm),
            borderColor=colors.HexColor(LINE),
            borderWidth=0.5,
            borderRadius=5,
            backColor=colors.HexColor(CANVAS),
            spaceBefore=2,
            spaceAfter=5,
        ),
    }


def _load_reportlab() -> dict[str, Any]:
    try:
        from reportlab.graphics.charts.piecharts import Pie
        from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (
            HRFlowable,
            Image,
            ListFlowable,
            ListItem,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
            XPreformatted,
        )
    except ImportError as exc:
        raise RuntimeError(
            "ReportLab is required to generate the PDF. Use the bundled workspace "
            "document runtime or install reportlab before building."
        ) from exc
    return {
        "Pie": Pie,
        "Circle": Circle,
        "Drawing": Drawing,
        "Line": Line,
        "Rect": Rect,
        "String": String,
        "colors": colors,
        "TA_CENTER": TA_CENTER,
        "TA_LEFT": TA_LEFT,
        "A4": A4,
        "ParagraphStyle": ParagraphStyle,
        "mm": mm,
        "pdfmetrics": pdfmetrics,
        "UnicodeCIDFont": UnicodeCIDFont,
        "TTFont": TTFont,
        "HRFlowable": HRFlowable,
        "Image": Image,
        "ListFlowable": ListFlowable,
        "ListItem": ListItem,
        "PageBreak": PageBreak,
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
        "XPreformatted": XPreformatted,
    }


def _drawing_placeholder(
    rl: Mapping[str, Any], fonts: Mapping[str, str], width: float, height: float, label: str
) -> Any:
    colors = rl["colors"]
    Drawing, Rect, Line, String = rl["Drawing"], rl["Rect"], rl["Line"], rl["String"]
    drawing = Drawing(width, height)
    drawing.add(
        Rect(
            0,
            0,
            width,
            height,
            rx=8,
            ry=8,
            fillColor=colors.HexColor(CANVAS),
            strokeColor=colors.HexColor(LINE),
            strokeWidth=0.8,
            strokeDashArray=[4, 3],
        )
    )
    drawing.add(Line(12, 12, width - 12, height - 12, strokeColor=colors.HexColor(LINE)))
    drawing.add(Line(12, height - 12, width - 12, 12, strokeColor=colors.HexColor(LINE)))
    drawing.add(
        String(
            width / 2,
            height / 2 + 5,
            "最终截图待补",
            fontName=fonts["bold"],
            fontSize=9,
            fillColor=colors.HexColor(MUTED),
            textAnchor="middle",
        )
    )
    drawing.add(
        String(
            width / 2,
            height / 2 - 9,
            label[:42],
            fontName=fonts["body"],
            fontSize=6.2,
            fillColor=colors.HexColor(MUTED),
            textAnchor="middle",
        )
    )
    return drawing


def _image_or_placeholder(
    rl: Mapping[str, Any],
    fonts: Mapping[str, str],
    path_text: str,
    width: float,
    height: float,
    missing: list[str],
) -> Any:
    path = _safe_asset(path_text)
    if not path.is_file():
        missing.append(path_text)
        return _drawing_placeholder(rl, fonts, width, height, path.name)
    Image = rl["Image"]
    from PIL import Image as PILImage

    with PILImage.open(path) as source:
        source_width, source_height = source.size
    ratio = min(width / source_width, height / source_height)
    return Image(str(path), width=source_width * ratio, height=source_height * ratio)


def _title_flowables(rl: Mapping[str, Any], styles: Mapping[str, Any], page: Page) -> list[Any]:
    Paragraph, HRFlowable, Spacer = rl["Paragraph"], rl["HRFlowable"], rl["Spacer"]
    colors = rl["colors"]
    return [
        Paragraph(f"{page.number:02d} / {html.escape(page.title)}", styles["h1"]),
        HRFlowable(
            width="100%",
            thickness=1.0,
            color=colors.HexColor(GREEN),
            spaceBefore=0,
            spaceAfter=6,
        ),
        Spacer(1, 1),
    ]


def _cover(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    fonts: Mapping[str, str],
    metadata: Mapping[str, Any],
    payload: Mapping[str, Any],
    available_width: float,
    missing: list[str],
) -> list[Any]:
    Paragraph, Spacer, Table, TableStyle = (
        rl["Paragraph"],
        rl["Spacer"],
        rl["Table"],
        rl["TableStyle"],
    )
    colors, mm = rl["colors"], rl["mm"]
    logo = _image_or_placeholder(rl, fonts, str(payload.get("logo", "")), 42 * mm, 28 * mm, missing)
    info = [
        ["课程", metadata["course"]],
        ["学生", f'{metadata["author"]}  ·  {metadata["student_id"]}'],
        ["日期", metadata["date"]],
    ]
    info_table = Table(
        [
            [
                Paragraph(html.escape(str(a)), styles["small"]),
                Paragraph(html.escape(str(b)), styles["body"]),
            ]
            for a, b in info
        ],
        colWidths=[28 * mm, 95 * mm],
        hAlign="LEFT",
    )
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.45, colors.HexColor(LINE)),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    accent = Table(
        [[Paragraph(html.escape(str(payload.get("accent", ""))), styles["h2"])]],
        colWidths=[available_width],
    )
    accent.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(GREEN_SOFT)),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C8DCD2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return [
        Spacer(1, 23 * mm),
        logo,
        Spacer(1, 13 * mm),
        Paragraph(html.escape(str(payload.get("eyebrow", ""))), styles["eyebrow"]),
        Spacer(1, 3 * mm),
        Paragraph(html.escape(str(metadata["title"])), styles["cover_title"]),
        Paragraph(html.escape(str(metadata["subtitle"])), styles["cover_subtitle"]),
        Spacer(1, 7 * mm),
        Paragraph(html.escape(str(payload.get("summary", ""))), styles["body"]),
        Spacer(1, 12 * mm),
        info_table,
        Spacer(1, 14 * mm),
        accent,
    ]


def _bars(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    fonts: Mapping[str, str],
    payload: Mapping[str, Any],
    available_width: float,
) -> list[Any]:
    Paragraph, Spacer = rl["Paragraph"], rl["Spacer"]
    Drawing, Rect, String = rl["Drawing"], rl["Rect"], rl["String"]
    colors = rl["colors"]
    labels = [str(value) for value in payload.get("labels", [])]
    values = [float(value) for value in payload.get("values", [])]
    if not labels or len(labels) != len(values):
        raise SourceError("bars directive requires equal non-empty labels and values")
    maximum = float(payload.get("max_value", max(values) or 1))
    if maximum <= 0:
        raise SourceError("bars max_value must be positive")
    row_height = 14
    height = 20 + len(labels) * row_height
    drawing = Drawing(available_width, height)
    label_width = min(112, available_width * 0.27)
    chart_width = available_width - label_width - 42
    for index, (label, value) in enumerate(zip(labels, values)):
        y = height - 19 - index * row_height
        drawing.add(
            String(
                0,
                y + 2,
                label,
                fontName=fonts["body"],
                fontSize=6.5,
                fillColor=colors.HexColor(MUTED),
            )
        )
        drawing.add(
            Rect(
                label_width,
                y,
                chart_width,
                7,
                rx=3.5,
                ry=3.5,
                fillColor=colors.HexColor("#EDF0F2"),
                strokeColor=None,
            )
        )
        drawing.add(
            Rect(
                label_width,
                y,
                chart_width * min(max(value / maximum, 0), 1),
                7,
                rx=3.5,
                ry=3.5,
                fillColor=colors.HexColor(GREEN if index % 2 == 0 else "#4D7182"),
                strokeColor=None,
            )
        )
        suffix = str(payload.get("unit", ""))
        formatted = str(int(value)) if value.is_integer() else f"{value:g}"
        drawing.add(
            String(
                available_width,
                y + 2,
                f"{formatted}{suffix}",
                fontName=fonts["bold"],
                fontSize=6.5,
                fillColor=colors.HexColor(INK),
                textAnchor="end",
            )
        )
    return [
        Paragraph(html.escape(str(payload.get("title", "数据概览"))), styles["h2"]),
        drawing,
        Spacer(1, 3),
    ]


def _flow(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    payload: Mapping[str, Any],
    available_width: float,
) -> list[Any]:
    Paragraph, Table, TableStyle, Spacer = (
        rl["Paragraph"],
        rl["Table"],
        rl["TableStyle"],
        rl["Spacer"],
    )
    colors = rl["colors"]
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        raise SourceError("flow directive requires items")
    box_width = (available_width - 12 * (len(items) - 1)) / len(items)
    cells: list[Any] = []
    widths: list[float] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise SourceError("flow items must be objects")
        content = [
            [Paragraph(html.escape(str(item.get("title", ""))), styles["h2"])],
            [Paragraph(html.escape(str(item.get("detail", ""))), styles["small"])],
        ]
        inner = Table(content, colWidths=[box_width - 10])
        inner.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(CANVAS)),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor(LINE)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, 0), 5),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
                ]
            )
        )
        cells.append(inner)
        widths.append(box_width)
        if index < len(items) - 1:
            cells.append(Paragraph("→", styles["h2"]))
            widths.append(12)
    table = Table([cells], colWidths=widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [
        Paragraph(html.escape(str(payload.get("title", "流程"))), styles["h2"]),
        table,
        Spacer(1, 5),
    ]


def _gallery(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    fonts: Mapping[str, str],
    payload: Mapping[str, Any],
    available_width: float,
    missing: list[str],
) -> list[Any]:
    Paragraph, Table, TableStyle, Spacer = (
        rl["Paragraph"],
        rl["Table"],
        rl["TableStyle"],
        rl["Spacer"],
    )
    colors = rl["colors"]
    images = payload.get("images", [])
    if not isinstance(images, list) or not images:
        raise SourceError("gallery directive requires images")
    gap = 8
    width = (available_width - gap * (len(images) - 1)) / len(images)
    height = float(payload.get("height", 150))
    cells = []
    for item in images:
        if not isinstance(item, Mapping):
            raise SourceError("gallery images must be objects")
        visual = _image_or_placeholder(
            rl, fonts, str(item.get("path", "")), width - 8, height, missing
        )
        caption = Paragraph(_inline(item.get("caption", ""), fonts), styles["caption"])
        inner = Table([[visual], [caption]], colWidths=[width])
        inner.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PAPER)),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(LINE)),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        cells.append(inner)
    table = Table([cells], colWidths=[width] * len(cells), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), gap),
            ]
        )
    )
    return [
        Paragraph(html.escape(str(payload.get("title", "界面截图"))), styles["h2"]),
        table,
        Spacer(1, 4),
    ]


def _single_image(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    fonts: Mapping[str, str],
    payload: Mapping[str, Any],
    available_width: float,
    missing: list[str],
) -> list[Any]:
    Paragraph, Table, TableStyle, Spacer = (
        rl["Paragraph"],
        rl["Table"],
        rl["TableStyle"],
        rl["Spacer"],
    )
    colors = rl["colors"]
    height = float(payload.get("height", 200))
    visual = _image_or_placeholder(
        rl, fonts, str(payload.get("path", "")), available_width - 10, height, missing
    )
    caption = Paragraph(_inline(payload.get("caption", ""), fonts), styles["caption"])
    table = Table([[visual], [caption]], colWidths=[available_width])
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(LINE)),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return [table, Spacer(1, 4)]


def _callout(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    fonts: Mapping[str, str],
    payload: Mapping[str, Any],
    available_width: float,
) -> list[Any]:
    Paragraph, Table, TableStyle, Spacer = (
        rl["Paragraph"],
        rl["Table"],
        rl["TableStyle"],
        rl["Spacer"],
    )
    colors = rl["colors"]
    warning = str(payload.get("tone", "neutral")) == "warning"
    background = AMBER_SOFT if warning else GREEN_SOFT
    border = "#E4CFAE" if warning else "#C8DCD2"
    title_color = AMBER if warning else GREEN_DARK
    title_style = styles["h2"].clone("CalloutTitle")
    title_style.textColor = colors.HexColor(title_color)
    content = [
        [Paragraph(_inline(payload.get("title", ""), fonts), title_style)],
        [Paragraph(_inline(payload.get("text", ""), fonts), styles["body"])],
    ]
    table = Table(content, colWidths=[available_width])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(border)),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return [table, Spacer(1, 5)]


def _metrics(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    fonts: Mapping[str, str],
    payload: Mapping[str, Any],
    available_width: float,
) -> list[Any]:
    Paragraph, Table, TableStyle, Spacer = (
        rl["Paragraph"],
        rl["Table"],
        rl["TableStyle"],
        rl["Spacer"],
    )
    colors = rl["colors"]
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        raise SourceError("metrics directive requires items")
    width = available_width / len(items)
    cells = []
    for item in items:
        if not isinstance(item, Mapping):
            raise SourceError("metric items must be objects")
        inner = Table(
            [
                [Paragraph(_inline(item.get("value", ""), fonts), styles["metric_value"])],
                [Paragraph(_inline(item.get("label", ""), fonts), styles["metric_label"])],
            ],
            colWidths=[width - 6],
        )
        inner.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(CANVAS)),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(LINE)),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        cells.append(inner)
    outer = Table([cells], colWidths=[width] * len(items))
    outer.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return [
        Paragraph(html.escape(str(payload.get("title", "数据快照"))), styles["h2"]),
        outer,
        Spacer(1, 5),
    ]


def _donut(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    fonts: Mapping[str, str],
    payload: Mapping[str, Any],
    available_width: float,
) -> list[Any]:
    Paragraph, Spacer = rl["Paragraph"], rl["Spacer"]
    Drawing, Circle, String, Pie = rl["Drawing"], rl["Circle"], rl["String"], rl["Pie"]
    colors = rl["colors"]
    labels = [str(value) for value in payload.get("labels", [])]
    values = [float(value) for value in payload.get("values", [])]
    color_values = [str(value) for value in payload.get("colors", [GREEN, LINE])]
    if len(labels) != 2 or len(values) != 2 or len(color_values) != 2:
        raise SourceError("donut directive currently requires exactly two values")
    drawing = Drawing(available_width, 95)
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 10, 4, 84, 84
    pie.data = values
    # ReportLab 4 rejects ``None`` entries for ``Pie.labels``.  Leaving the
    # optional label list unset renders the same clean ring while remaining
    # compatible with both ReportLab 3 and 4.
    pie.slices[0].fillColor = colors.HexColor(color_values[0])
    pie.slices[1].fillColor = colors.HexColor(color_values[1])
    pie.strokeColor = colors.HexColor(PAPER)
    pie.strokeWidth = 0.5
    drawing.add(pie)
    drawing.add(Circle(52, 46, 23, fillColor=colors.HexColor(PAPER), strokeColor=None))
    drawing.add(
        String(
            52,
            43,
            "7 : 3",
            fontName=fonts["bold"],
            fontSize=10,
            fillColor=colors.HexColor(INK),
            textAnchor="middle",
        )
    )
    for index, (label, value, color_value) in enumerate(zip(labels, values, color_values)):
        y = 61 - index * 28
        drawing.add(Circle(130, y + 2, 4, fillColor=colors.HexColor(color_value), strokeColor=None))
        drawing.add(
            String(
                143,
                y,
                f"{label}  {value:g}%",
                fontName=fonts["body"],
                fontSize=8,
                fillColor=colors.HexColor(INK),
            )
        )
    return [
        Paragraph(html.escape(str(payload.get("title", "比例"))), styles["h2"]),
        drawing,
        Spacer(1, 3),
    ]


def _markdown_table(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    fonts: Mapping[str, str],
    rows: list[list[str]],
    available_width: float,
) -> Any:
    Paragraph, Table, TableStyle = rl["Paragraph"], rl["Table"], rl["TableStyle"]
    colors = rl["colors"]
    columns = len(rows[0])
    col_widths = [available_width / columns] * columns
    cells = [
        [
            Paragraph(_inline(cell, fonts), styles["small"] if row_index else styles["body"])
            for cell in row
        ]
        for row_index, row in enumerate(rows)
    ]
    table = Table(cells, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(GREEN_SOFT)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(GREEN_DARK)),
                ("FONTNAME", (0, 0), (-1, 0), fonts["bold"]),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor(LINE)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.HexColor(PAPER), colors.HexColor("#FAFBFC")],
                ),
            ]
        )
    )
    return table


def _render_block(
    rl: Mapping[str, Any],
    styles: Mapping[str, Any],
    fonts: Mapping[str, str],
    block: Block,
    available_width: float,
    metadata: Mapping[str, Any],
    missing: list[str],
) -> list[Any]:
    Paragraph, Spacer, XPreformatted = rl["Paragraph"], rl["Spacer"], rl["XPreformatted"]
    ListFlowable, ListItem = rl["ListFlowable"], rl["ListItem"]
    if block.kind == "paragraph":
        return [Paragraph(_inline(block.value, fonts), styles["body"])]
    if block.kind == "heading":
        return [Paragraph(_inline(block.value, fonts), styles["h2"])]
    if block.kind == "bullets":
        items = [
            ListItem(Paragraph(_inline(item, fonts), styles["body"]), leftIndent=10)
            for item in block.value
        ]
        return [
            ListFlowable(
                items,
                bulletType="bullet",
                start="circle",
                leftIndent=14,
                bulletFontName=fonts["body"],
                bulletFontSize=6,
                spaceAfter=4,
            )
        ]
    if block.kind == "table":
        return [_markdown_table(rl, styles, fonts, block.value, available_width), Spacer(1, 4)]
    if block.kind == "code":
        style = styles["code"].clone("CodeCJK" if CJK_RE.search(block.value) else "CodeMono")
        if CJK_RE.search(block.value):
            style.fontName = fonts["body"]
        return [XPreformatted(html.escape(block.value), style)]
    if block.kind == "cover":
        return _cover(rl, styles, fonts, metadata, block.value, available_width, missing)
    if block.kind == "bars":
        return _bars(rl, styles, fonts, block.value, available_width)
    if block.kind == "flow":
        return _flow(rl, styles, block.value, available_width)
    if block.kind == "gallery":
        return _gallery(rl, styles, fonts, block.value, available_width, missing)
    if block.kind == "image":
        return _single_image(rl, styles, fonts, block.value, available_width, missing)
    if block.kind == "callout":
        return _callout(rl, styles, fonts, block.value, available_width)
    if block.kind == "metrics":
        return _metrics(rl, styles, fonts, block.value, available_width)
    if block.kind == "donut":
        return _donut(rl, styles, fonts, block.value, available_width)
    raise SourceError(f"unsupported report block: {block.kind}")


def _header_footer(
    canvas: Any,
    doc: Any,
    *,
    rl: Mapping[str, Any],
    fonts: Mapping[str, str],
    metadata: Mapping[str, Any],
) -> None:
    colors, mm, A4 = rl["colors"], rl["mm"], rl["A4"]
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(colors.HexColor(PAPER))
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    canvas.setStrokeColor(colors.HexColor(GREEN if doc.page == 1 else LINE))
    canvas.setLineWidth(1.4 if doc.page == 1 else 0.45)
    canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
    if doc.page > 1:
        canvas.setFont(fonts["body"], 6.8)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(18 * mm, height - 10.5 * mm, str(metadata["subtitle"]))
        canvas.drawRightString(width - 18 * mm, height - 10.5 * mm, str(metadata["course"]))
    canvas.setStrokeColor(colors.HexColor(LINE))
    canvas.setLineWidth(0.45)
    canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
    canvas.setFont(fonts["body"], 6.6)
    canvas.setFillColor(colors.HexColor(MUTED))
    canvas.drawString(18 * mm, 8.5 * mm, "OJ Python Homework 2 · 实验报告")
    canvas.drawRightString(width - 18 * mm, 8.5 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build_pdf(
    source: ReportSource,
    output: Path = DEFAULT_OUTPUT,
    *,
    require_images: bool = False,
    allow_placeholders: bool = False,
) -> tuple[Path, tuple[str, ...]]:
    if source.unresolved and not allow_placeholders:
        raise SourceError(
            "unresolved final facts: "
            + ", ".join(source.unresolved)
            + ". Supply --set KEY=value for each fact."
        )
    rl = _load_reportlab()
    fonts = _register_fonts(rl["pdfmetrics"], rl["TTFont"], rl["UnicodeCIDFont"])
    styles = _paragraph_styles(rl, fonts)
    mm, A4 = rl["mm"], rl["A4"]
    PageBreak = rl["PageBreak"]
    output = output.resolve()
    if output.suffix.lower() != ".pdf":
        raise ValueError("output path must end with .pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_BUILD.parent.mkdir(parents=True, exist_ok=True)
    build_path = DEFAULT_BUILD.resolve()
    build_path.unlink(missing_ok=True)
    document = rl["SimpleDocTemplate"](
        str(build_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=str(source.metadata["title"]),
        author=str(source.metadata["author"]),
        subject="程序设计训练（Python）OJ 系统实验报告",
        creator="report/generate_report.py",
    )
    missing: list[str] = []
    story: list[Any] = []
    for page_index, page in enumerate(source.pages):
        if page_index:
            story.append(PageBreak())
        if page.number > 1:
            story.extend(_title_flowables(rl, styles, page))
        for block in page.blocks:
            story.extend(
                _render_block(
                    rl,
                    styles,
                    fonts,
                    block,
                    document.width,
                    source.metadata,
                    missing,
                )
            )
    if require_images and missing:
        raise SourceError("required screenshots are missing: " + ", ".join(sorted(set(missing))))
    document.build(
        story,
        onFirstPage=lambda canvas, doc: _header_footer(
            canvas, doc, rl=rl, fonts=fonts, metadata=source.metadata
        ),
        onLaterPages=lambda canvas, doc: _header_footer(
            canvas, doc, rl=rl, fonts=fonts, metadata=source.metadata
        ),
    )
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for final page-count verification") from exc
    actual_pages = len(PdfReader(str(build_path)).pages)
    expected_pages = int(source.metadata["expected_pages"])
    if actual_pages != expected_pages:
        raise RuntimeError(
            f"layout produced {actual_pages} pages; expected exactly {expected_pages}. "
            f"Inspect the intermediate build at {build_path}."
        )
    os.replace(build_path, output)
    return output, tuple(sorted(set(missing)))


def _parse_set(values: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise SourceError(f"--set expects KEY=value, got {raw!r}")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key or not value.strip():
            raise SourceError(f"--set expects a non-empty KEY and value, got {raw!r}")
        result[key] = value.strip()
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=value",
        help="override one front-matter fact (repeatable)",
    )
    parser.add_argument(
        "--check-source",
        action="store_true",
        help="parse and validate the source without importing ReportLab or writing a PDF",
    )
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="allow TODO final facts (layout development only)",
    )
    parser.add_argument(
        "--require-images",
        action="store_true",
        help="fail rather than drawing placeholders for missing screenshots",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source = parse_source(args.source.resolve(), overrides=_parse_set(args.set))
        if args.check_source:
            kinds = sorted({block.kind for page in source.pages for block in page.blocks})
            print(
                f"source ok: {len(source.pages)} pages; blocks={','.join(kinds)}; "
                f"unresolved={','.join(source.unresolved) or 'none'}"
            )
            return 0
        output, missing = build_pdf(
            source,
            args.output,
            require_images=args.require_images,
            allow_placeholders=args.allow_placeholders,
        )
        print(f"created {output}")
        if missing:
            print("placeholder images: " + ", ".join(missing))
        return 0
    except (OSError, RuntimeError, SourceError, ValueError) as exc:
        print(f"report build failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
