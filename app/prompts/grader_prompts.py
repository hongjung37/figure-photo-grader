"""app.prompts.grader_prompts - Figure photography grading prompt builder.

Provides the comprehensive aesthetic evaluation prompt, including figure category
specialized criteria, strict scoring benchmarks, pros/cons segregation, and aesthetic tagging.
"""

from __future__ import annotations

import json
from typing import Any

from app.models.analysis import (
    AESTHETIC_TAG_CATEGORIES,
    AESTHETIC_TAG_OPTIONS,
    FIGURE_CATEGORIES,
)


def build_grader_prompt(
    photo: Any,
    category_hint: str | None = None,
    compact_tags: bool = False,
) -> str:
    """Build the prompt for figure photo evaluation."""
    safe_exif = getattr(photo, "safe_exif", {})
    camera_settings = json.dumps(safe_exif, ensure_ascii=False, sort_keys=True)
    if not safe_exif:
        camera_settings = "{} (사용 가능한 안전한 EXIF 촬영 설정 없음)"

    if compact_tags:
        tag_section = (
            "viewpoint(시점), composition_space(구도·공간), pose_gaze(포즈·시선), mood(분위기), "
            "subject_background(피사체-배경), light_expression(빛 표현), color_impression(색조 인상), "
            "narrative_implication(이야기 암시)의 8개 범주에 대해, "
            "응답 JSON 스키마(aesthetic_tags)에 정의된 허용 어휘 목록 중에서 적합한 태그를 0~3개(필수 항목은 1~3개) 정확히 선택하세요."
        )
    else:
        tag_section = "키와 허용 어휘는 다음과 같습니다:\n" + "\n".join(
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
- 아래 8개 범주별로 이미지에서 직접 확인되는 태그를 0~3개 선택하세요.
- ★미학적 분위기/온도감 필수 판별 규칙:
  1) mood(분위기): 사진의 정서적 무드와 온도감을 면밀히 분석하여 '차가움', '따뜻함', '청량함', '화사함', '몽환적', '다크·누아르', '시네마틱' 등에서 반드시 1~3개를 필수로 선택하세요 (빈 배열 금지).
  2) color_impression(색조 인상): 피규어 조명과 피부톤의 색온도를 판별하여 '따뜻한 톤', '차가운 톤', '쿨톤(차가움)', '웜톤(따뜻함)', '파스텔', '비비드 컬러' 등에서 반드시 1~3개를 필수로 선택하세요 (빈 배열 금지).
  3) light_expression(빛 표현): '자연광', '스튜디오 조명', '확산광', '역광', '부드러운 그림자', '강한 명암' 등에서 반드시 1~3개를 필수로 선택하세요.
- 허용된 태그 문구를 그대로 사용하고, 문장이나 새 태그를 임의로 만들지 마세요.
- viewpoint(시점)는 촬영 방향을 판별할 수 있을 때 정면·측면·후면·사선 등을 선택하고, 높이/시점도 함께 표현할 수 있습니다.
- pose_gaze(포즈·시선)는 인물이나 동물 등 해당 피사체가 보일 때만 적용하세요.
- narrative_implication(이야기 암시)은 보이는 단서에 한정하고 인물의 신원·관계·사건을 단정하지 마세요.
- 모든 키를 포함한 객체로 반환하세요.
{tag_section}

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


