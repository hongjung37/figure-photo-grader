"""SNS crop recommendations and social caption prompts.

Provides aesthetic-first crop ratios, single-ratio focus crops,
4-ratio batch recommendations, and social media captions/hashtags.
"""

from __future__ import annotations

from typing import Any


def build_sns_advice_prompt(photo: Any) -> str:
    """Build the aesthetic-first prompt for full SNS advice (crops + caption + tags)."""
    return f"""당신은 피규어 사진 및 조형 예술을 전문으로 다루는 갤러리 큐레이터이자 사진 예술 감독입니다.
제시된 피규어 사진(원본 해상도: {photo.width} × {photo.height})을 감상하고,
SNS 규격에 억지로 맞추기 전에 **사진 자체의 미적 완성도, 시선 흐름, 여백의 미가 가장 완벽하게 살아나는 최상의 구도**를 우선 판단하세요.
그 후, 소셜 미디어(Instagram, X)에서 활용할 수 있도록 주요 4대 표준 규격에 맞춘 최적 크롭 영역과 감성 캡션, 해시태그를 함께 제안하세요.

[1단계 : 순수 미학 관점의 최적 구도 판정 (best_ratio_key & best_ratio_reason)]
- best_ratio_key: 이 사진의 조형감, 피사체 크기, 배경 공간감, 시선 흐름을 고려할 때 가장 아름다운 비율 키를 1개 선택하세요.
  선택지: 'original', 'instagram_crop_4_5', 'instagram_crop_1_1', 'x_crop_16_9', 'x_crop_3_4'
  * ★중요(원형 보존 원칙): 만약 촬영 당시 원본 프레이밍과 주변 여백, 배경 조명 배치가 이미 완성도가 높아 크롭 시 피사체의 분위기나 공간감이 훼손된다면 주저 없이 'original'을 선택하세요.
  * 만약 불필요한 배경 요소를 덜어내고 피사체에 시선을 극대화했을 때 시각적 임팩트가 훨씬 뛰어난 특정 비율(수직 4:5, 정방 1:1, 시네마틱 16:9, 세로 3:4)이 있다면 해당 키를 선택하세요.
- best_ratio_reason: 왜 그 비율(또는 원본 유지)이 이 사진에 가장 아름다운지 미학적/구도적 근거를 1~2줄로 명확히 설명하세요.

[2단계 : 원본 구도 총평 (original_tip)]
- original_tip: 원본 해상도 및 원래 프레이밍 상태에서 피규어의 배치, 주변 배경의 공간감, 여백의 미, 아쉬운 점 또는 살릴 만한 특징에 대한 전문적인 큐레이터 구도 총평을 1~2줄로 작성하세요.

[3단계 : 보조 옵션 - 주요 플랫폼 규격별 최적화 크롭 영역 도출]
각 플랫폼으로 크롭해야 하는 상황을 위해 아래 4가지 비율에 맞춘 최적의 정규화 좌표(0.0~1.0)와 구도 연출 조언(composition_tip)을 작성하세요.
1. instagram_crop_4_5: 인스타그램 피드 표준 (4:5 가로:세로 비율)
   - 피규어의 안면, 눈동자 데칼, 시선 방향 여백을 최우선으로 살릴 것.
   - 머리 위나 손/소품이 애매하게 잘리지 않도록 상단 여백과 하단 컷 라인을 미학적으로 조율.
2. instagram_crop_1_1: 인스타그램 정방형 피드 (1:1 정사각형 비율)
   - 피규어 상반신 또는 핵심 조형 포인트가 중앙 또는 3분할 교차점에 오도록 집중 프레이밍.
3. x_crop_16_9: X(트위터) 가로 인라인 타임라인 미리보기 최적화 (16:9 가로 비율)
   - X 타임라인 썸네일에서 피규어 얼굴이 잘려나가지 않도록 수평 파노라마 구도 조율.
4. x_crop_3_4: X(트위터) 세로 최적화 (3:4 세로 비율)
   - 모바일 X 앱에서 풀 세로로 시원하게 보이는 비율.

[좌표 작성 규칙 및 실제 픽셀 비율 지침]
- ymin, xmin, ymax, xmax는 0.0 이상 1.0 이하의 실수값으로 작성하세요 (소수점 4자리 권장).
- 0.0 <= ymin < ymax <= 1.0, 0.0 <= xmin < xmax <= 1.0 이어야 합니다.
- ★중요(실제 픽셀 비율): 원본 해상도는 {photo.width}(가로) × {photo.height}(세로)입니다.
  정규화 좌표 기준 실제 픽셀 크기는 가로 = (xmax - xmin) * {photo.width}, 세로 = (ymax - ymin) * {photo.height} 입니다.
  단순 정규화 수치가 아닌, 실제 픽셀 비율(가로/세로)이 각 플랫폼 목표 종횡비와 최대한 일치하도록 좌표를 지정하세요.
  (예: 세로가 긴 사진에서 1:1이나 16:9로 자를 때 정규화 폭/높이를 같게 두면 세로 직사각형이 됩니다. 반드시 실제 픽셀 기준으로 목표 비율을 맞추세요.)
- ★핵심(헤드룸 보존 및 안면 중심 프레이밍): 피규어 인물 사진에서 시선 집중의 핵심은 '얼굴과 눈'입니다. 가로 비율(1:1, 16:9)로 자를 때는 정수리 위 적정 여백(헤드룸)을 남기고 하단(다리/스탠드 베이스)을 덜어내어 얼굴이 프레임 상단~중앙에 오도록 ymin을 머리 위 적정 위치로 잡으세요. 절대로 얼굴을 잘라내고 몸통만 남기지 마세요.
- composition_tip: 각 비율에서 왜 그 위치로 잘라야 피규어가 돋보이는지에 대한 친절한 1~2줄 코멘트를 작성하세요.

[소셜 캡션 및 해시태그]
- social_caption: 인스타/X에 바로 복사해 올릴 수 있는 세련된 2~3줄 캡션 (이모지 포함, 한국어).
- hashtags: 한국어/일본어/영어 피규어 특화 해시태그 8~12개 (예: #피규어, #피규어사진, #figurephotography, #toyphotography, #フィギュア 등).
"""


