"""Safe, bounded attachment parsing for AI-assisted authoring.

Uploaded bytes are never executed and this module performs no persistence or
provider calls.  Extracted text remains untrusted user content; AI callers must
place it in a delimited data section rather than interpolate it into system
instructions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
from importlib import import_module
from io import BytesIO
import json
from pathlib import PurePosixPath
import re
from typing import Any
import unicodedata
import xml.etree.ElementTree as ET

from oj.safe_archive import ArchivePolicy, MIB, SafeArchiveError, read_safe_zip

SCHEMA_VERSION = "oj.attachment.v1"
MAX_FILE_BYTES = 10 * MIB
MAX_TASK_FILES = 8
MAX_TASK_BYTES = 32 * MIB
MAX_IMAGE_PIXELS = 20_000_000
MAX_EXTRACTED_CHARS = 100_000
MAX_PREVIEW_CHARS = 4_000
PARSER_VERSION = "oj-attachment-parser.v1"

_SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".ts",
    ".py",
    ".go",
    ".rs",
    ".swift",
    ".kt",
    ".kts",
    ".sh",
    ".sql",
}
_TEXT_EXTENSIONS = {".txt", ".md", ".json", ".yaml", ".yml", ".csv"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_MACRO_EXTENSIONS = {".docm", ".dotm", ".xlsm", ".xltm", ".pptm", ".ppsm"}
_ARCHIVE_MEMBER_EXTENSIONS = (
    _TEXT_EXTENSIONS | _SOURCE_EXTENSIONS | _IMAGE_EXTENSIONS | {".pdf", ".in", ".out", ".ans"}
)
_MIME_TYPES = {
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain", "text/x-markdown"},
    ".json": {"application/json", "text/json", "text/plain"},
    ".yaml": {"application/yaml", "application/x-yaml", "text/yaml", "text/plain"},
    ".yml": {"application/yaml", "application/x-yaml", "text/yaml", "text/plain"},
    ".csv": {"text/csv", "application/csv", "text/plain"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
}
for _extension in _SOURCE_EXTENSIONS:
    _MIME_TYPES[_extension] = {
        "text/plain",
        "application/octet-stream",
        "text/x-python",
        "text/x-c",
        "text/x-c++src",
        "application/javascript",
        "text/javascript",
    }

_PROMPT_INJECTION = re.compile(
    r"(?:ignore|disregard|override).{0,40}(?:previous|system|instruction)|"
    r"(?:system\s*prompt|reveal.{0,20}(?:secret|key|token))|"
    r"(?:忽略|覆盖).{0,20}(?:系统|之前|指令)|(?:系统提示词|泄露.{0,12}(?:密钥|令牌))",
    re.IGNORECASE | re.DOTALL,
)


class AttachmentError(Exception):
    """A stable attachment failure safe to return without uploaded content."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ParsedAttachment:
    attachment_id: str
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    kind: str
    preview: Mapping[str, Any]
    warning_codes: tuple[str, ...]
    created_at: str
    expires_at: str
    extracted_text: str = field(repr=False, default="")
    vision_bytes: bytes | None = field(repr=False, default=None)
    parser_version: str = PARSER_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "status": "ready",
            "kind": self.kind,
            "parser_version": self.parser_version,
            "capabilities": {
                "text": bool(self.extracted_text),
                "vision": self.vision_bytes is not None,
            },
            "preview": dict(self.preview),
            "warning_codes": list(self.warning_codes),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class _Extraction:
    kind: str
    text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    vision_bytes: bytes | None = None


def _error(code: str, message: str) -> None:
    raise AttachmentError(code, message)


def _extension(filename: str) -> str:
    if (
        not isinstance(filename, str)
        or not filename
        or len(filename) > 255
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or any(ord(character) < 32 for character in filename)
    ):
        _error("UNSUPPORTED_MEDIA", "The attachment filename is invalid.")
    filename = unicodedata.normalize("NFC", filename)
    extension = PurePosixPath(filename).suffix.casefold()
    if extension in _MACRO_EXTENSIONS:
        _error("UNSUPPORTED_MEDIA", "Macro-enabled documents are not supported.")
    if extension not in _MIME_TYPES:
        _error("UNSUPPORTED_MEDIA", "The attachment type is not supported.")
    return extension