def build_cross_check_prompt(
    photo: Any,
    category_hint: str | None = None,
) -> str:
    """Build lightweight figure photo critique prompt for OpenAI cross-check second opinion (no aesthetic tags)."""
    safe_exif = getattr(photo, "safe_exif", {})
    camera_settings = json.dumps(safe_exif, ensure_ascii=False, sort_keys=True)
    if not safe_exif:
        camera_settings = "{} (사용 가능한 안전한 EXIF 촬영 설정 없음)"

    if category_hint and category_hint in FIGURE_CATEGORIES:
        cat = FIGURE_CATEGORIES[category_hint]
        category_info = f"[지정된 촬영 유형: {cat['label']}]\n- 특화 심사 중점: {cat['focus']}"
    else:
        category_info = """[피규어 촬영 세부 유형 및 특화 심사 기준]
사진의 구도와 연출 의도를 고려하여 아래 유형에 부합하도록 평가하세요:
- '접사/디테일': 안면·눈동자 데칼의 초정밀 칼초점, 적절한 매크로 심도, 마감 관리
- '일상/야외 스냅': 자연광(역광/측광)의 창의적 활용, 환경과 피규어의 스케일 조화, 일상적 분위기
- '스튜디오 연출/디오라마': 드라마틱한 조명 명암비와 입체감, 역동적 포징, 디오라마 일체감
- '일반 피규어 촬영': 왜곡 없는 안정적 프레이밍, 단정한 배경 분리, 자연스러운 피부톤"""

    return f"""당신은 피규어 사진(Figure Photography)의 완성도를 전문적이고 균형 있게 심사하는 전문 피규어 사진 비평가입니다.
제공된 사진을 시각적으로 면밀히 관찰하고 피규어 사진으로서의 완성도를 심사하여 독립적인 2차 평가 의견(Second Opinion / Cross-Check)을 제시하세요.

{category_info}

[핵심 심사 원칙: 전문 포토그래퍼의 균형 잡힌 시각]
- 사진의 완성도와 미학적 장점을 충분히 인정하되, 부족한 점이나 개선이 필요한 점은 솔직하게 표현하고, 더 나은 결과물을 위한 구체적 팁을 제안하는 프로 포토그래퍼의 시각으로 심사하세요.
- 과도하게 트집을 잡거나 사소한 아쉬움으로 전체 퀄리티를 깎아내리지 마세요. 퀄리티가 높은 사진에는 그에 합당한 높은 점수를 명확히 부여해야 합니다.
- composition_critique와 lighting_critique는 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술하세요.
- strengths에는 사진에서 실제로 돋보이는 긍정적 강점(표정, 핀, 조명, 색감 등) 2~3개를 구체적으로 짚어주세요.
- improvements에는 비난이 아닌, 다음 촬영 시 사진의 완성도를 한 단계 끌어올릴 수 있는 실질적인 개선 조언 2~3개를 제시하세요.

[점수 평가 척도 및 변별력 기준 (10점 만점)]:
- 9.0 ~ 10.0: [프로사진작가 및 전문가급] - 상업 화보 수준의 탁월한 완성도. 빛·구도·기술의 완벽한 통제와 독창적 연출. 결함이 거의 없는 마스터피스.
- 8.0 ~ 8.9: [매우 우수] - 상급 사진가 수준. 초점·구도·조명이 탄탄하고 피규어의 매력이 뚜렷하게 살아있음. 높은 완성도에 걸맞은 점수를 부여하세요.
- 7.0 ~ 7.9: [우수 / 준수] - 기본기가 잘 갖추어진 준수한 사진. 안정적이나 조명 각도, 배경 정리, 앵글 등에서 개선 여지가 공존함.
- 5.0 ~ 6.9: [보통 (일반 스냅)] - 일상적인 스냅사진 수준. 구도 불안정, 평면적 조명, 배경 산만, 핀의 아쉬움 등 명확한 한계가 존재함.
- 5.0 미만: [기초 미흡] - 초점 이탈, 심각한 흔들림, 노출 실패 등 기초적인 기술적 결함.

* 중요한 주의사항 (변별력 확보):
- 사소한 아쉬움 하나로 전체 완성도를 과도하게 깎아내리지 마세요. 퀄리티가 우수한 사진은 그에 걸맞은 높은 점수를 부여하여, 보통 스냅사진과의 변별력을 명확히 구분해야 합니다.
- 태그 분류는 필요하지 않으며, 순수 시각적 비평과 촬영자를 위한 건설적 조언에 집중하세요.
- 한국어로 작성하세요.

촬영 관련 안전 EXIF:
{camera_settings}
"""


_build_prompt = build_grader_prompt

__all__ = ["build_grader_prompt", "_build_prompt", "build_cross_check_prompt"]
