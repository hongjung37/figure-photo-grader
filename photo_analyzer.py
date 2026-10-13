from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from PIL import ExifTags, Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, field_validator
from photo_html_report import save_html_report
from photo_tag_schema import AESTHETIC_TAG_CATEGORIES, AESTHETIC_TAG_OPTIONS, AestheticTags

DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_DB_PATH = Path(__file__).resolve().with_name("photo_analysis.sqlite3")
ENV_FILE_PATH = Path(__file__).resolve().with_name(".env")
SUPPORTED_FORMATS = {
    "JPEG": "image/jpeg",
    "MPO": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
MAX_IMAGE_EDGE = 4096
# Keep base64 image data well below Gemini's 20 MB inline-request limit,
# leaving room for the prompt and JSON envelope.
MAX_BASE64_IMAGE_BYTES = 18 * 1024 * 1024
EXIF_IFD_ID = 34665

# Deliberate allowlist: omit GPS, timestamps, owner/comment fields, maker notes,
# and camera/lens serial numbers from the upload image, SQLite, and model prompt.
SAFE_EXIF_FIELDS = {
    "Make",
    "Model",
    "LensModel",
    "LensSpecification",
    "ExposureTime",
    "FNumber",
    "ExposureProgram",
    "ISOSpeedRatings",
    "PhotographicSensitivity",
    "ShutterSpeedValue",
    "ApertureValue",
    "ExposureBiasValue",
    "MaxApertureValue",
    "MeteringMode",
    "Flash",
    "FocalLength",
    "FocalLengthIn35mmFilm",
    "WhiteBalance",
    "ExposureMode",
    "SceneCaptureType",
    "DigitalZoomRatio",
    "LightSource",
    "ColorSpace",
    "Orientation",
}
EXIF_IFD_TAG_NAMES = SAFE_EXIF_FIELDS - {"Make", "Model", "Orientation"}
UPLOAD_EXIF_FIELDS = SAFE_EXIF_FIELDS - {"Orientation"}


class PhotoAnalysis(BaseModel):
    """Strict JSON model returned by Gemini and stored in SQLite."""

    model_config = ConfigDict(extra="forbid")

    composition_score: float = Field(description="구도 점수, 0~10")
    composition_notes: str = Field(description="구도의 장점과 아쉬운 점")
    lighting_score: float = Field(description="조명 점수, 0~10")
    lighting_notes: str = Field(description="빛의 방향, 노출, 명암에 대한 평가")
    color_score: float = Field(description="색감 점수, 0~10")
    color_notes: str = Field(description="색조, 채도, 색 조화에 대한 평가")
    technique_score: float = Field(description="촬영 기술 점수, 0~10")
    technique_notes: str = Field(description="초점, 흔들림, 심도, 촬영 설정의 적절성")
    final_score: float = Field(description="사진 전체에 대한 최종 점수, 0~10")
    final_reason: str = Field(description="최종 점수의 간결한 근거")
    strengths: list[str] = Field(description="사진의 주요 장점 목록")
    improvements: list[str] = Field(description="다음 촬영에서 시도할 수 있는 개선점 목록")
    aesthetic_tags: AestheticTags = Field(
        default_factory=AestheticTags.empty,
        description="시각적 근거에 기반한 범주별 미학 태그",
    )

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        schema = super().model_json_schema(*args, **kwargs)
        required = list(schema.get("required", []))
        if "aesthetic_tags" not in required:
            required.append("aesthetic_tags")
        schema["required"] = required
        return schema

    @field_validator(
        "composition_score",
        "lighting_score",
        "color_score",
        "technique_score",
        "final_score",
    )
    @classmethod
    def score_must_be_between_zero_and_ten(cls, value: float) -> float:
        if not 0 <= value <= 10:
            raise ValueError("점수는 0 이상 10 이하여야 합니다.")
        return value


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
            collected[name] = _json_safe(value)
    return dict(sorted(collected.items()))


def _build_safe_upload_exif_bytes(image: Image.Image) -> bytes:
    """Build fresh EXIF bytes containing only safe photographic fields."""
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
    """Re-encode the photo with only allowlisted EXIF, never private metadata."""
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

    # Large inputs are downscaled and recompressed as JPEG to fit inline limits.
    for edge, quality in ((3072, 88), (2560, 82), (2048, 75)):
        smaller = image.copy()
        smaller.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        data = _save_as_jpeg(smaller, quality, safe_exif)
        encoded_size = 4 * ((len(data) + 2) // 3)
        if encoded_size <= MAX_BASE64_IMAGE_BYTES:
            return data, "image/jpeg"
    raise ValueError("이미지 용량이 너무 큽니다. 더 작은 JPEG/MPO/PNG/WEBP 파일을 사용해 주세요.")


def prepare_photo(image_path: str | Path) -> PreparedPhoto:
    """Read safe EXIF and keep only allowlisted fields in the upload image."""
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"사진 파일을 찾을 수 없습니다: {path}")

    with Image.open(path) as source:
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

    return PreparedPhoto(
        source_filename=path.name,
        sha256=_sha256_file(path),
        width=width,
        height=height,
        image_format=source_format,
        safe_exif=safe_exif,
        upload_bytes=upload_bytes,
        upload_mime_type=upload_mime_type,
    )


def _build_prompt(photo: PreparedPhoto) -> str:
    camera_settings = json.dumps(photo.safe_exif, ensure_ascii=False, sort_keys=True)
    if not photo.safe_exif:
        camera_settings = "{} (사용 가능한 안전한 EXIF 촬영 설정 없음)"
    tag_taxonomy = "\n".join(
        f"- {category_key} ({AESTHETIC_TAG_CATEGORIES[category_key]}): {', '.join(options)}"
        for category_key, options in AESTHETIC_TAG_OPTIONS.items()
    )
    return f"""당신은 사진 촬영을 돕는 비평가입니다. 첨부 이미지에서 확인할 수 있는 시각적 근거를 바탕으로 평가하세요.

평가 항목:
- composition: 프레이밍, 시선 유도, 균형, 여백, 주제 배치
- lighting: 빛의 방향과 질, 노출, 하이라이트/그림자 디테일
- color: 색조, 채도, 색 조화와 분위기
- technique: 초점/선명도, 흔들림, 심도, 그리고 아래 EXIF 촬영 설정의 적절성
- final_score: 사진 전체의 완성도에 대한 최종 점수

미학 태깅(aesthetic_tags):
- 아래 8개 범주별로 이미지에서 직접 확인되는 태그를 0~3개 선택하세요. 근거가 없거나 해당되지 않으면 빈 배열([])을 사용하세요.
- 허용된 태그 문구를 그대로 사용하고, 문장이나 새 태그를 임의로 만들지 마세요.
- viewpoint(시점)는 촬영 방향을 판별할 수 있을 때 정면·측면·후면·사선 등을 선택하고, 높이/시점도 함께 표현할 수 있습니다.
- pose_gaze(포즈·시선)는 인물이나 동물 등 해당 피사체가 보일 때만 적용하세요.
- narrative_implication(이야기 암시)은 보이는 단서에 한정하고 인물의 신원·관계·사건을 단정하지 마세요.
- 모든 키를 포함한 객체로 반환하세요. 키와 허용 어휘는 다음과 같습니다:
{tag_taxonomy}

모든 점수는 0.0~10.0 범위의 숫자로 작성하세요. 점수는 사진의 장르와 의도를 고려하고, 최종 점수는 네 항목을 기계적으로 평균 내지 말고 전체 인상을 반영하세요. EXIF가 없거나 불완전하면 추정하지 말고 이미지에서 확인되는 내용만 평가하세요. 답변의 텍스트 값은 한국어로 작성하세요. 강점과 개선점은 구체적이고 간결하게 적으세요.

촬영 관련 안전 EXIF (GPS, 촬영 시각, 소유자/일련번호 등은 제외됨):
{camera_settings}
"""


def analyze_with_gemini(photo: PreparedPhoto, model: str = DEFAULT_MODEL) -> PhotoAnalysis:
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    client = genai.Client(api_key=api_key)
    interaction = client.interactions.create(
        model=model,
        input=[
            {"type": "text", "text": _build_prompt(photo)},
            {
                "type": "image",
                "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
                "mime_type": photo.upload_mime_type,
            },
        ],
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": PhotoAnalysis.model_json_schema(),
        },
        # Do not persist the Interaction object server-side.
        store=False,
    )
    output_text = interaction.output_text
    if not output_text:
        raise RuntimeError("Gemini가 JSON 분석 결과를 반환하지 않았습니다.")
    return PhotoAnalysis.model_validate_json(output_text)


