"""Bounded, in-memory ZIP inspection shared by import and attachment services.

The helpers in this module never extract files to disk.  ZIP member names and
metadata are treated as untrusted even when the caller already checked the
outer file extension and MIME type.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
import stat
import unicodedata
import zipfile

MIB = 1024 * 1024


class SafeArchiveError(Exception):
    """A stable, presentation-safe archive validation failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ArchivePolicy:
    max_entries: int = 500
    max_compressed_bytes: int = 50 * MIB
    max_total_bytes: int = 100 * MIB
    max_entry_bytes: int = 2 * MIB
    max_ratio: float = 200.0
    reject_nested_archives: bool = True


@dataclass(frozen=True)
class ArchiveMember:
    path: str
    data: bytes
    compressed_size: int


PathValidator = Callable[[str], bool]

_NESTED_SUFFIXES = (
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".tgz",
    ".gz",
    ".bz2",
    ".xz",
    ".jar",
    ".war",
    ".docx",
    ".docm",
    ".xlsx",
    ".xlsm",
    ".pptx",
    ".pptm",
)


def _fail(code: str, message: str) -> None:
    raise SafeArchiveError(code, message)


def _safe_path(raw_name: str) -> tuple[str, str, bool]:
    if not isinstance(raw_name, str) or not raw_name:
        _fail("ARCHIVE_PATH_INVALID", "The archive contains an invalid member path.")
    if len(raw_name) > 1_024:
        _fail("ARCHIVE_PATH_INVALID", "An archive member path exceeds the length limit.")
    if "\x00" in raw_name:
        _fail("ARCHIVE_PATH_INVALID", "The archive contains an invalid member path.")
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in raw_name):
        _fail("ARCHIVE_PATH_INVALID", "Control characters are not allowed in archive paths.")
    if "\\" in raw_name:
        _fail("ARCHIVE_PATH_AMBIGUOUS", "Backslashes are not allowed in archive paths.")
    if raw_name.startswith("/") or raw_name.startswith("//"):
        _fail("ARCHIVE_PATH_ABSOLUTE", "Absolute archive paths are not allowed.")
    is_directory = raw_name.endswith("/")
    stripped = raw_name[:-1] if is_directory else raw_name
    pieces = stripped.split("/")
    if not stripped or any(piece in {"", ".", ".."} for piece in pieces):
        _fail("ARCHIVE_PATH_TRAVERSAL", "Unsafe archive path segments are not allowed.")
    if any(len(piece) > 255 for piece in pieces):
        _fail("ARCHIVE_PATH_INVALID", "An archive path segment exceeds the length limit.")
    if any(":" in piece for piece in pieces):
        _fail("ARCHIVE_PATH_ABSOLUTE", "Drive and alternate-stream paths are not allowed.")
    normalized = "/".join(unicodedata.normalize("NFC", piece) for piece in pieces)
    duplicate_key = "/".join(unicodedata.normalize("NFKC", piece).casefold() for piece in pieces)
    return normalized, duplicate_key, is_directory


def _is_special_member(info: zipfile.ZipInfo, is_directory: bool) -> bool:
    if info.create_system != 3:
        return False
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    if not kind:
        return False
    if is_directory:
        return kind != stat.S_IFDIR
    return kind != stat.S_IFREG


def _has_archive_magic(data: bytes) -> bool:
    prefixes = (
        b"PK\x03\x04",
        b"PK\x05\x06",
        b"PK\x07\x08",
        b"Rar!\x1a\x07",
        b"7z\xbc\xaf\x27\x1c",
        b"\x1f\x8b",
        b"BZh",
        b"\xfd7zXZ\x00",
    )
    if data.startswith(prefixes):
        return True
    return len(data) >= 265 and data[257:262] == b"ustar"


def read_safe_zip(
    raw: bytes,
    *,
    policy: ArchivePolicy | None = None,
    path_validator: PathValidator | None = None,
) -> Mapping[str, ArchiveMember]:
    """Validate and return an immutable-style mapping of in-memory members.

    ``path_validator`` is applied to every non-directory normalized path.  It
    lets a format parser reject unknown members before any of their data is
    consumed.
    """

    policy = policy or ArchivePolicy()
    if not isinstance(raw, bytes):
        _fail("ARCHIVE_INVALID", "Archive content must be bytes.")
    if not raw or len(raw) > policy.max_compressed_bytes:
        _fail("ARCHIVE_SIZE_LIMIT", "The compressed archive exceeds the size limit.")
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
    except (zipfile.BadZipFile, ValueError, OSError):
        _fail("ARCHIVE_CORRUPT", "The uploaded file is not a valid ZIP archive.")

    result: dict[str, ArchiveMember] = {}
    seen: set[str] = set()
    total = 0
    with archive:
        infos = archive.infolist()
        if len(infos) > policy.max_entries:
            _fail("ARCHIVE_ENTRY_LIMIT", "The archive contains too many entries.")
        for info in infos:
            # ``zipfile`` normalizes backslashes on Windows in ``filename``;
            # ``orig_filename`` preserves the attacker-controlled spelling.
            original_name = getattr(info, "orig_filename", info.filename)
            path, duplicate_key, is_directory = _safe_path(original_name)
            if duplicate_key in seen:
                _fail(
                    "ARCHIVE_DUPLICATE_PATH",
                    "The archive contains duplicate or Unicode-equivalent paths.",
                )
            seen.add(duplicate_key)
            if _is_special_member(info, is_directory):
                _fail("ARCHIVE_SPECIAL_FILE", "Links and special files are not allowed.")
            if info.flag_bits & 0x1:
                _fail("ARCHIVE_ENCRYPTED", "Encrypted archive entries are not supported.")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                _fail("ARCHIVE_COMPRESSION", "The archive uses an unsupported compression method.")
            if is_directory:
                continue
            if path_validator is not None and not path_validator(path):
                _fail("ARCHIVE_UNKNOWN_PATH", "The archive contains an unsupported path.")
            if info.file_size < 0 or info.file_size > policy.max_entry_bytes:
                _fail("ARCHIVE_ENTRY_SIZE_LIMIT", "An archive entry exceeds the size limit.")
            total += info.file_size
            if total > policy.max_total_bytes:
                _fail("ARCHIVE_TOTAL_SIZE_LIMIT", "The expanded archive exceeds the size limit.")
            if info.file_size:
                if (
                    info.compress_size <= 0
                    or info.file_size / info.compress_size > policy.max_ratio
                ):
                    _fail(
                        "ARCHIVE_COMPRESSION_RATIO",
                        "An archive entry exceeds the compression-ratio limit.",
                    )
            try:
                data = archive.read(info)
            except (RuntimeError, zipfile.BadZipFile, OSError, EOFError):
                _fail("ARCHIVE_CORRUPT", "The archive could not be read safely.")
            if len(data) != info.file_size:
                _fail("ARCHIVE_CORRUPT", "An archive entry has inconsistent metadata.")
            if policy.reject_nested_archives and (
                path.casefold().endswith(_NESTED_SUFFIXES) or _has_archive_magic(data)
            ):
                _fail("ARCHIVE_NESTED", "Nested archives are not supported.")
            result[path] = ArchiveMember(path, data, info.compress_size)
    if not result:
        _fail("ARCHIVE_EMPTY", "The archive does not contain any files.")
    return result


__all__ = [
    "ArchiveMember",
    "ArchivePolicy",
    "MIB",
    "PathValidator",
    "SafeArchiveError",
    "read_safe_zip",
]