def _check_mime(extension: str, media_type: str) -> str:
    if not isinstance(media_type, str):
        _error("MIME_MISMATCH", "The attachment media type is invalid.")
    normalized = media_type.partition(";")[0].strip().casefold()
    if normalized not in _MIME_TYPES[extension]:
        _error("MIME_MISMATCH", "The filename and media type do not match.")
    return normalized


def _decode_text(raw: bytes) -> str:
    if b"\x00" in raw:
        _error("MIME_MISMATCH", "The uploaded file does not contain plain UTF-8 text.")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        _error("PARSE_FAILED", "The text attachment must use UTF-8.")


def _text_extraction(raw: bytes, extension: str) -> _Extraction:
    text = _decode_text(raw)
    if extension == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError:
            _error("PARSE_FAILED", "The JSON attachment is invalid.")
    kind = "code" if extension in _SOURCE_EXTENSIONS else "text"
    return _Extraction(kind=kind, text=text)


def _safe_xml(raw: bytes) -> ET.Element:
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        _error("PARSE_FAILED", "Document XML declarations are not supported.")
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        _error("PARSE_FAILED", "The document contains invalid XML.")


def _ooxml_members(raw: bytes, kind: str) -> Mapping[str, Any]:
    base = {"document": "word", "spreadsheet": "xl", "presentation": "ppt"}[kind]
    blocked_parts = {
        "activex",
        "connections",
        "embeddings",
        "externallinks",
        "macrosheets",
        "vba",
    }

    def validator(path: str) -> bool:
        lowered = path.casefold()
        if any(part in lowered.split("/") for part in blocked_parts):
            return False
        if path == "[Content_Types].xml" or path == "_rels/.rels":
            return True
        if re.fullmatch(r"docProps/[^/]+\.xml", path, re.IGNORECASE):
            return True
        if not lowered.startswith(f"{base}/"):
            return False
        return lowered.endswith((".xml", ".rels", ".png", ".jpg", ".jpeg", ".webp"))

    try:
        members = read_safe_zip(
            raw,
            policy=ArchivePolicy(
                max_entries=500,
                max_compressed_bytes=MAX_FILE_BYTES,
                max_total_bytes=50 * MIB,
                max_entry_bytes=2 * MIB,
                max_ratio=200,
                reject_nested_archives=False,
            ),
            path_validator=validator,
        )
    except SafeArchiveError as exc:
        code = "ENCRYPTED" if exc.code == "ARCHIVE_ENCRYPTED" else "PARSE_FAILED"
        raise AttachmentError(code, "The Office document is unsafe or damaged.") from exc
    content_types = members.get("[Content_Types].xml")
    if content_types is None:
        _error("MIME_MISMATCH", "The Office document type could not be verified.")
    lowered_types = content_types.data.lower()
    if b"macroenabled" in lowered_types or any("vba" in path.casefold() for path in members):
        _error("UNSUPPORTED_MEDIA", "Macro-enabled documents are not supported.")
    expected_type = {
        "document": b"wordprocessingml.document.main+xml",
        "spreadsheet": b"spreadsheetml.sheet.main+xml",
        "presentation": b"presentationml.presentation.main+xml",
    }[kind]
    if expected_type not in lowered_types:
        _error("MIME_MISMATCH", "The Office container does not match its filename.")
    return members


def _docx_extraction(raw: bytes) -> _Extraction:
    members = _ooxml_members(raw, "document")
    member = members.get("word/document.xml")
    if member is None:
        _error("MIME_MISMATCH", "The file is not a supported DOCX document.")
    root = _safe_xml(member.data)
    parts = [node.text or "" for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "t"]
    return _Extraction(kind="document", text="\n".join(filter(None, parts)))


