from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from photo_tag_schema import (
    AESTHETIC_TAG_CATEGORIES,
    AESTHETIC_TAG_OPTIONS,
    FIGURE_CATEGORIES,
    FIGURE_CATEGORY_CHOICES,
    SCORE_GRADE_BENCHMARKS,
    AestheticTags,
    get_score_grade,
)

MODEL_PRESETS = {
    "lite": "gemini-3.1-flash-lite",      # 빠르고 가벼운 대량 분류/스크리닝 모드 (기본값)
    "standard": "gemini-2.5-flash",       # 균형 잡힌 표준 화질 평가 모드
    "pro": "gemini-3.1-pro-preview",              # 고화질 심층 비평 모드 (전문가급)
}
DEFAULT_TIER = "lite"
DEFAULT_MODEL = MODEL_PRESETS[DEFAULT_TIER]
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

    composition_score: float = Field(description="구도 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    composition_notes: str = Field(description="구도 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    lighting_score: float = Field(description="조명 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    lighting_notes: str = Field(description="빛의 방향/노출/명암 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    color_score: float = Field(description="색감 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    color_notes: str = Field(description="색조/채도/조화 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    technique_score: float = Field(description="촬영 기술 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    technique_notes: str = Field(description="초점/선명도/설정 적절성 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    final_score: float = Field(description="사진 전체 최종 종합 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    final_reason: str = Field(description="최종 점수 근거. 장점과 단점을 균형 있게 분석하고 해당 점수를 부여한 명확한 이유 제시")
    strengths: list[str] = Field(description="사진의 주요 장점 목록 (실제 돋보이는 핵심 강점)")
    improvements: list[str] = Field(description="사진의 단점, 아쉬운 점 및 다음 촬영을 위한 개선점 목록")
    figure_category: str = Field(
        default="일반 피규어 촬영",
        description="피규어 사진 하위 유형: '접사/디테일', '일상/야외 스냅', '스튜디오 연출/디오라마', '일반 피규어 촬영' 중 택1",
    )
    detected_camera_settings: dict[str, str] | None = Field(
        default=None,
        description="사진 하단 프레임이나 워터마크에 인쇄된 시각적 촬영 설정(카메라, 조리개, 셔터, ISO, 렌즈 등) 추출 결과. 없거나 불확실하면 null",
    )
    focus_status: str = Field(
        default="완벽 칼초점",
        description="피규어 눈동자/페이스 초점 핀 정밀 판정: '완벽 칼초점', '미세 앞핀', '미세 뒤핀', '초점 이탈', '판별 불가' 중 택1",
    )
    focus_notes: str = Field(
        default="",
        description="초점이 맞은 부위(눈동자, 의상, 배경 등) 및 심도 상태에 대한 1줄 분석 근거",
    )
    aesthetic_tags: AestheticTags = Field(
        default_factory=AestheticTags.empty,
        description="시각적 근거에 기반한 범주별 미학 태그",
    )

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        schema = super().model_json_schema(*args, **kwargs)
        tag_properties = schema.get("$defs", {}).get("AestheticTags", {}).get("properties", {})
        for category_key, allowed_tags in AESTHETIC_TAG_OPTIONS.items():
            field_schema = tag_properties.get(category_key)
            if isinstance(field_schema, dict):
                field_schema["items"] = {"type": "string", "enum": list(allowed_tags)}
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


class LightroomAdvice(BaseModel):
    """Pydantic model for on-demand Adobe Lightroom post-processing slider recommendations."""

    model_config = ConfigDict(extra="forbid")

    exposure: float = Field(description="노출 슬라이더 추천값 (-5.00 ~ +5.00, 소수점 둘째자리)")
    contrast: int = Field(description="대비 슬라이더 추천값 (-100 ~ +100)")
    highlights: int = Field(description="밝은 영역 (하이라이트) 추천값 (-100 ~ +100)")
    shadows: int = Field(description="어두운 영역 (그림자) 추천값 (-100 ~ +100)")
    whites: int = Field(description="흰색 계열 추천값 (-100 ~ +100)")
    blacks: int = Field(description="검정 계열 추천값 (-100 ~ +100)")
    texture: int = Field(description="텍스처 슬라이더 추천값 (-100 ~ +100)")
    clarity: int = Field(description="명료도 (부분 대비) 추천값 (-100 ~ +100)")
    dehaze: int = Field(description="디헤이즈 추천값 (-100 ~ +100)")
    vibrance: int = Field(description="활기 슬라이더 추천값 (-100 ~ +100)")
    saturation: int = Field(description="채도 슬라이더 추천값 (-100 ~ +100)")
    temp_tint_notes: str = Field(description="화이트밸런스/색온도/색조 가이드 (예: 5200K 유지, 틴트 +4 등)")
    retouching_guide: str = Field(description="피규어 특성에 맞춘 마스킹 및 세부 후보정 팁 (아이 데칼 캐치라이트 살리기, 피부 번들거림 방지 등)")


class CropBox(BaseModel):
    """Normalized bounding box coordinates (0.0 to 1.0) and rationale for social media cropping."""

    model_config = ConfigDict(extra="forbid")

    ymin: float = Field(description="크롭 영역 상단 Y (0.0 ~ 1.0)")
    xmin: float = Field(description="크롭 영역 좌측 X (0.0 ~ 1.0)")
    ymax: float = Field(description="크롭 영역 하단 Y (0.0 ~ 1.0)")
    xmax: float = Field(description="크롭 영역 우측 X (0.0 ~ 1.0)")
    ratio_label: str = Field(description="비율 라벨 (예: '4:5 (인스타 세로)', '1:1 (정방형)', '16:9 (X 가로)', '3:4 (X 세로)')")
    composition_tip: str = Field(description="해당 비율 크롭 시 피규어 시선/여백/프레이밍 의도 및 연출 팁")


class SNSAdvice(BaseModel):
    """Pydantic model for on-demand SNS platform crops (Instagram, X) and social captions."""

    model_config = ConfigDict(extra="forbid")

    instagram_crop_4_5: CropBox = Field(description="인스타그램 피드 표준 4:5 세로 크롭 영역 (ymin, xmin, ymax, xmax)")
    instagram_crop_1_1: CropBox = Field(description="인스타그램 1:1 정방형 크롭 영역")
    x_crop_16_9: CropBox = Field(description="X(트위터) 타임라인 최적화 16:9 가로 크롭 영역")
    x_crop_3_4: CropBox = Field(description="X(트위터) 세로 최적화 3:4 크롭 영역")
    social_caption: str = Field(description="인스타 및 X 피드용 감성적인 짧은 캡션 (2~3줄, 이모지 포함)")
    hashtags: list[str] = Field(description="피규어 특화 추천 해시태그 목록 (#피규어, #figurephotography 등 8~12개)")


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
    return bin(h1 ^ h2).count("1")


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

        thumb_img = oriented.copy()
        thumb_img.thumbnail((800, 800), Image.Resampling.LANCZOS)
        thumb_buf = BytesIO()
        if thumb_img.mode not in ("RGB", "RGBA"):
            thumb_img = thumb_img.convert("RGB")
        thumb_img.save(thumb_buf, format="WEBP", quality=82)
        thumbnail_bytes = thumb_buf.getvalue()
        dhash_val = compute_dhash_from_bytes(thumbnail_bytes)

    return PreparedPhoto(
        source_filename=path.name,
        sha256=_sha256_file(path),
        width=width,
        height=height,
        image_format=source_format,
        safe_exif=safe_exif,
        upload_bytes=upload_bytes,
        upload_mime_type=upload_mime_type,
        thumbnail_bytes=thumbnail_bytes,
        dhash=dhash_val,
    )


def _build_prompt(photo: PreparedPhoto, category_hint: str | None = None) -> str:
    camera_settings = json.dumps(photo.safe_exif, ensure_ascii=False, sort_keys=True)
    if not photo.safe_exif:
        camera_settings = "{} (사용 가능한 안전한 EXIF 촬영 설정 없음)"
    tag_taxonomy = "\n".join(
        f"- {category_key} ({AESTHETIC_TAG_CATEGORIES[category_key]}): {', '.join(options)}"
        for category_key, options in AESTHETIC_TAG_OPTIONS.items()
    )
    category_instruction = ""
    if category_hint and category_hint in FIGURE_CATEGORIES:
        cat_info = FIGURE_CATEGORIES[category_hint]
        category_instruction = f"""[지정된 피규어 촬영 유형: {cat_info['label']}]
이 사진은 사용자가 '{cat_info['label']}'({cat_info['description']}) 유형으로 지정했습니다.
figure_category 값에 반드시 '{cat_info['label']}'을 입력하고, 아래 특화 심사 기준을 최우선 잣대로 적용하세요:
- 특화 심사 포인트: {cat_info['focus']}
"""
    else:
        category_instruction = """[피규어 촬영 세부 유형 자동 판별 및 분기 심사]
먼저 사진을 분석하여 다음 4가지 피규어 촬영 유형 중 가장 부합하는 하나를 판별하여 figure_category에 정확히 입력하고, 해당 유형의 특화 기준을 엄격하게 적용하여 심사하세요:
1. '접사/디테일' (피규어 얼굴, 눈동자, 무기 등 세부 조형/도색 초근접 촬영)
   → 중점 기준: 눈동자 데칼의 초정밀 칼초점, 코/귀/머리카락 등 주요 조형이 날아가지 않는 적절한 매크로 심도(너무 얕아서 조형이 뭉개지면 감점), 미세 먼지/마감 관리, 번들거리는 반사광(핫스팟) 억제
2. '일상/야외 스냅' (자연광 야외 출사, 여행 동행, 카페 등 실제 일상 환경과 상호작용)
   → 중점 기준: 자연광(역광/측광)의 창의적 활용, 실제 환경과 피규어의 자연스러운 스케일 조화, 계절감 및 일상적 스토리텔링, 자연스러운 여백과 수평
3. '스튜디오 연출/디오라마' (배경지, 다각도 조명 세팅, 디오라마 세트, 이펙트 파츠 활용)
   → 중점 기준: 다각도 조명(키/필/림라이트)의 드라마틱한 입체감과 명암비, 디오라마와 피규어의 정교한 스케일 일치, 역동적인 포징, 클리어/이펙트 파츠 투과광
4. '일반 피규어 촬영' (피규어 본체 전신 또는 상반신을 중심으로 단정하게 담아낸 스탠다드 포토)
   → 중점 기준: 피규어 원형의 왜곡 없는 렌즈 화각과 프레이밍, 단정한 배경 분리, 자연스러운 광택 및 피부톤 밸런스
"""

    return f"""당신은 피규어 및 캐릭터 모델 사진(Figure Photography)의 완성도를 엄격하고 객관적으로 심사하는 전문 피규어 사진 비평가입니다. 첨부 이미지에서 직접 관찰되는 시각적 근거를 바탕으로 냉정하게 평가하세요.

{category_instruction}

[핵심 심사 원칙: 지나친 긍정 지양 및 엄격한 비판]
- 과도하게 칭찬하거나 호의적으로만 평가하지 마세요.
- 잘된 점뿐만 아니라 구도의 군더더기, 노출 및 빛의 아쉬움, 색감 왜곡, 기술적 한계(흔들림/초점/노이즈 등) 등 단점과 한계를 분명하고 솔직하게 지적해야 합니다.
- 각 세부 평가 메모(composition_notes, lighting_notes, color_notes, technique_notes)는 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술하세요.
  예시 형식:
  [장점] 피사체의 배치와 시선 처리가 안정적임
  [단점] 배경 요소가 산만하여 시선을 분산시키고 상단 여백이 과도하게 남음

[점수 평가 기준 (10점 만점 척도)]:
- 9.0 ~ 10.0: [프로사진작가 및 전문가급] - 상업 화보, 사진전시회 또는 전문 포트폴리오 수준의 탁월한 완성도. 빛·구도·기술의 완벽한 통제와 독창적 연출. 결함이나 아쉬움이 없는 마스터피스에만 부여.
- 8.0 ~ 8.9: [매우 우수] - 상급 사진가 및 준전문가 수준. 주제가 명확하고 완성도가 높으며 시각적 호소력이 뛰어남. 사소한 단점만 존재.
- 7.0 ~ 7.9: [우수] - 기본기가 탄탄하고 잘 찍힌 준수한 사진. 안정적인 면이 있으나, 구도 정리나 빛의 활용, 설정 등에서 분명한 단점이나 개선 여지가 공존함.
- 5.0 ~ 6.9: [보통 (일반 스냅)] - 일상적인 스냅사진 수준. 구도 불안정, 노출 과부족, 배경 분산, 초점의 아쉬움 등 일반적인 한계가 다수 보임.
- 5.0 미만: [개선 필요 (기초 미흡)] - 초점 이탈, 심각한 흔들림, 노출 실패 등 기초적인 기술적 결함이 큰 사진.

* 점수 인플레이션을 엄격히 금지합니다. 일상 스냅이나 평범한 사진은 5~6점대에 배치하고, 7점은 충분히 우수한 사진, 8점 이상은 엄격한 기준을 통과한 사진, 9점 이상은 프로 수준의 완성도를 갖춘 경우에만 부여하세요.

평가 항목:
- composition: 프레이밍, 시선 유도, 균형, 여백, 주제 배치 ([장점]과 [단점] 구분)
- lighting: 빛의 방향과 질, 노출, 하이라이트/그림자 디테일 ([장점]과 [단점] 구분)
- color: 색조, 채도, 색 조화와 분위기 ([장점]과 [단점] 구분)
- technique: 초점/선명도, 흔들림, 심도, 그리고 아래 EXIF 촬영 설정의 적절성 ([장점]과 [단점] 구분)
- focus_status: 피규어 눈동자(아이 데칼) 및 안면 조형의 초점 정밀 상태 ('완벽 칼초점', '미세 앞핀', '미세 뒤핀', '초점 이탈', '판별 불가' 중 택1)
  * 완벽 칼초점: 눈동자 데칼의 경계면과 반사광이 타협 없이 극도로 선명함
  * 미세 앞핀: 눈동자보다 앞쪽(앞머리 끝, 코끝, 무기)에 초점이 맺힘
  * 미세 뒤핀: 눈동자보다 뒤쪽(귀, 머리 뒤편, 어깨)에 초점이 맺힘
  * 초점 이탈: 피규어 얼굴 전반에 핀이 맞지 않거나 흔들림
- focus_notes: 초점이 맞은 위치와 심도 상태에 대한 1줄 직관적 판정 근거
- final_score: 위 점수 기준 척도(7: 우수, 8: 매우 우수, 9: 프로/전문가급)를 엄격히 준수한 종합 점수
- final_reason: 최종 점수의 객관적 근거 (장점과 단점을 균형 있게 종합하여 점수 이유 서술)
- strengths: 사진의 주요 장점 목록 (실제 돋보이는 핵심 강점 2~3개)
- improvements: 사진의 단점, 아쉬운 점 및 다음 촬영을 위한 개선점 목록 (2~3개)

미학 태깅(aesthetic_tags):
- 아래 8개 범주별로 이미지에서 직접 확인되는 태그를 0~3개 선택하세요. 근거가 없거나 해당되지 않으면 빈 배열([])을 사용하세요.
- 허용된 태그 문구를 그대로 사용하고, 문장이나 새 태그를 임의로 만들지 마세요.
- viewpoint(시점)는 촬영 방향을 판별할 수 있을 때 정면·측면·후면·사선 등을 선택하고, 높이/시점도 함께 표현할 수 있습니다.
- pose_gaze(포즈·시선)는 인물이나 동물 등 해당 피사체가 보일 때만 적용하세요.
- narrative_implication(이야기 암시)은 보이는 단서에 한정하고 인물의 신원·관계·사건을 단정하지 마세요.
- 모든 키를 포함한 객체로 반환하세요. 키와 허용 어휘는 다음과 같습니다:
{tag_taxonomy}

모든 점수는 0.0~10.0 범위의 숫자로 작성하세요. 최종 점수는 네 항목을 기계적으로 단순 산술평균하지 말고 전체 인상과 완성도를 위 점수 기준에 맞춰 반영하세요. EXIF가 없거나 불완전하면 추정하지 말고 이미지에서 확인되는 내용만 평가하세요. 답변의 텍스트 값은 한국어로 작성하세요.

[시각적 워터마크/하단 프레임 촬영 설정 감지 지침]
- WebP 변환 등으로 인해 파일 자체의 EXIF가 비어있더라도, 사진 하단 테두리/여백/워터마크에 카메라 모델명 및 촬영 파라미터(조리개 F값, 셔터스피드, ISO, 초점거리, 렌즈명 등)가 시각적으로 인쇄되어 있는 경우가 있습니다.
- 만약 해당 텍스트가 사진 내에 명백하게 시각적으로 존재한다면:
  1. 이를 촬영 기술(technique_notes) 평가의 객관적 근거로 참고하세요.
  2. detected_camera_settings 필드에 감지된 설정들을 키-값 객체(예: {{"Camera": "SONY A7M4", "Lens": "FE 50mm F1.2 GM", "FNumber": "F/1.4", "ExposureTime": "1/250s", "ISO": "100"}})로 추출하세요.
  3. 주의: 작가 서명, SNS 아이디, 캐릭터명, 제작사 로고 등은 제외하고 순수 광학 촬영 정보만 추출하세요.
- 만약 사진에 그러한 인쇄 텍스트가 전혀 없거나 불확실하면 절대로 지어내지 말고 detected_camera_settings를 반드시 null로 두세요.

촬영 관련 안전 EXIF (GPS, 촬영 시각, 소유자/일련번호 등은 제외됨):
{camera_settings}
"""


def analyze_with_gemini(photo: PreparedPhoto, model: str = DEFAULT_MODEL, category_hint: str | None = None) -> PhotoAnalysis:
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    client = genai.Client(api_key=api_key)
    max_retries = 5
    backoff = 3.0
    for attempt in range(1, max_retries + 1):
        try:
            interaction = client.interactions.create(
                model=model,
                input=[
                    {"type": "text", "text": _build_prompt(photo, category_hint=category_hint)},
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
        except Exception as exc:
            err_msg = str(exc)
            is_transient = any(
                code in err_msg
                for code in ("503", "429", "high demand", "ResourceExhausted", "UNAVAILABLE", "service_unavailable")
            )
            if is_transient and attempt < max_retries:
                print(f"[재시도 {attempt}/{max_retries}] API 일시적 지연/오류 발생. {backoff:.1f}초 후 재시도합니다...", file=sys.stderr)
                time.sleep(backoff)
                backoff *= 2.0
            else:
                raise


def generate_lightroom_advice(photo: PreparedPhoto, model: str = DEFAULT_MODEL) -> LightroomAdvice:
    """Generate on-demand Adobe Lightroom post-processing slider recommendations."""
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    prompt = """당신은 피규어/서브컬처 전문 사진 리터처이자 Adobe Lightroom 마스터입니다.
제시된 피규어 사진의 노출, 명암비, 하이라이트(번들거림), 암부 섀도우, 색감 및 피부 질감을 면밀히 분석하고,
Lightroom 기본 현상(Basic Tone) 슬라이더 추천 수치와 세부 리터칭 가이드를 JSON 형식으로 제시해 주세요.

[보정 슬라이더 기준]
- exposure: 노출 보정치 (EV 단위, -5.00 ~ +5.00, 보통 -1.0 ~ +1.0 사이 소수점 둘째자리)
- contrast: 대비 (-100 ~ +100)
- highlights: 밝은 영역 (-100 ~ +100, 피규어 플라스틱/도색의 과도한 하이라이트 번들거림을 억제하려면 음수 추천)
- shadows: 어두운 영역 (-100 ~ +100, 피규어 머리카락 안쪽이나 옷주름의 디테일을 살리려면 양수 추천)
- whites: 흰색 계열 (-100 ~ +100)
- blacks: 검정 계열 (-100 ~ +100)
- texture: 텍스처 (-100 ~ +100, 피부는 살짝 부드럽게 음수, 무기/의상 질감은 양수)
- clarity: 명료도 (-100 ~ +100)
- dehaze: 디헤이즈 (-100 ~ +100)
- vibrance: 활기 (-100 ~ +100)
- saturation: 채도 (-100 ~ +100)
- temp_tint_notes: 색온도(K) 및 틴트(Green/Magenta) 화이트밸런스 추천 가이드
- retouching_guide: 브러시/원형 마스크 활용법, 아이 데칼 캐치라이트 강조, 피규어 안면 번들거림 제어 등 실전 후보정 팁

출력은 반드시 지정된 JSON 스키마를 준수하고 한국어로 작성하세요."""

    client = genai.Client(api_key=api_key)
    max_retries = 5
    backoff = 3.0
    for attempt in range(1, max_retries + 1):
        try:
            interaction = client.interactions.create(
                model=model,
                input=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image",
                        "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
                        "mime_type": photo.upload_mime_type,
                    },
                ],
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": LightroomAdvice.model_json_schema(),
                },
                store=False,
            )
            output_text = interaction.output_text
            if not output_text:
                raise RuntimeError("Gemini가 Lightroom 보정 제안 JSON을 반환하지 않았습니다.")
            return LightroomAdvice.model_validate_json(output_text)
        except Exception as exc:
            err_msg = str(exc)
            is_transient = any(
                code in err_msg
                for code in ("503", "429", "high demand", "ResourceExhausted", "UNAVAILABLE", "service_unavailable")
            )
            if is_transient and attempt < max_retries:
                print(f"[재시도 {attempt}/{max_retries}] API 일시적 지연/오류 발생. {backoff:.1f}초 후 재시도합니다...", file=sys.stderr)
                time.sleep(backoff)
                backoff *= 2.0
            else:
                raise


def generate_sns_advice(photo: PreparedPhoto, model: str = DEFAULT_MODEL) -> SNSAdvice:
    """Generate on-demand SNS platform crop coordinates and social captions for Instagram & X."""
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    prompt = f"""당신은 피규어 사진 및 서브컬처 소셜 미디어(Instagram, X/Twitter) 전문 큐레이터입니다.
제시된 피규어 사진(원본 해상도: {photo.width} × {photo.height})을 분석하고,
인스타그램과 X(트위터) 업로드 시 피규어가 가장 돋보이도록 플랫폼별 크롭 영역(정규화 좌표 0.0~1.0)과 감성 캡션, 해시태그를 JSON으로 제안하세요.

[플랫폼별 크롭 비율 요구사항]
1. instagram_crop_4_5: 인스타그램 피드 표준 (4:5 가로:세로 비율)
   - 피규어의 안면, 눈동자 데칼, 시선 방향 여백을 최우선으로 살릴 것.
   - 머리 위나 손/소품이 애매하게 잘리지 않도록 상단 여백과 하단 컷 라인을 미학적으로 조율.
2. instagram_crop_1_1: 인스타그램 정방형 피드 (1:1 정사각형 비율)
   - 피규어 상반신 또는 핵심 조형 포인트가 중앙 또는 3분할 교차점에 오도록 집중 프레이밍.
3. x_crop_16_9: X(트위터) 가로 인라인 타임라인 미리보기 최적화 (16:9 가로 비율)
   - X 타임라인 썸네일에서 피규어 얼굴이 잘려나가지 않도록 수평 파노라마 구도 조율.
4. x_crop_3_4: X(트위터) 세로 최적화 (3:4 세로 비율)
   - 모바일 X 앱에서 풀 세로로 시원하게 보이는 비율.

[좌표 작성 규칙]
- ymin, xmin, ymax, xmax는 0.0 이상 1.0 이하의 실수값으로 작성하세요 (소수점 4자리 권장).
- 0.0 <= ymin < ymax <= 1.0, 0.0 <= xmin < xmax <= 1.0 이어야 합니다.
- composition_tip에는 "왜 이렇게 잘라야 피규어가 돋보이는지"에 대한 친절한 1~2줄 코멘트를 작성하세요.

[소셜 캡션 및 해시태그]
- social_caption: 인스타/X에 바로 복사해 올릴 수 있는 세련된 2~3줄 캡션 (이모지 포함, 한국어).
- hashtags: 한국어/일본어/영어 피규어 특화 해시태그 8~12개 (예: #피규어, #피규어사진, #figurephotography, #toyphotography, #フィギュア 등).
"""

    client = genai.Client(api_key=api_key)
    max_retries = 5
    backoff = 3.0
    for attempt in range(1, max_retries + 1):
        try:
            interaction = client.interactions.create(
                model=model,
                input=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image",
                        "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
                        "mime_type": photo.upload_mime_type,
                    },
                ],
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": SNSAdvice.model_json_schema(),
                },
                store=False,
            )
            output_text = interaction.output_text
            if not output_text:
                raise RuntimeError("Gemini가 SNS 크롭 및 캡션 제안 JSON을 반환하지 않았습니다.")
            return SNSAdvice.model_validate_json(output_text)
        except Exception as exc:
            err_msg = str(exc)
            is_transient = any(
                code in err_msg
                for code in ("503", "429", "high demand", "ResourceExhausted", "UNAVAILABLE", "service_unavailable")
            )
            if is_transient and attempt < max_retries:
                print(f"[재시도 {attempt}/{max_retries}] API 일시적 지연/오류 발생. {backoff:.1f}초 후 재시도합니다...", file=sys.stderr)
                time.sleep(backoff)
                backoff *= 2.0
            else:
                raise



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
    thumbnail: bytes | None = None,
) -> int:
    """Persist the privacy-filtered EXIF and validated analysis JSON in SQLite, with lightweight thumbnail."""
    database = Path(db_path).expanduser()
    database.parent.mkdir(parents=True, exist_ok=True)
    thumb_data = thumbnail if thumbnail is not None else getattr(photo, "thumbnail_bytes", None)
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
                created_at TEXT NOT NULL,
                thumbnail BLOB
            )"""
        )
        existing_cols = [r[1] for r in connection.execute("PRAGMA table_info(photo_analyses)").fetchall()]
        if "thumbnail" not in existing_cols:
            connection.execute("ALTER TABLE photo_analyses ADD COLUMN thumbnail BLOB")
        if "lr_advice_json" not in existing_cols:
            connection.execute("ALTER TABLE photo_analyses ADD COLUMN lr_advice_json TEXT")
        if "sns_advice_json" not in existing_cols:
            connection.execute("ALTER TABLE photo_analyses ADD COLUMN sns_advice_json TEXT")
        if "dhash" not in existing_cols:
            connection.execute("ALTER TABLE photo_analyses ADD COLUMN dhash INTEGER")
        ensure_tag_tables(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_photo_analyses_sha256 "
            "ON photo_analyses (sha256)"
        )
        dhash_to_save = getattr(photo, "dhash", None)
        if dhash_to_save is None and thumb_data:
            try:
                dhash_to_save = compute_dhash_from_bytes(thumb_data)
            except Exception:
                dhash_to_save = None

        cursor = connection.execute(
            """INSERT INTO photo_analyses (
                sha256, source_filename, width, height, image_format,
                model, exif_json, analysis_json, created_at, thumbnail, dhash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                thumb_data,
                dhash_to_save,
            ),
        )
        record_id = int(cursor.lastrowid)
        sync_analysis_tags(connection, record_id, analysis.aesthetic_tags)
        return record_id




