"""app.prompts.caption_prompts - Prompt builder for SNS caption and hashtags generation."""

from __future__ import annotations

from typing import Any


def build_caption_and_tags_prompt(photo: Any) -> str:
    """Build the prompt for generating SNS caption and hashtags."""
    return f"""당신은 감각적인 피규어 사진을 전문으로 공유하는 인기 인스타그램/X 인플루언서이자 소셜 미디어 에디터입니다.
제시된 피규어 사진(해상도: {photo.width} × {photo.height})을 감상하고,
피드의 참여율과 감성을 극대화할 수 있는 **인스타/X 최적화 짧은 캡션과 해시태그 목록**을 작성하세요.

[요구사항]
1. social_caption:
   - 피규어의 분위기, 조형미, 조명과 색감의 무드를 세련되고 센스 있게 담은 2~3줄 분량의 본문 문구.
   - 피드 스크롤 중 눈길을 사로잡을 수 있도록 자연스러운 이모지(✨, 📸, 🤍 등)를 적절히 곁들일 것.
   - 과도하게 유치하거나 장황하지 않고, 사진의 톤앤매너(다크, 화사함, 시네마틱 등)에 부합하는 감성적인 문체(한국어).
2. hashtags:
   - 인스타그램 및 X에서 피규어/토이 포토그래퍼 커뮤니티에 가장 효과적으로 노출되는 핵심 해시태그 8~12개.
   - 한국어(#피규어, #피규어사진, #키덜트 등), 글로벌 영어(#figurephotography, #toyphotography, #animefigure 등), 일본어(#フィギュア 등)를 균형 있게 배분할 것.
   - 각 해시태그는 반드시 '#' 기호로 시작하는 단어로 작성할 것.
"""