def _xlsx_extraction(raw: bytes) -> _Extraction:
    members = _ooxml_members(raw, "spreadsheet")
    sheets = sorted(
        (
            member
            for path, member in members.items()
            if re.fullmatch(r"xl/worksheets/[^/]+\.xml", path, re.IGNORECASE)
        ),
        key=lambda member: member.path.casefold(),
    )
    if not sheets:
        _error("MIME_MISMATCH", "The file is not a supported XLSX workbook.")
    shared: list[str] = []
    if "xl/sharedStrings.xml" in members:
        root = _safe_xml(members["xl/sharedStrings.xml"].data)
        for item in root.iter():
            if item.tag.rsplit("}", 1)[-1] == "si":
                shared.append(
                    "".join(
                        node.text or ""
                        for node in item.iter()
                        if node.tag.rsplit("}", 1)[-1] == "t"
                    )
                )
    rows: list[str] = []
    formula_ignored = False
    for sheet in sheets:
        root = _safe_xml(sheet.data)
        for row in (node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "row"):
            values: list[str] = []
            for cell in (node for node in row if node.tag.rsplit("}", 1)[-1] == "c"):
                children = {child.tag.rsplit("}", 1)[-1]: child for child in cell}
                if "f" in children:
                    formula_ignored = True
                    values.append("")
                    continue
                value = children.get("v")
                text = value.text if value is not None and value.text is not None else ""
                if cell.attrib.get("t") == "s" and text:
                    try:
                        text = shared[int(text)]
                    except (ValueError, IndexError):
                        _error("PARSE_FAILED", "The workbook shared-string table is invalid.")
                elif cell.attrib.get("t") == "inlineStr":
                    text = "".join(
                        node.text or ""
                        for node in cell.iter()
                        if node.tag.rsplit("}", 1)[-1] == "t"
                    )
                values.append(text)
            rows.append("\t".join(values).rstrip())
    warnings = ("FORMULAS_IGNORED",) if formula_ignored else ()
    return _Extraction(kind="spreadsheet", text="\n".join(rows), warnings=warnings)


def _pptx_extraction(raw: bytes) -> _Extraction:
    members = _ooxml_members(raw, "presentation")
    slides = sorted(
        (member for path, member in members.items() if path.startswith("ppt/slides/slide")),
        key=lambda member: member.path.casefold(),
    )
    if not slides:
        _error("MIME_MISMATCH", "The file is not a supported PPTX presentation.")
    blocks = []
    for slide in slides:
        root = _safe_xml(slide.data)
        blocks.append(
            "\n".join(
                node.text or ""
                for node in root.iter()
                if node.tag.rsplit("}", 1)[-1] == "t" and node.text
            )
        )
    return _Extraction(kind="presentation", text="\n\n".join(blocks))


def _pdf_extraction(raw: bytes) -> _Extraction:
    try:
        pypdf = import_module("pypdf")
    except ModuleNotFoundError:
        _error("PARSE_UNAVAILABLE", "PDF text extraction is not installed on this server.")
    try:
        reader = pypdf.PdfReader(BytesIO(raw), strict=True)
        if reader.is_encrypted:
            _error("ENCRYPTED", "Encrypted PDF files are not supported.")
        if len(reader.pages) > 100:
            _error("TOO_LARGE", "The PDF exceeds the page limit.")
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except AttachmentError:
        raise
    except Exception:
        _error("PARSE_FAILED", "The PDF could not be parsed safely.")
    return _Extraction(kind="document", text=text, metadata={"pages": len(reader.pages)})


