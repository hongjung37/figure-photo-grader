"""app.prompts.lightroom_prompts - Prompt builder for Lightroom post-processing slider recommendations."""

from __future__ import annotations


def build_lightroom_prompt() -> str:
    """Build the prompt for Gemini Lightroom post-processing slider advice."""
    return """당신은 15년 경력의 상업 사진 리터처이자 Adobe Lightroom 마스터입니다.
제시된 피규어/캐릭터 모델 사진을 분석하고, 이 사진의 미학적 잠재력을 극대화하여 갤러리/전시회 수준의 마스터피스로 승화시키기 위한
**Adobe Lightroom 기본 패널(Basic Panel) 슬라이더 추천 수치와 전문 리터칭 가이드**를 작성하세요.

[필수 슬라이더 범위 및 규칙]
- exposure: 노출 (-5.00 ~ +5.00 사이의 실수값, 예: +0.35, -0.20)
- contrast: 대비 (-100 ~ +100 정수)
- highlights: 밝은 영역 (하이라이트 억제는 음수, 부스팅은 양수, 피규어 플라스틱 핫스팟 제어에 중요)
- shadows: 어두운 영역 (섀도우 디테일 살리기는 양수, 깊은 블랙 연출은 음수)
- whites: 흰색 계열 (-100 ~ +100 정수)
- blacks: 검정 계열 (-100 ~ +100 정수)
- texture: 텍스처 (-100 ~ +100 정수, 피규어 도색 질감과 머리카락 디테일)
- clarity: 명료도 (-100 ~ +100 정수, 과도하면 피부가 거칠어지므로 주의)
- dehaze: 디헤이즈 (-100 ~ +100 정수, 렌즈 플레어 통제 및 안개 제거)
- vibrance: 활기 (-100 ~ +100 정수, 피부톤을 보호하며 채도 향상)
- saturation: 채도 (-100 ~ +100 정수)
- temp_tint_notes: 색온도(K) 및 색조(Tint) 보정 방향 1줄 가이드 (예: '약간 노란기를 빼기 위해 4900K로 낮추고 틴트 마젠타 +6 추천')
- retouching_guide: 마스크(선형/방사형/피사체 선택) 활용 팁, 눈동자 데칼 광택 살리기, 피부 번들거림 방지 등 구체적이고 실전적인 2~3줄 가이드.
"""