def build_single_crop_prompt(photo: Any, ratio_key: str, cfg: dict[str, Any]) -> str:
    """Build the prompt for re-generating a single crop ratio."""
    target_ratio = cfg["w"] / cfg["h"]
    return f"""당신은 피규어 사진 및 SNS(Instagram, X/Twitter) 비주얼 디렉터입니다.
제시된 피규어 사진(원본 해상도: {photo.width} × {photo.height})을 분석하고,
**[{cfg['name']}] ({cfg['aspect']})** 규격에 가장 이상적인 크롭 영역(정규화 좌표 0.0~1.0)과 구도 연출 조언을 JSON으로 제안하세요.

[플랫폼별 구도 최적화 지침]
- 대상 비율: {cfg['aspect']} (가로:세로 = {cfg['w']}:{cfg['h']}, 목표 픽셀 종횡비 = {target_ratio:.4f})
- 연출 가이드: {cfg['guide']}

[좌표 및 필드 작성 규칙]
- ymin, xmin, ymax, xmax는 0.0 이상 1.0 이하 실수값으로 작성하세요 (소수점 4자리 권장).
- 반드시 0.0 <= ymin < ymax <= 1.0, 0.0 <= xmin < xmax <= 1.0 을 만족해야 합니다.
- ★중요(실제 픽셀 비율): 원본 해상도는 {photo.width}(가로) × {photo.height}(세로)입니다.
  실제 픽셀 가로 = (xmax - xmin) * {photo.width}, 실제 픽셀 세로 = (ymax - ymin) * {photo.height} 입니다.
  실제 픽셀 비율 ((xmax - xmin) * {photo.width}) / ((ymax - ymin) * {photo.height}) 이 목표 종횡비 {cfg['w']}:{cfg['h']} ({target_ratio:.4f})에 최대한 근접하도록 폭과 높이를 조율하세요.
- ★핵심(헤드룸 보존 및 안면 중심 프레이밍): 피규어의 핵심 포인트는 얼굴과 상반신 조형입니다. 가로로 넓은 비율(1:1, 16:9)로 자를 때는 정수리 위 여백(헤드룸)을 자연스럽게 살리고 하단(베이스/다리)을 덜어내어 얼굴과 눈이 프레임 상단 3분할선 또는 중앙에 안정적으로 배치되도록 ymin을 조율하세요.
- ratio_label: '{cfg['name']} ({cfg['aspect']})'
- composition_tip: 이 비율에서 왜 이 위치로 잘라야 피규어가 가장 돋보이는지 미학적 의도를 친절히 1~2줄로 설명하세요.
"""