def _image_extraction(raw: bytes, extension: str, vision_available: bool) -> _Extraction:
    valid_magic = {
        ".png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": raw.startswith(b"\xff\xd8\xff"),
        ".jpeg": raw.startswith(b"\xff\xd8\xff"),
        ".webp": len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
    }[extension]
    if not valid_magic:
        _error("MIME_MISMATCH", "The image signature does not match its filename.")
    try:
        image_module = import_module("PIL.Image")
    except ModuleNotFoundError:
        _error("PARSE_UNAVAILABLE", "Image validation is not installed on this server.")
    try:
        with image_module.open(BytesIO(raw)) as image:
            width, height = image.size
            format_name = image.format
            frames = getattr(image, "n_frames", 1)
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                _error("TOO_LARGE", "The image exceeds the pixel limit.")
            image.verify()
    except AttachmentError:
        raise
    except Exception:
        _error("PARSE_FAILED", "The image could not be validated safely.")
    warnings = () if vision_available else ("VISION_UNAVAILABLE",)
    return _Extraction(
        kind="image",
        metadata={"width": width, "height": height, "format": format_name, "frames": frames},
        warnings=warnings,
        vision_bytes=raw if vision_available else None,
    )


def _archive_extraction(raw: bytes) -> _Extraction:
    def member_allowed(path: str) -> bool:
        return PurePosixPath(path).suffix.casefold() in _ARCHIVE_MEMBER_EXTENSIONS

    try:
        members = read_safe_zip(raw, path_validator=member_allowed)
    except SafeArchiveError as exc:
        raise AttachmentError("ARCHIVE_UNSAFE", exc.message) from exc
    native_manifests = [
        path for path in members if path == "problem.json" or path.endswith("/problem.json")
    ]
    if native_manifests:
        try:
            from oj.problem_import import ImportError as ProblemImportError
            from oj.problem_import import parse_native_archive

            parsed = parse_native_archive(raw)
        except ProblemImportError as exc:
            code = "ARCHIVE_UNSAFE" if exc.code == "ARCHIVE_UNSAFE" else "PARSE_FAILED"
            raise AttachmentError(code, "The problem archive is invalid or unsupported.") from exc
        problem = parsed.problem
        sections = [
            f"Title: {problem['title']}",
            str(problem["description"]),
            f"Input:\n{problem['input_description']}",
            f"Output:\n{problem['output_description']}",
            f"Constraints:\n{problem['constraints']}",
        ]
        for index, case in enumerate(problem["samples"], start=1):
            sections.append(
                f"Sample {index} input:\n{case['input']}\nSample {index} output:\n{case['output']}"
            )
        return _Extraction(
            kind="problem_archive",
            text="\n\n".join(sections),
            metadata={
                "source_format": parsed.source_format,
                "problem_id": problem["id"],
                "title": problem["title"],
                "sample_count": parsed.sample_count,
                "testcase_count": parsed.testcase_count,
            },
            warnings=tuple(
                [str(item["code"]) for item in parsed.warnings] + ["PROBLEM_ARCHIVE_REFERENCE_ONLY"]
            ),
        )

    sections: list[str] = []
    images: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path, member in sorted(members.items()):
        extension = PurePosixPath(path).suffix.casefold()
        if extension in _IMAGE_EXTENSIONS:
            extracted = _image_extraction(member.data, extension, False)
            images.append({"path": path, **dict(extracted.metadata)})
            warnings.extend(extracted.warnings)
        else:
            if extension == ".pdf":
                if not member.data.startswith(b"%PDF-"):
                    _error("MIME_MISMATCH", "A ZIP member has an invalid PDF signature.")
                extracted = _pdf_extraction(member.data)
            else:
                extracted = _text_extraction(member.data, extension)
            sections.append(f"--- {path} ---\n{extracted.text}")
    paths = sorted(members)
    metadata: dict[str, Any] = {
        "file_count": len(paths),
        "files": paths[:50],
        "images": images[:20],
    }
    if len(paths) > 50:
        warnings.append("ARCHIVE_FILE_LIST_TRUNCATED")
    if len(images) > 20:
        warnings.append("ARCHIVE_IMAGE_LIST_TRUNCATED")
    return _Extraction(
        kind="archive",
        text="\n\n".join(sections),
        metadata=metadata,
        warnings=tuple(warnings),
    )