def ensure_tag_tables(connection: sqlite3.Connection) -> None:
    """Create the controlled tag catalog and normalized per-analysis tag table."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS photo_tag_catalog (
            category_key TEXT NOT NULL,
            category_label TEXT NOT NULL,
            tag TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            PRIMARY KEY (category_key, tag)
        )"""
    )
    catalog_rows = [
        (category_key, AESTHETIC_TAG_CATEGORIES[category_key], tag, order)
        for category_key, options in AESTHETIC_TAG_OPTIONS.items()
        for order, tag in enumerate(options)
    ]
    connection.executemany(
        "INSERT OR IGNORE INTO photo_tag_catalog "
        "(category_key, category_label, tag, sort_order) VALUES (?, ?, ?, ?)",
        catalog_rows,
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS photo_analysis_tags (
            analysis_id INTEGER NOT NULL REFERENCES photo_analyses(id) ON DELETE CASCADE,
            category_key TEXT NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (analysis_id, category_key, tag),
            FOREIGN KEY (category_key, tag)
                REFERENCES photo_tag_catalog(category_key, tag)
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_photo_analysis_tags_category_tag "
        "ON photo_analysis_tags (category_key, tag)"
    )


def sync_analysis_tags(
    connection: sqlite3.Connection,
    analysis_id: int,
    tags: AestheticTags,
) -> None:
    """Replace the normalized tag rows for one analysis."""
    connection.execute(
        "DELETE FROM photo_analysis_tags WHERE analysis_id = ?",
        (analysis_id,),
    )
    connection.executemany(
        "INSERT INTO photo_analysis_tags (analysis_id, category_key, tag) VALUES (?, ?, ?)",
        [
            (analysis_id, category_key, tag)
            for category_key, values in tags.model_dump(mode="python").items()
            for tag in values
        ],
    )


def save_analysis(
    db_path: str | Path,
    photo: PreparedPhoto,
    model: str,
    analysis: PhotoAnalysis,
) -> int:
    """Persist the privacy-filtered EXIF and validated analysis JSON in SQLite."""
    database = Path(db_path).expanduser()
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS photo_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                image_format TEXT NOT NULL,
                model TEXT NOT NULL,
                exif_json TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        ensure_tag_tables(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_photo_analyses_sha256 "
            "ON photo_analyses (sha256)"
        )
        cursor = connection.execute(
            """INSERT INTO photo_analyses (
                sha256, source_filename, width, height, image_format,
                model, exif_json, analysis_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                photo.sha256,
                photo.source_filename,
                photo.width,
                photo.height,
                photo.image_format,
                model,
                json.dumps(photo.safe_exif, ensure_ascii=False, sort_keys=True),
                analysis.model_dump_json(),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        record_id = int(cursor.lastrowid)
        sync_analysis_tags(connection, record_id, analysis.aesthetic_tags)
        return record_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="사진의 안전한 EXIF와 Gemini JSON 평가를 SQLite에 저장합니다."
    )
    parser.add_argument("image", type=Path, help="분석할 JPEG, MPO, PNG 또는 WEBP 사진")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini 모델 (기본값: {DEFAULT_MODEL})")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite DB 경로")
    parser.add_argument(
        "--html",
        "--html-report",
        dest="html_output",
        type=Path,
        metavar="PATH",
        help="분석 결과를 단독 HTML 보고서로도 저장할 경로",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report_output = args.html_output.expanduser() if args.html_output else None
        if report_output is not None:
            protected_paths = {
                args.image.expanduser().resolve(),
                args.db.expanduser().resolve(),
                ENV_FILE_PATH.resolve(),
            }
            if report_output.resolve() in protected_paths:
                raise ValueError("HTML 보고서 경로가 입력 사진, SQLite DB 또는 .env 경로와 같을 수 없습니다.")
        photo = prepare_photo(args.image)
        analysis = analyze_with_gemini(photo, model=args.model)
        record_id = save_analysis(args.db, photo, args.model, analysis)
        report_path = None
        if report_output is not None:
            report_path = save_html_report(photo, analysis, record_id, args.model, report_output)
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    # Keep stdout as a single valid JSON document for piping to other programs.
    print(analysis.model_dump_json(indent=2))
    print(f"SQLite 저장 완료 (record_id={record_id}, db={args.db})", file=sys.stderr)
    if report_path is not None:
        print(f"HTML 보고서 저장 완료: {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