def render_batch_comparison_html(
    results: list[dict[str, Any]],
    model: str,
    db_path: Path,
) -> str:
    """Render a standalone, modern HTML summary comparing all analyzed photos in a batch."""
    from html import escape
    from statistics import mean

    scores = [float(r["analysis"].final_score) for r in results] if results else [0.0]
    avg_score = mean(scores)
    max_score = max(scores)
    min_score = min(scores)

    rows_html = []
    for r in results:
        analysis: PhotoAnalysis = r["analysis"]
        grade = get_score_grade(analysis.final_score)
        report_link = f'<a href="{escape(r["relative_report"])}">개별 보고서</a>' if r.get("relative_report") else "-"
        rows_html.append(
            f"""<tr>
              <td><strong>{escape(r["filename"])}</strong></td>
              <td><span class="badge" style="background:#eef2ff;color:#4338ca;">{escape(getattr(analysis, 'figure_category', '일반'))}</span></td>
              <td><span class="badge">{escape(grade)}</span></td>
              <td><strong class="score">{analysis.final_score:.1f}</strong></td>
              <td>{analysis.composition_score:.1f}</td>
              <td>{analysis.lighting_score:.1f}</td>
              <td>{analysis.color_score:.1f}</td>
              <td>{analysis.technique_score:.1f}</td>
              <td class="reason-cell">{escape(analysis.final_reason)}</td>
              <td>{report_link}</td>
            </tr>"""
        )

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>피규어 사진 일괄 평가 결과</title>
<style>
:root {{ --ink:#17233b; --muted:#61708a; --navy:#182b49; --blue:#436cf5; --teal:#11a898; --line:#e5eaf2; --paper:#f4f7fb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font-family: "Segoe UI", "Malgun Gothic", sans-serif; line-height:1.6; }}
main {{ width:min(1240px, calc(100% - 36px)); margin:32px auto 60px; }}
.hero {{ padding:32px 36px; border-radius:24px; color:white; background:linear-gradient(125deg,#142440,#253f68 65%,#3757a3); box-shadow:0 18px 48px #20395b24; }}
.hero h1 {{ margin:0 0 8px; font-size:clamp(1.8rem, 3.5vw, 2.5rem); }}
.hero p {{ margin:4px 0; color:#e0e8f7; font-size:.95rem; }}
.stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:14px; margin-top:22px; }}
.stat-card {{ background:rgba(255,255,255,.1); backdrop-filter:blur(10px); border:1px solid rgba(255,255,255,.2); border-radius:16px; padding:16px 20px; }}
.stat-card small {{ display:block; color:#b9c9ff; font-size:.8rem; }}
.stat-card strong {{ font-size:1.9rem; color:white; }}
.section {{ margin-top:28px; }}
.table-wrap {{ overflow-x:auto; background:white; border:1px solid var(--line); border-radius:18px; box-shadow:0 8px 26px #2439570a; }}
table {{ border-collapse:collapse; width:100%; min-width:850px; font-size:.92rem; }}
th, td {{ padding:13px 15px; text-align:left; border-bottom:1px solid var(--line); vertical-align:middle; }}
th {{ background:#f8fafc; color:var(--muted); font-weight:700; font-size:.84rem; }}
tr:last-child td {{ border-bottom:none; }}
tr:hover td {{ background:#fbfdff; }}
.badge {{ display:inline-block; padding:4px 9px; border-radius:999px; background:#e6f8f5; color:#0e8477; font-size:.8rem; font-weight:700; white-space:nowrap; }}
.score {{ color:var(--blue); font-size:1.15rem; }}
.reason-cell {{ max-width:320px; color:#4a5568; font-size:.86rem; line-height:1.45; }}
a {{ color:var(--blue); text-decoration:none; font-weight:650; }}
a:hover {{ text-decoration:underline; }}
.guide {{ margin-top:20px; padding:15px 20px; border-radius:14px; background:white; border:1px solid var(--line); color:var(--muted); font-size:.85rem; }}
.guide strong {{ color:var(--ink); }}
footer {{ margin-top:30px; text-align:center; color:var(--muted); font-size:.82rem; }}
</style>
</head>
<body>
<main>
  <header class="hero">
    <h1>피규어 사진 일괄 평가 결과</h1>
    <p>Gemini 모델: {escape(model)} · 분석 완료: {len(results)}장 · SQLite DB: {escape(db_path.name)}</p>
    <div class="stats-grid">
      <div class="stat-card"><small>총 분석 장수</small><strong>{len(results)}<span style="font-size:1rem;font-weight:normal">장</span></strong></div>
      <div class="stat-card"><small>평균 점수</small><strong>{avg_score:.1f}<span style="font-size:1rem;font-weight:normal"> / 10</span></strong></div>
      <div class="stat-card"><small>최고 점수</small><strong>{max_score:.1f}<span style="font-size:1rem;font-weight:normal"> / 10</span></strong></div>
      <div class="stat-card"><small>최저 점수</small><strong>{min_score:.1f}<span style="font-size:1rem;font-weight:normal"> / 10</span></strong></div>
    </div>
  </header>

  <section class="section">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>파일명</th>
            <th>유형</th>
            <th>등급</th>
            <th>최종</th>
            <th>구도</th>
            <th>조명</th>
            <th>색감</th>
            <th>기술</th>
            <th>총평 요약</th>
            <th>상세</th>
          </tr>
        </thead>
        <tbody>
          {"".join(rows_html)}
        </tbody>
      </table>
    </div>
  </section>

  <aside class="guide">
    <strong>채점 기준 척도:</strong>
    <span><b>9.0~10</b> 프로사진작가 및 전문가급</span> ·
    <span><b>8.0~8.9</b> 매우 우수</span> ·
    <span><b>7.0~7.9</b> 우수</span> ·
    <span><b>5.0~6.9</b> 보통 (일반 스냅)</span> ·
    <span><b>5.0 미만</b> 개선 필요 (기초 미흡)</span>
  </aside>
  <footer>생성된 일괄 평가 보고서 · 피규어 사진 미학 및 기술 기준 적용</footer>
</main>
</body>
</html>"""


def run_batch_pipeline(
    photo_paths: list[Path],
    model: str,
    db_path: Path,
    report_dir: Path | None,
    summary_html_path: Path | None,
    max_workers: int = 2,
    category: str = "auto",
    generate_xmp: bool = False,
) -> int:
    """Analyze multiple photos in parallel, save results to DB, generate reports and optional XMP sidecars."""
    print(f"=== 피규어 사진 일괄 분석 시작 ===", file=sys.stderr)
    print(f"대상 사진: {len(photo_paths)}장 | 모델: {model} | 동시 워커: {max_workers}", file=sys.stderr)
    print(f"SQLite DB: {db_path}", file=sys.stderr)
    if report_dir:
        report_dir.mkdir(parents=True, exist_ok=True)
        print(f"개별 HTML 폴더: {report_dir}", file=sys.stderr)
    if generate_xmp:
        print("Lightroom / Capture One 호환 XMP 사이드카 자동 생성 활성화됨", file=sys.stderr)

    results: list[dict[str, Any]] = []

    def _process_one(photo_path: Path) -> dict[str, Any]:
        photo = prepare_photo(photo_path)
        analysis = analyze_with_gemini(photo, model=model, category_hint=category if category != "auto" else None)
        record_id = save_analysis(db_path, photo, model, analysis)
        report_path = None
        rel_report = None
        if report_dir is not None:
            clean_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", photo_path.stem).strip("._") or "photo"
            report_path = report_dir / f"{clean_stem}.html"
            save_html_report(photo, analysis, record_id, model, report_path)
            if summary_html_path is not None:
                try:
                    rel_report = os.path.relpath(report_path, summary_html_path.parent).replace("\\", "/")
                except ValueError:
                    rel_report = report_path.as_posix()
            else:
                rel_report = report_path.as_posix()

        if generate_xmp:
            from photo_xmp_manager import write_xmp_sidecar
            tags_list = [t for sub in analysis.aesthetic_tags.model_dump().values() for t in sub]
            write_xmp_sidecar(
                photo_path=photo_path,
                score=analysis.final_score,
                reason=analysis.final_reason,
                figure_category=analysis.figure_category,
                tags=tags_list,
                strengths=analysis.strengths,
                improvements=analysis.improvements,
            )

        return {
            "path": photo_path,
            "filename": photo_path.name,
            "photo": photo,
            "analysis": analysis,
            "record_id": record_id,
            "report_path": report_path,
            "relative_report": rel_report,
        }

    total = len(photo_paths)
    completed_count = 0
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        future_map = {executor.submit(_process_one, p): p for p in photo_paths}
        for future in as_completed(future_map):
            completed_count += 1
            path = future_map[future]
            try:
                res = future.result()
                results.append(res)
                analysis: PhotoAnalysis = res["analysis"]
                grade = get_score_grade(analysis.final_score)
                print(
                    f"[{completed_count:02d}/{total}] {path.name} [{analysis.figure_category}] 완료 - {analysis.final_score:.1f}점 ({grade}) [DB #{res['record_id']}]",
                    file=sys.stderr,
                )
            except Exception as exc:
                print(f"[{completed_count:02d}/{total}] {path.name} 분석 실패: {exc}", file=sys.stderr)

    # Sort results by filename
    results.sort(key=lambda r: r["filename"].casefold())

    if summary_html_path is not None and results:
        summary_html_path.parent.mkdir(parents=True, exist_ok=True)
        summary_content = render_batch_comparison_html(results, model, db_path)
        summary_html_path.write_text(summary_content, encoding="utf-8")
        print(f"일괄 비교 HTML 보고서 저장 완료: {summary_html_path}", file=sys.stderr)

    print(f"\n=== 일괄 분석 완료: 성공 {len(results)}/{total}장 ===", file=sys.stderr)
    return 0 if len(results) == total else 1



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="피규어 사진의 안전한 EXIF와 Gemini JSON 평가를 SQLite에 저장하고 보고서를 생성합니다."
    )
    parser.add_argument(
        "target",
        type=Path,
        help="분석할 사진 파일(JPEG, MPO, PNG, WEBP) 또는 사진이 포함된 폴더 경로",
    )
    parser.add_argument(
        "--category",
        "-c",
        choices=["auto", "macro", "snap", "staging", "general"],
        default="auto",
        help="피규어 촬영 세부 유형 (auto: 자동 판별, macro: 접사/디테일, snap: 일상/야외 스냅, staging: 스튜디오 연출/디오라마, general: 일반) (기본값: auto)",
    )
    parser.add_argument(
        "--tier",
        choices=list(MODEL_PRESETS.keys()),
        default=DEFAULT_TIER,
        help=f"모델 티어 프리셋 선택 (lite: Flash-Lite, standard: 2.5-Flash, pro: 2.5-Pro) (기본값: {DEFAULT_TIER})",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="사용할 Gemini 모델명 직접 지정 (지정 시 --tier보다 우선 적용)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite DB 경로 (기본값: {DEFAULT_DB_PATH.name})",
    )
    parser.add_argument(
        "--html",
        "--html-report",
        dest="html_output",
        type=Path,
        metavar="PATH",
        help="단일 사진 분석 시 단독 HTML 보고서 저장 경로",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="폴더 일괄 분석 시 동시 처리 워커 수 (기본값: 2)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="폴더 일괄 분석 시 하위 폴더까지 재귀적으로 검색",
    )
    parser.add_argument(
        "--summary-html",
        type=Path,
        default=None,
        help="폴더 일괄 분석 시 전체 비교 요약 HTML 저장 경로 (기본: <폴더>/comparison.html)",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="폴더 일괄 분석 시 개별 사진 HTML 보고서를 저장할 폴더 (기본: <폴더>/reports)",
    )
    parser.add_argument(
        "--xmp",
        action="store_true",
        help="Lightroom / Capture One 호환 XMP 사이드카 파일(*.xmp)을 원본 사진 옆에 자동 생성",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_path = args.target.expanduser().resolve()
    model = args.model if args.model else MODEL_PRESETS[args.tier]
    db_path = args.db.expanduser().resolve()

    if target_path.is_dir():
        # Batch folder mode
        extensions = {f".{fmt.lower()}" for fmt in SUPPORTED_FORMATS} | {".jpg"}
        pattern = "**/*" if args.recursive else "*"
        photo_paths = [
            p for p in sorted(target_path.glob(pattern))
            if p.is_file() and p.suffix.lower() in extensions
        ]
        if not photo_paths:
            print(f"오류: 지정된 폴더에 지원하는 사진 파일이 없습니다: {target_path}", file=sys.stderr)
            return 1

        summary_html = (
            args.summary_html.expanduser().resolve()
            if args.summary_html
            else (args.html_output.expanduser().resolve() if args.html_output else target_path / "comparison.html")
        )
        report_dir = args.report_dir.expanduser().resolve() if args.report_dir else target_path / "reports"

        return run_batch_pipeline(
            photo_paths=photo_paths,
            model=model,
            db_path=db_path,
            report_dir=report_dir,
            summary_html_path=summary_html,
            max_workers=args.workers,
            category=args.category,
            generate_xmp=args.xmp,
        )

    # Single file mode
    try:
        if not target_path.is_file():
            candidates = list(target_path.parent.glob(f"{target_path.name}.*"))
            supported_exts = {f".{fmt.lower()}" for fmt in SUPPORTED_FORMATS} | {".jpg"}
            valid_candidates = [c for c in candidates if c.suffix.lower() in supported_exts]
            if valid_candidates:
                raise FileNotFoundError(
                    f"파일을 찾을 수 없습니다: {target_path} (혹시 '{valid_candidates[0].name}' 파일을 의미하셨나요? 확장자를 포함해 주세요.)"
                )
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {target_path}")
        report_output = args.html_output.expanduser().resolve() if args.html_output else None
        if report_output is not None:
            protected_paths = {
                target_path,
                db_path,
                ENV_FILE_PATH.resolve(),
            }
            if report_output in protected_paths:
                raise ValueError("HTML 보고서 경로가 입력 사진, SQLite DB 또는 .env 경로와 같을 수 없습니다.")
        photo = prepare_photo(target_path)
        analysis = analyze_with_gemini(photo, model=model, category_hint=args.category if args.category != "auto" else None)
        record_id = save_analysis(db_path, photo, model, analysis)
        report_path = None
        if report_output is not None:
            report_path = save_html_report(photo, analysis, record_id, model, report_output)

        if args.xmp:
            from photo_xmp_manager import write_xmp_sidecar
            tags_list = [t for sub in analysis.aesthetic_tags.model_dump().values() for t in sub]
            xmp_out = write_xmp_sidecar(
                photo_path=target_path,
                score=analysis.final_score,
                reason=analysis.final_reason,
                figure_category=analysis.figure_category,
                tags=tags_list,
                strengths=analysis.strengths,
                improvements=analysis.improvements,
            )
            print(f"XMP 사이드카 저장 완료: {xmp_out}", file=sys.stderr)
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    # Keep stdout as a single valid JSON document for piping to other programs.
    print(analysis.model_dump_json(indent=2))
    print(f"SQLite 저장 완료 (record_id={record_id}, db={db_path})", file=sys.stderr)
    if report_path is not None:
        print(f"HTML 보고서 저장 완료: {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