def _extract(raw: bytes, extension: str, vision_available: bool) -> _Extraction:
    if extension in _TEXT_EXTENSIONS or extension in _SOURCE_EXTENSIONS:
        return _text_extraction(raw, extension)
    if extension == ".pdf":
        if not raw.startswith(b"%PDF-"):
            _error("MIME_MISMATCH", "The PDF signature does not match its filename.")
        return _pdf_extraction(raw)
    if extension == ".docx":
        return _docx_extraction(raw)
    if extension == ".xlsx":
        return _xlsx_extraction(raw)
    if extension == ".pptx":
        return _pptx_extraction(raw)
    if extension in _IMAGE_EXTENSIONS:
        return _image_extraction(raw, extension, vision_available)
    if extension == ".zip":
        if not raw.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            _error("MIME_MISMATCH", "The ZIP signature does not match its filename.")
        return _archive_extraction(raw)
    _error("UNSUPPORTED_MEDIA", "The attachment type is not supported.")


def _bounded_text(text: str, warnings: list[str]) -> str:
    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS]
        warnings.append("TEXT_TRUNCATED")
    if _PROMPT_INJECTION.search(text):
        warnings.append("UNTRUSTED_INSTRUCTIONS")
    return text


def parse_attachment(
    raw: bytes,
    *,
    filename: str,
    media_type: str,
    attachment_id: str,
    created_at: str,
    expires_at: str,
    vision_available: bool = False,
) -> ParsedAttachment:
    """Validate one attachment and produce public metadata plus private text."""

    if not isinstance(raw, bytes):
        _error("PARSE_FAILED", "Attachment content must be bytes.")
    if not raw or len(raw) > MAX_FILE_BYTES:
        _error("TOO_LARGE", "The attachment exceeds the file size limit.")
    if not all(
        isinstance(value, str) and value for value in (attachment_id, created_at, expires_at)
    ):
        _error("PARSE_FAILED", "Attachment lifecycle metadata is invalid.")
    extension = _extension(filename)
    normalized_media_type = _check_mime(extension, media_type)
    extraction = _extract(raw, extension, vision_available)
    warnings = list(extraction.warnings)
    text = _bounded_text(extraction.text, warnings)
    preview: dict[str, Any] = dict(extraction.metadata)
    preview.update(
        {
            "text": text[:MAX_PREVIEW_CHARS],
            "text_truncated": len(text) > MAX_PREVIEW_CHARS,
            "character_count": len(text),
        }
    )
    return ParsedAttachment(
        attachment_id=attachment_id,
        filename=unicodedata.normalize("NFC", filename),
        media_type=normalized_media_type,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        kind=extraction.kind,
        preview=preview,
        warning_codes=tuple(dict.fromkeys(warnings)),
        created_at=created_at,
        expires_at=expires_at,
        extracted_text=text,
        vision_bytes=extraction.vision_bytes,
    )


def validate_attachment_batch(attachments: Sequence[ParsedAttachment]) -> None:
    """Enforce per-task count, raw-byte total, and identity uniqueness."""

    if len(attachments) > MAX_TASK_FILES:
        _error("TOO_LARGE", "A task may contain at most eight attachments.")
    if sum(item.size_bytes for item in attachments) > MAX_TASK_BYTES:
        _error("TOO_LARGE", "The task attachment total exceeds the size limit.")
    identifiers = {item.attachment_id for item in attachments}
    if len(identifiers) != len(attachments):
        _error("HASH_MISMATCH", "Attachment references must be unique.")


def validate_attachment_reference(
    attachment: ParsedAttachment, *, attachment_id: str, sha256: str
) -> None:
    """Bind a task reference to the exact extracted snapshot it names."""

    if attachment.attachment_id != attachment_id or attachment.sha256 != sha256:
        _error("HASH_MISMATCH", "The attachment reference does not match its snapshot.")


__all__ = [
    "AttachmentError",
    "MAX_FILE_BYTES",
    "MAX_IMAGE_PIXELS",
    "MAX_TASK_BYTES",
    "MAX_TASK_FILES",
    "PARSER_VERSION",
    "ParsedAttachment",
    "SCHEMA_VERSION",
    "parse_attachment",
    "validate_attachment_batch",
    "validate_attachment_reference",
]
