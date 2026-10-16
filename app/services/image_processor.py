"""app.services.image_processor - Image resizing, safe EXIF extraction, dHash, and storage."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, ImageOps

from app.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_DB_PATH,
    EXIF_DATETIME_ORIGINAL_ID,
    EXIF_IFD_ID,
    EXIF_IFD_TAG_NAMES,
    EXIF_OFFSET_TIME_ID,
    EXIF_OFFSET_TIME_ORIGINAL_ID,
    MAX_BASE64_IMAGE_BYTES,
    MAX_IMAGE_EDGE,
    ORIGINALS_DIR,
    ORIGINALS_DIR_NAME,
    PROJECT_ROOT,
    SAFE_EXIF_FIELDS,
    SUPPORTED_FORMATS,
    UPLOAD_EXIF_FIELDS,
)


def compute_dhash_from_bytes(image_bytes: bytes, hash_size: int = 8) -> int:
    """Compute 64-bit difference hash (dHash) from image bytes."""
    with Image.open(BytesIO(image_bytes)) as img:
        gray = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.BILINEAR)
        pixels = gray.tobytes()
        diff = 0
        for row in range(hash_size):
            r_start = row * (hash_size + 1)
            for col in range(hash_size):
                if pixels[r_start + col] > pixels[r_start + col + 1]:
                    diff |= 1 << (row * hash_size + col)
        return diff


def hamming_distance(h1: int, h2: int) -> int:
    """Compute Hamming distance between two 64-bit perceptual hashes."""
    return bin((int(h1) ^ int(h2)) & 0xFFFFFFFFFFFFFFFF).count("1")


def dhash_to_sqlite(val: int | None) -> int | None:
    """Convert 64-bit unsigned perceptual hash to signed 64-bit integer for SQLite INTEGER compatibility."""
    if val is None:
        return None
    val = int(val) & 0xFFFFFFFFFFFFFFFF
    if val >= (1 << 63):
        val -= (1 << 64)
    return val


def dhash_from_sqlite(val: int | None) -> int | None:
    """Restore 64-bit unsigned perceptual hash from SQLite signed 64-bit integer."""
    if val is None:
        return None
    return int(val) & 0xFFFFFFFFFFFFFFFF


@dataclass(frozen=True)
class PreparedPhoto:
    source_filename: str
    sha256: str
    width: int
    height: int
    image_format: str
    safe_exif: dict[str, Any]
    upload_bytes: bytes
    upload_mime_type: str
    thumbnail_bytes: bytes | None = None
    dhash: int | None = None


def make_thumbnail_bytes(image_path_or_bytes: Path | bytes | str, max_dim: int = 800, quality: int = 82) -> bytes:
    """Generate lightweight WebP thumbnail from image file path or raw bytes without leaking handles."""
    if isinstance(image_path_or_bytes, (str, Path)):
        data = Path(image_path_or_bytes).read_bytes()
    else:
        data = image_path_or_bytes
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=quality)
        return out.getvalue()


def get_original_photo_path(db_path: str | Path, sha256: str, mime_type: str) -> Path:
    """Return the managed high-resolution path for a stored, privacy-filtered upload."""
    suffix = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(mime_type)
    if suffix is None:
        raise ValueError(f"지원하지 않는 업로드 MIME 형식입니다: {mime_type}")
    target_path = Path(db_path).expanduser().parent / ORIGINALS_DIR_NAME / f"{sha256}{suffix}"
    if not target_path.exists():
        legacy_path = PROJECT_ROOT / ORIGINALS_DIR_NAME / f"{sha256}{suffix}"
        if legacy_path.exists():
            return legacy_path
    return target_path


def save_original_photo(db_path: str | Path, photo: PreparedPhoto) -> Path:
    """Store the privacy-filtered high-resolution upload beside the SQLite database safely on Windows."""
    target = get_original_photo_path(db_path, photo.sha256, photo.upload_mime_type)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        temporary.write_bytes(photo.upload_bytes)
        temporary.replace(target)
    except OSError:
        if target.exists():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return target
        target.write_bytes(photo.upload_bytes)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return target


def _json_safe(value: Any) -> Any:
    """Convert Pillow EXIF values into JSON-compatible primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value[:128].decode("utf-8", errors="replace")
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _safe_exif_tag_sections(
    image: Image.Image,
) -> tuple[dict[int, Any], dict[int, Any]]:
    """Return allowlisted root and EXIF-IFD tags without reading GPS or other IFDs."""
    exif = image.getexif()
    root_tags: dict[int, Any] = {}
    for tag_id, value in exif.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        if name in SAFE_EXIF_FIELDS and name not in EXIF_IFD_TAG_NAMES:
            root_tags[tag_id] = value

    exif_ifd_tags: dict[int, Any] = {}
    try:
        exif_ifd = exif.get_ifd(EXIF_IFD_ID)
    except (AttributeError, KeyError, TypeError, ValueError):
        exif_ifd = {}
    for tag_id, value in exif_ifd.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        if name in SAFE_EXIF_FIELDS and name in EXIF_IFD_TAG_NAMES:
            exif_ifd_tags[tag_id] = value
    return root_tags, exif_ifd_tags


