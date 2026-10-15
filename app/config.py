"""app.config - Application configuration, model presets, and global constants."""

from __future__ import annotations

import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
LEGACY_DB_PATH = PROJECT_ROOT / "photo_analysis.sqlite3"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "photo_analysis.sqlite3" if DEFAULT_DATA_DIR.exists() or not LEGACY_DB_PATH.exists() else LEGACY_DB_PATH
ORIGINALS_DIR = DEFAULT_DATA_DIR / "photo_originals" if DEFAULT_DATA_DIR.exists() else PROJECT_ROOT / "photo_originals"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"
ENV_FILE_PATH = PROJECT_ROOT / ".env"

PORT = 8080
HOST = "127.0.0.1"

# Gemini Models
MODEL_PRESETS: dict[str, str] = {
    "lite": "gemini-3.1-flash-lite",      # 빠르고 가벼운 대량 분류/스크리닝 모드 (과부하시 자동 폴백)
    "standard": "gemini-3.5-flash-lite",   # 균형 잡힌 표준 화질 평가 모드
    "pro": "gemini-3.8-flash",            # 고화질 심층 비평 모드 (서버 과부하시 자동 폴백)
}
DEFAULT_TIER = "lite"
DEFAULT_MODEL = MODEL_PRESETS[DEFAULT_TIER]
FALLBACK_MODEL = "gemini-3.5-flash-lite"

ORIGINALS_DIR_NAME = "photo_originals"
SUPPORTED_FORMATS = {
    "JPEG": "image/jpeg",
    "MPO": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
MAX_IMAGE_EDGE = 4096
MAX_UPLOAD_SIZE = 50 * 1024 * 1024
MAX_BASE64_IMAGE_BYTES = 18 * 1024 * 1024
EXIF_IFD_ID = 34665

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
EXIF_DATETIME_ORIGINAL_ID = 0x9003
EXIF_OFFSET_TIME_ORIGINAL_ID = 0x9011
EXIF_OFFSET_TIME_ID = 0x9010

# SNS Crop Configurations
SNS_CROP_RATIO_CONFIGS = {
    "instagram_crop_4_5": {
        "name": "인스타그램 4:5 피드세로",
        "aspect": "4:5 (세로)",
        "w": 4,
        "h": 5,
        "guide": (
            "인스타그램 모바일 피드 최적화: 스마트폰 화면을 최대로 점유하는 가장 강력한 세로 구도. "
            "피규어의 얼굴과 상체가 상단 1/3 지점에 오도록 하고 불필요한 바닥 여백을 잘라내어 시선을 집중시킬 것."
        ),
    },
    "instagram_crop_1_1": {
        "name": "인스타그램 1:1 정방형",
        "aspect": "1:1 (정사각형)",
        "w": 1,
        "h": 1,
        "guide": (
            "인스타그램 1:1 정방형 피드 최적화: 피규어의 상반신 또는 핵심 조형 포인트가 중앙 또는 3분할 교차점에 오도록 집중 프레이밍할 것. "
            "불필요한 주변 빈 공간을 과감히 덜어내고 피규어 본체와 실루엣에 시선이 즉각 꽂히는 밀도 높은 정사각형 구도를 잡을 것."
        ),
    },
    "x_crop_16_9": {
        "name": "X(트위터) 16:9 가로타임라인",
        "aspect": "16:9 (와이드 가로)",
        "w": 16,
        "h": 9,
        "guide": (
            "X(트위터) 가로 타임라인 미리보기(16:9) 최적화: 모바일 및 PC X 타임라인 썸네일에서 피규어의 얼굴과 상체가 잘려나가지 않아야 함. "
            "피규어의 시선 방향이나 동세를 고려해 좌우 여백을 시네마틱하게 배치하여 피드 스크롤 중 한눈에 들어오는 가로 파노라마 구도를 조율할 것."
        ),
    },
    "x_crop_3_4": {
        "name": "X(트위터) 3:4 모바일세로",
        "aspect": "3:4 (모바일 세로)",
        "w": 3,
        "h": 4,
        "guide": (
            "X(트위터) 모바일 세로 풀뷰(3:4) 최적화: 스마트폰 X 앱에서 시원하게 꽉 찬 세로 화면으로 입체감이 돋보이게 할 것. "
            "피규어의 전신 또는 3/4 샷을 안정적으로 담을 수 있도록 위아래 균형을 맞춘 시원한 세로 프레임을 구성할 것."
        ),
    },
}