def build_all_sns_crops_prompt(photo: Any, ratio_block: str) -> str:
    """Build the aesthetic-first prompt for batch generating 4 crop ratios and curator best pick."""
    return f"""당신은 피규어 사진 및 조형 예술을 전문으로 다루는 갤러리 큐레이터이자 사진 예술 감독입니다.
제시된 피규어 사진(원본 해상도: {photo.width} × {photo.height})을 감상하고,
SNS 규격에 억지로 맞추기 전에 **사진 자체의 미적 완성도, 시선 흐름, 여백의 미가 가장 완벽하게 살아나는 최상의 구도**를 우선 판단하세요.
그 후, 소셜 미디어 활용을 위한 주요 4대 표준 규격 각각의 이상적인 크롭 영역(정규화 좌표 0.0~1.0)과 구도 연출 조언을 JSON으로 한 번에 제안하세요.

[1단계 : 순수 미학 관점의 최적 구도 판정 (best_ratio_key & best_ratio_reason)]
- best_ratio_key: 이 사진의 조형감, 피사체 크기, 배경 공간감, 시선 흐름을 고려할 때 가장 아름다운 비율 키를 1개 선택하세요.
  선택지: 'original', 'instagram_crop_4_5', 'instagram_crop_1_1', 'x_crop_16_9', 'x_crop_3_4'
  * ★중요(원형 보존 원칙): 만약 촬영 당시 원본 프레이밍과 주변 여백, 배경 조명 배치가 이미 완성도가 높아 크롭 시 피사체의 분위기나 공간감이 훼손된다면 주저 없이 'original'을 선택하세요.
  * 만약 불필요한 배경 요소를 덜어내고 피사체에 시선을 극대화했을 때 시각적 임팩트가 훨씬 뛰어난 특정 비율(수직 4:5, 정방 1:1, 시네마틱 16:9, 세로 3:4)이 있다면 해당 키를 선택하세요.
- best_ratio_reason: 왜 그 비율(또는 원본 유지)이 이 사진에 가장 아름다운지 미학적/구도적 근거를 1~2줄로 명확히 설명하세요.

[2단계 : 원본 구도 총평 (original_tip)]
- original_tip: 원본 해상도 및 원래 프레이밍 상태에서 피규어의 배치, 주변 배경의 공간감, 여백의 미, 아쉬운 점 또는 살릴 만한 특징에 대한 전문적인 큐레이터 구도 총평을 1~2줄로 작성하세요.

[3단계 : 보조 옵션 - 주요 규격별 최적화 크롭 영역 도출]
각 규격으로 크롭해야 하는 상황을 위해 아래 4가지 비율에 맞춘 최적의 정규화 좌표(0.0~1.0)와 구도 연출 조언(composition_tip)을 작성하세요.
먼저 사진 속 피규어의 핵심 포인트(얼굴, 눈동자)를 중심으로 4개 크롭 모두 일관된 시선 집중이 이루어지도록 구성하세요.
{ratio_block}

[좌표 및 필드 작성 규칙]
- ymin, xmin, ymax, xmax는 0.0 이상 1.0 이하 실수값 (소수점 4자리 권장). 0.0 <= ymin < ymax <= 1.0, 0.0 <= xmin < xmax <= 1.0.
- ★중요(실제 픽셀 비율): 실제 픽셀 가로 = (xmax - xmin) * {photo.width}, 실제 픽셀 세로 = (ymax - ymin) * {photo.height} 입니다.
  각 크롭의 (가로/세로) 픽셀 비율이 해당 목표 종횡비에 최대한 근접하도록 폭과 높이를 조율하세요.
- ★핵심(헤드룸 보존 및 안면 중심 프레이밍): 얼굴과 눈이 잘리지 않도록 정수리 위 여백(헤드룸)을 자연스럽게 살리고, 가로로 넓은 비율(1:1, 16:9)에서는 하단(베이스/다리)을 덜어내어 얼굴이 프레임 상단 3분할선 또는 중앙에 오게 하세요. 절대로 얼굴을 잘라내지 마세요.
- composition_tip: 각 비율에서 왜 그 위치로 잘라야 피규어가 돋보이는지 1~2줄로 설명하세요.
"""


def build_caption_and_tags_prompt(photo: Any) -> str:
    """Build the prompt for generating social caption and figure hashtags."""
    return f"""당신은 피규어 사진 및 서브컬처 소셜 미디어(Instagram, X/Twitter) 전문 큐레이터입니다.
제시된 피규어 사진(원본 해상도: {photo.width} × {photo.height})의 분위기, 조명, 캐릭터 표정을 분석하여
SNS에 바로 복사해 올릴 수 있는 세련된 한국어 감성 캡션과 피규어 특화 해시태그를 JSON으로 제안하세요.

[요구사항]
- social_caption: 인스타/X에 바로 복사해 올릴 수 있는 센스 있는 2~3줄 캡션 (이모지 포함, 한국어).
- hashtags: 한국어/일본어/영어 피규어 특화 해시태그 8~12개 (예: #피규어, #피규어사진, #figurephotography, #toyphotography, #フィギュア 등).
"""