def extract_safe_exif(image: Image.Image) -> dict[str, Any]:
    """Extract only photography-related EXIF fields; never read the GPS IFD."""
    root_tags, exif_ifd_tags = _safe_exif_tag_sections(image)
    collected: dict[str, Any] = {}
    for tags in (root_tags, exif_ifd_tags):
        for tag_id, value in tags.items():
            name = ExifTags.TAGS.get(tag_id, str(tag_id))
            if name in SAFE_EXIF_FIELDS:
                collected[name] = _json_safe(value)
    return collected


def _build_safe_upload_exif_bytes(image: Image.Image) -> bytes:
    root_tags, exif_ifd_tags = _safe_exif_tag_sections(image)
    safe_exif = Image.Exif()
    safe_root_tags = {
        tag_id: value
        for tag_id, value in root_tags.items()
        if ExifTags.TAGS.get(tag_id, str(tag_id)) in UPLOAD_EXIF_FIELDS
    }
    safe_nested_tags = {
        tag_id: value
        for tag_id, value in exif_ifd_tags.items()
        if ExifTags.TAGS.get(tag_id, str(tag_id)) in UPLOAD_EXIF_FIELDS
    }
    for tag_id, value in safe_root_tags.items():
        safe_exif[tag_id] = value
    if safe_nested_tags:
        safe_exif[EXIF_IFD_ID] = safe_nested_tags
    return safe_exif.tobytes() if safe_root_tags or safe_nested_tags else b""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _save_as_jpeg(image: Image.Image, quality: int, safe_exif: bytes) -> bytes:
    output = BytesIO()
    save_options: dict[str, Any] = {
        "format": "JPEG",
        "quality": quality,
        "optimize": True,
    }
    if safe_exif:
        save_options["exif"] = safe_exif
    _flatten_to_rgb(image).save(output, **save_options)
    return output.getvalue()


def _encode_with_safe_exif(
    image: Image.Image,
    source_format: str,
    safe_exif: bytes,
) -> tuple[bytes, str]:
    output = BytesIO()
    if source_format in {"JPEG", "MPO"}:
        save_options: dict[str, Any] = {
            "format": "JPEG",
            "quality": 90,
            "optimize": True,
        }
        mime_type = "image/jpeg"
    elif source_format == "PNG":
        save_options = {"format": "PNG", "optimize": True}
        mime_type = "image/png"
    elif source_format == "WEBP":
        save_options = {"format": "WEBP", "quality": 90, "method": 6}
        mime_type = "image/webp"
    else:
        raise ValueError("지원 형식은 JPEG, MPO, PNG, WEBP입니다.")

    if safe_exif:
        save_options["exif"] = safe_exif
    if source_format in {"JPEG", "MPO"}:
        _flatten_to_rgb(image).save(output, **save_options)
    else:
        image.save(output, **save_options)

    data = output.getvalue()
    encoded_size = 4 * ((len(data) + 2) // 3)
    if encoded_size <= MAX_BASE64_IMAGE_BYTES:
        return data, mime_type

    for edge, quality in ((3072, 88), (2560, 82), (2048, 75)):
        smaller = image.copy()
        smaller.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        data = _save_as_jpeg(smaller, quality, safe_exif)
        encoded_size = 4 * ((len(data) + 2) // 3)
        if encoded_size <= MAX_BASE64_IMAGE_BYTES:
            return data, "image/jpeg"
    raise ValueError("이미지 용량이 너무 큽니다. 더 작은 JPEG/MPO/PNG/WEBP 파일을 사용해 주세요.")


def prepare_photo_from_bytes(data: bytes, filename: str) -> PreparedPhoto:
    """Read safe EXIF and keep only allowlisted fields in memory from raw image bytes."""
    with Image.open(BytesIO(data)) as source:
        source_format = (source.format or "").upper()
        if source_format not in SUPPORTED_FORMATS:
            raise ValueError("지원하지 않는 이미지 형식입니다. JPEG, MPO, PNG, WEBP만 사용할 수 있습니다.")
        safe_exif = extract_safe_exif(source)
        safe_upload_exif = _build_safe_upload_exif_bytes(source)
        oriented = ImageOps.exif_transpose(source)
        oriented.load()
        width, height = oriented.size
        oriented.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
        upload_bytes, upload_mime_type = _encode_with_safe_exif(
            oriented,
            source_format,
            safe_upload_exif,
        )

        thumb_img = oriented.copy()
        thumb_img.thumbnail((800, 800), Image.Resampling.LANCZOS)
        thumb_buf = BytesIO()
        if thumb_img.mode not in ("RGB", "RGBA"):
            thumb_img = thumb_img.convert("RGB")
        thumb_img.save(thumb_buf, format="WEBP", quality=82)
        thumbnail_bytes = thumb_buf.getvalue()
        dhash_val = compute_dhash_from_bytes(thumbnail_bytes)

    return PreparedPhoto(
        source_filename=filename,
        sha256=hashlib.sha256(data).hexdigest(),
        width=width,
        height=height,
        image_format=source_format,
        safe_exif=safe_exif,
        upload_bytes=upload_bytes,
        upload_mime_type=upload_mime_type,
        thumbnail_bytes=thumbnail_bytes,
        dhash=dhash_val,
    )


def prepare_photo(image_path: str | Path) -> PreparedPhoto:
    """Read safe EXIF and keep only allowlisted fields in the upload image."""
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"사진 파일을 찾을 수 없습니다: {path}")
    data = path.read_bytes()
    return prepare_photo_from_bytes(data, filename=path.name)
