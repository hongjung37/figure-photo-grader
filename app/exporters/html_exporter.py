from __future__ import annotations

import base64
import os
import tempfile
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

from app.models.analysis import AESTHETIC_TAG_CATEGORIES, get_score_grade

if TYPE_CHECKING:
    from app.models.analysis import PhotoAnalysis
    from app.services.image_processor import PreparedPhoto

CATEGORY_SCORES = (
    ("구도", "composition_score", "composition_notes"),
    ("조명", "lighting_score", "lighting_notes"),
    ("색감", "color_score", "color_notes"),
    ("촬영 기술", "technique_score", "technique_notes"),
)


def _score_card(title: str, score: float, notes: str) -> str:
    value = float(score)
    grade = get_score_grade(value)
    return f"""<article class="score-card">
      <div class="score-heading"><h3>{escape(title)}</h3><div><span class="sub-grade">{escape(grade)}</span> <strong>{value:.1f}<small> / 10</small></strong></div></div>
      <div class="track" role="meter" aria-label="{escape(title)} 점수 ({escape(grade)})" aria-valuemin="0" aria-valuemax="10" aria-valuenow="{value:.1f}"><span style="width:{value * 10:.1f}%"></span></div>
      <p>{escape(notes)}</p>
    </article>"""


def _render_cross_check_section(cross_check: Any) -> str:
    if cross_check is None:
        return ""
    cc_data = (
        cross_check.model_dump(mode="python")
        if hasattr(cross_check, "model_dump")
        else (cross_check if isinstance(cross_check, dict) else {})
    )
    if not cc_data:
        return ""

    cc_model = escape(str(cc_data.get("model") or "GPT-6 Luna"))
    raw_score = cc_data.get("score")
    if raw_score is not None:
        cc_score = float(raw_score)
        score_str = f"{cc_score:.1f}"
        score_grade = escape(get_score_grade(cc_score))
        grade_badge = f'<span class="cross-check-grade-pill">{score_grade}</span>'
    else:
        score_str = "-"
        grade_badge = ""

    cc_reason = escape(str(cc_data.get("reason") or ""))
    cc_comp = escape(str(cc_data.get("composition_critique") or ""))
    cc_light = escape(str(cc_data.get("lighting_critique") or ""))

    strengths = cc_data.get("strengths") or []
    improvements = cc_data.get("improvements") or []

    def render_list_items(items: list[Any]) -> str:
        if not items:
            return '<li class="empty">기록된 항목이 없습니다.</li>'
        return "".join(f"<li>{escape(str(item))}</li>" for item in items)

    reason_html = (
        f'<div class="cross-check-reason-box"><strong>OpenAI 총평:</strong> <p>{cc_reason}</p></div>'
        if cc_reason
        else ""
    )

    critique_html = ""
    if cc_comp or cc_light:
        comp_card = (
            f'<div class="cross-check-comp-box"><b class="cross-check-sub-title">📐 구도 비평</b><p>{cc_comp}</p></div>'
            if cc_comp
            else ""
        )
        light_card = (
            f'<div class="cross-check-light-box"><b class="cross-check-sub-title">💡 조명 비평</b><p>{cc_light}</p></div>'
            if cc_light
            else ""
        )
        critique_html = f'<div class="cross-check-grid-2">{comp_card}{light_card}</div>'

    list_html = ""
    if strengths or improvements:
        s_card = (
            f'<div class="cross-check-strengths-box"><b class="cross-check-sub-title">✓ OpenAI 시각 강점</b><ul>{render_list_items(strengths)}</ul></div>'
            if strengths
            else ""
        )
        i_card = (
            f'<div class="cross-check-improvements-box"><b class="cross-check-sub-title">✗ OpenAI 조언/개선점</b><ul>{render_list_items(improvements)}</ul></div>'
            if improvements
            else ""
        )
        margin_style = ' style="margin-top:12px;"' if (cc_comp or cc_light) else ""
        list_html = f'<div class="cross-check-grid-2"{margin_style}>{s_card}{i_card}</div>'

    return f"""
  <section class="section" aria-label="OpenAI 크로스 체크 의견">
    <div class="panel cross-check-opinion-card">
      <div class="cross-check-header">
        <div class="cross-check-title-group">
          <span class="cross-check-icon">🤝</span>
          <div>
            <h2 class="cross-check-title">OpenAI 크로스 체크 의견 <small>교차 검증 소견 ({cc_model})</small></h2>
            <p class="cross-check-subtitle">Gemini 본 평가와 별도로 제공되는 독립적인 보조 비평입니다. (점수 합산/평균 없음)</p>
          </div>
        </div>
        <div class="cross-check-score-group">
          {grade_badge}
          <div class="cross-check-score-val"><strong>{score_str}</strong><small> / 10</small></div>
        </div>
      </div>
      {reason_html}
      {critique_html}
      {list_html}
    </div>
  </section>"""



def render_html_report(
    photo: PreparedPhoto,
    analysis: PhotoAnalysis,
    record_id: int,
    model: str,
) -> str:
    """Render a portable, self-contained HTML report from validated analysis data."""
    image_data = base64.b64encode(photo.upload_bytes).decode("ascii")
    image_source = f"data:{escape(photo.upload_mime_type, quote=True)};base64,{image_data}"
    analysis_data = analysis.model_dump(mode="python")
    category_cards = "\n".join(
        _score_card(title, analysis_data[score_field], analysis_data[notes_field])
        for title, score_field, notes_field in CATEGORY_SCORES
    )
    aesthetic_tags = analysis_data["aesthetic_tags"]
    has_aesthetic_tags = any(aesthetic_tags.get(key) for key in AESTHETIC_TAG_CATEGORIES)
    tag_cards = "\n".join(
        f'<article class="tag-card"><h3>{escape(category_label)}</h3>'
        + (
            "<div class=\"tag-list\">"
            + "".join(f'<span class="tag-pill">{escape(tag)}</span>' for tag in aesthetic_tags.get(category_key, []))
            + "</div>"
            if aesthetic_tags.get(category_key)
            else '<p class="empty-tag">관찰된 태그 없음</p>'
        )
        + "</article>"
        for category_key, category_label in AESTHETIC_TAG_CATEGORIES.items()
    )

    def render_list(items: list[str]) -> str:
        if not items:
            return "<li class=\"empty\">기록된 항목이 없습니다.</li>"
        return "".join(f"<li>{escape(item)}</li>" for item in items)

    filename = escape(photo.source_filename)
    final_score = float(analysis.final_score)
    final_grade = escape(get_score_grade(final_score))
    category_label = escape(getattr(analysis, "figure_category", "일반 피규어 촬영"))
    focus_status = escape(getattr(analysis, "focus_status", "완벽 칼초점"))
    focus_notes = escape(getattr(analysis, "focus_notes", ""))

    watermark_badge = ""
    detected_settings = getattr(analysis, "detected_camera_settings", None)
    if detected_settings and isinstance(detected_settings, dict):
        sp_text = " · ".join(f"{v}" for v in detected_settings.values() if v)
        if sp_text:
            watermark_badge = f'<div style="margin-top:8px;font-size:0.82rem;color:#4338ca;background:#eef2ff;padding:4px 10px;border-radius:6px;display:inline-block"><b>🔍 사진 내 워터마크 감지:</b> {escape(sp_text)}</div>'
    if focus_notes:
        watermark_badge += f'<div style="margin-top:6px;font-size:0.82rem;color:#0369a1;background:#f0f9ff;padding:4px 10px;border-radius:6px;display:inline-block"><b>🎯 초점 정밀 분석:</b> {focus_notes}</div>'

    cross_check = getattr(analysis, "cross_check_opinion", None)
    cross_check_section = _render_cross_check_section(cross_check)
    topline_desc = "Gemini + OpenAI 앙상블 분석" if cross_check else "Gemini 사진 분석"
    ensemble_badge = (
        '<span style="background:#0284c7;border-color:#0284c7;font-weight:700;">🤝 앙상블 크로스체크</span>'
        if cross_check
        else ""
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>사진 분석 결과 — {filename}</title>
<style>
:root {{ color-scheme: light; --ink:#17233b; --muted:#61708a; --navy:#182b49; --blue:#436cf5; --teal:#11a898; --line:#e5eaf2; --paper:#f4f7fb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font-family: "Segoe UI", "Malgun Gothic", sans-serif; line-height:1.6; }}
.page {{ width:min(1120px, calc(100% - 36px)); margin:34px auto 60px; }}
.topline {{ display:flex; justify-content:space-between; gap:16px; align-items:center; color:var(--muted); font-size:.9rem; margin-bottom:16px; }}
.brand {{ color:var(--blue); font-weight:800; letter-spacing:.11em; text-transform:uppercase; }}
.hero {{ display:grid; grid-template-columns:minmax(0,1fr) 220px; gap:30px; align-items:center; padding:38px; border-radius:26px; color:white; background:linear-gradient(125deg,#142440,#253f68 65%,#3757a3); box-shadow:0 18px 48px #20395b24; }}
.eyebrow {{ margin:0 0 8px; color:#b9c9ff; font-size:.82rem; font-weight:700; letter-spacing:.12em; }}
h1 {{ margin:0; font-size:clamp(1.8rem,4vw,2.8rem); line-height:1.2; }}
.filename {{ margin:12px 0 0; color:#e0e8f7; overflow-wrap:anywhere; }}
.meta {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:20px; }}
.meta span {{ padding:6px 11px; border:1px solid #ffffff38; border-radius:999px; color:#e0e8f7; font-size:.82rem; }}
.final-score {{ display:grid; place-items:center; width:184px; height:184px; margin:auto; border-radius:50%; background:conic-gradient(#71e0c8 {final_score * 10:.1f}%,#ffffff26 0); position:relative; }}
.final-score::before {{ content:""; position:absolute; inset:10px; border-radius:50%; background:#20385f; }}
.final-score div {{ position:relative; text-align:center; }}
.final-score strong {{ display:block; font-size:3.4rem; line-height:1.1; }}
.final-score span {{ display:block; color:#cfdbef; font-size:.88rem; }}
.grade-pill {{ display:inline-block; margin-top:6px; padding:3px 10px; border-radius:999px; background:#11a898; color:white; font-size:.78rem; font-weight:700; letter-spacing:.02em; }}
.sub-grade {{ font-size:.8rem; font-weight:600; color:var(--teal); margin-right:4px; vertical-align:middle; }}
.grade-guide {{ margin-top:20px; padding:14px 18px; border-radius:14px; background:white; border:1px solid var(--line); color:var(--muted); font-size:.84rem; display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
.grade-guide strong {{ color:var(--ink); }}
.grade-guide b {{ color:var(--navy); }}
.section {{ margin-top:28px; }}
.section-title {{ display:flex; justify-content:space-between; align-items:end; gap:14px; margin:0 0 14px; }}
.section-title h2 {{ margin:0; font-size:1.35rem; }}
.section-title p {{ margin:0; color:var(--muted); font-size:.9rem; }}
.content-grid {{ display:grid; grid-template-columns:1.05fr .95fr; gap:22px; align-items:start; }}
.panel {{ background:white; border:1px solid var(--line); border-radius:20px; box-shadow:0 8px 26px #2439570a; overflow:hidden; }}
.photo-panel {{ padding:12px; }}
.photo-panel img {{ display:block; width:100%; max-height:520px; object-fit:contain; background:#edf1f7; border-radius:13px; }}
.photo-caption {{ padding:10px 6px 2px; color:var(--muted); font-size:.82rem; }}
.score-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
.score-card {{ padding:19px; background:white; border:1px solid var(--line); border-radius:18px; box-shadow:0 8px 26px #2439570a; min-width:0; }}
.score-heading {{ display:flex; justify-content:space-between; align-items:center; gap:8px; }}
.score-heading h3 {{ margin:0; font-size:1.02rem; }}
.score-heading strong {{ white-space:nowrap; color:var(--blue); font-size:1.45rem; }}
.score-heading small {{ color:var(--muted); font-size:.76rem; font-weight:500; }}
.track {{ height:8px; margin:13px 0 12px; border-radius:9px; background:#edf1f7; overflow:hidden; }}
.track span {{ display:block; height:100%; border-radius:9px; background:linear-gradient(90deg,#526df6,#39b5a4); }}
.score-card p {{ margin:0; color:#46556e; font-size:.92rem; white-space:pre-wrap; overflow-wrap:anywhere; }}
.reason {{ padding:23px 25px; border-left:4px solid var(--teal); }}
.reason p {{ margin:8px 0 0; color:#40506a; white-space:pre-wrap; }}
.list-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
.list-card {{ padding:22px 24px; }}
.list-card h3 {{ margin:0 0 10px; font-size:1.02rem; }}
.list-card ul {{ margin:0; padding-left:20px; color:#46556e; }}
.list-card li {{ padding:4px 0; }}
.list-card .empty {{ color:var(--muted); }}
.tag-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
.tag-card {{ min-width:0; padding:17px; background:white; border:1px solid var(--line); border-radius:16px; }}
.tag-card h3 {{ margin:0 0 11px; font-size:.95rem; }}
.tag-list {{ display:flex; flex-wrap:wrap; gap:7px; }}
.tag-pill {{ display:inline-flex; align-items:center; padding:5px 10px; border-radius:999px; background:#eef2ff; color:#304bb8; font-size:.84rem; font-weight:650; }}
.empty-tag {{ margin:0; color:var(--muted); font-size:.86rem; }}
.empty-tags {{ margin-bottom:12px; padding:13px 16px; border-radius:12px; background:#f0f4fa; color:#53627a; font-size:.9rem; }}
.cross-check-opinion-card {{ padding:24px 28px; background:#f8fbff; border:1px solid #bae6fd; border-left:5px solid #0284c7; border-radius:20px; box-shadow:0 8px 26px #2439570a; }}
.cross-check-header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:16px; flex-wrap:wrap; }}
.cross-check-title-group {{ display:flex; align-items:center; gap:12px; }}
.cross-check-icon {{ font-size:1.8rem; line-height:1; }}
.cross-check-title {{ margin:0; font-size:1.25rem; color:var(--navy); display:flex; align-items:baseline; gap:8px; }}
.cross-check-title small {{ font-size:0.88rem; color:#0284c7; font-weight:700; }}
.cross-check-subtitle {{ margin:3px 0 0; color:var(--muted); font-size:0.82rem; }}
.cross-check-score-group {{ display:flex; align-items:center; gap:10px; }}
.cross-check-grade-pill {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#0284c7; color:white; font-size:0.8rem; font-weight:700; }}
.cross-check-score-val strong {{ font-size:1.8rem; color:#0284c7; line-height:1; }}
.cross-check-score-val small {{ color:var(--muted); font-size:0.85rem; font-weight:500; }}
.cross-check-reason-box {{ background:white; border:1px solid #e2e8f0; border-radius:12px; padding:14px 18px; margin-bottom:14px; font-size:0.92rem; color:#334155; line-height:1.6; }}
.cross-check-reason-box strong {{ color:var(--navy); display:block; margin-bottom:4px; font-size:0.95rem; }}
.cross-check-reason-box p {{ margin:0; white-space:pre-wrap; overflow-wrap:anywhere; }}
.cross-check-grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
.cross-check-comp-box {{ background:#f0f9ff; border:1px solid #e0f2fe; border-radius:12px; padding:14px 16px; color:#0369a1; }}
.cross-check-light-box {{ background:#fffbeb; border:1px solid #fef3c7; border-radius:12px; padding:14px 16px; color:#b45309; }}
.cross-check-sub-title {{ display:block; margin-bottom:6px; font-size:0.92rem; font-weight:700; }}
.cross-check-comp-box p, .cross-check-light-box p {{ margin:0; font-size:0.88rem; line-height:1.55; white-space:pre-wrap; color:#334155; }}
.cross-check-strengths-box {{ background:#f0fdf4; border:1px solid #dcfce7; border-radius:12px; padding:14px 16px; color:#166534; }}
.cross-check-improvements-box {{ background:#fef2f2; border:1px solid #fee2e2; border-radius:12px; padding:14px 16px; color:#991b1b; }}
.cross-check-strengths-box ul, .cross-check-improvements-box ul {{ margin:0; padding-left:20px; font-size:0.88rem; color:#334155; }}
.cross-check-strengths-box li, .cross-check-improvements-box li {{ padding:3px 0; }}
footer {{ margin-top:24px; color:var(--muted); font-size:.8rem; text-align:center; }}
@media (max-width:900px) {{ .tag-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
@media (max-width:760px) {{ .page {{ width:min(100% - 22px, 600px); margin:16px auto 36px; }} .hero {{ grid-template-columns:1fr; padding:25px; }} .final-score {{ width:148px; height:148px; }} .final-score strong {{ font-size:2.8rem; }} .content-grid,.list-grid {{ grid-template-columns:1fr; }} .score-grid {{ grid-template-columns:1fr; }} .tag-grid {{ grid-template-columns:1fr; }} .topline {{ align-items:flex-start; flex-direction:column; }} .cross-check-grid-2 {{ grid-template-columns:1fr; }} .cross-check-header {{ flex-direction:column; align-items:flex-start; }} }}
@media print {{ body {{ background:white; }} .page {{ width:100%; margin:0; }} .hero,.panel,.score-card,.cross-check-opinion-card {{ box-shadow:none; }} .hero {{ break-inside:avoid; }} }}
</style>
</head>
<body>
<main class="page">
  <div class="topline"><span class="brand">PHOTO REVIEW</span><span>{topline_desc} · 레코드 #{record_id}</span></div>
  <header class="hero">
    <div>
      <p class="eyebrow">PHOTO ANALYSIS REPORT</p>
      <h1>사진 분석 결과</h1>
      <p class="filename">{filename}</p>
      <div class="meta"><span style="background:#11a898;border-color:#11a898;font-weight:700;">{category_label}</span><span style="background:#4f46e5;border-color:#4f46e5;font-weight:700;">🎯 {focus_status}</span>{ensemble_badge}<span>{photo.width} × {photo.height}px</span><span>{escape(photo.image_format)}</span><span>{escape(model)}</span></div>
    </div>
    <div class="final-score" role="img" aria-label="최종 점수 {final_score:.1f}점 ({final_grade})">
      <div><strong>{final_score:.1f}</strong><span>최종 점수 / 10</span><div class="grade-pill">{final_grade}</div></div>
    </div>
  </header>

  <section class="section content-grid" aria-label="사진과 종합 평가">
    <div class="panel photo-panel"><img src="{image_source}" alt="분석한 사진 미리보기"><div class="photo-caption">보고서에 삽입된 미리보기는 EXIF 민감 정보를 제거한 분석용 이미지입니다.{watermark_badge}</div></div>
    <div>
      <div class="section-title"><h2>전체 평가</h2></div>
      <article class="panel reason"><strong>한줄 총평</strong><p>{escape(analysis.final_reason)}</p></article>
      <div class="section-title" style="margin-top:20px"><h2>항목별 점수</h2><p>각 항목 10점 만점</p></div>
      <div class="score-grid">{category_cards}</div>
    </div>
  </section>

  <section class="section" aria-label="미학 태그">
    <div class="section-title"><h2>미학 태그</h2><p>시각적 근거 기반 · 범주별 최대 3개</p></div>
    {'' if has_aesthetic_tags else '<div class="empty-tags">이 기록에는 태그가 없습니다. 새 분석을 실행하거나 Excel 태그 열에서 입력할 수 있습니다.</div>'}
    <div class="tag-grid">{tag_cards}</div>
  </section>

  <section class="section list-grid" aria-label="강점과 개선점">
    <article class="panel list-card"><h3>주요 장점</h3><ul>{render_list(analysis.strengths)}</ul></article>
    <article class="panel list-card"><h3>단점 및 개선점</h3><ul>{render_list(analysis.improvements)}</ul></article>
  </section>{cross_check_section}
  <aside class="grade-guide" aria-label="점수 평가 기준 안내">
    <strong>점수 평가 기준:</strong>
    <span><b>9.0~10</b> 프로사진작가 및 전문가급</span> ·
    <span><b>8.0~8.9</b> 매우 우수</span> ·
    <span><b>7.0~7.9</b> 우수</span> ·
    <span><b>5.0~6.9</b> 보통 (일반 스냅)</span> ·
    <span><b>5.0 미만</b> 개선 필요 (기초 미흡)</span>
  </aside>
  <footer>생성된 HTML 단독 보고서 · 이미지는 분석용으로 재인코딩된 데이터만 포함합니다.</footer>
</main>
</body>
</html>
"""


def save_html_report(
    photo: PreparedPhoto,
    analysis: PhotoAnalysis,
    record_id: int,
    model: str,
    output_path: str | Path,
) -> Path:
    """Write a complete HTML report atomically and return its absolute path."""
    output = Path(output_path).expanduser()
    if output.suffix.lower() not in {".html", ".htm"}:
        raise ValueError(f"HTML 보고서 경로는 .html 또는 .htm이어야 합니다: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    content = render_html_report(photo, analysis, record_id, model)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{output.stem}.",
            suffix=output.suffix,
            dir=output.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        os.replace(temporary_path, output)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return output.resolve()


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
        analysis = r["analysis"]
        grade = get_score_grade(analysis.final_score)
        report_link = f'<a href="{escape(r["relative_report"])}">개별 보고서</a>' if r.get("relative_report") else "-"
        cross_check = getattr(analysis, "cross_check_opinion", None)
        cross_check_badge = ""
        if cross_check is not None:
            op_score = getattr(cross_check, "score", None)
            op_model = getattr(cross_check, "model", "OpenAI")
            if op_score is not None:
                cross_check_badge = f'<div style="font-size:0.75rem;color:#0284c7;font-weight:700;margin-top:2px;">🤝 {escape(str(op_model))} {float(op_score):.1f}</div>'
        rows_html.append(
            f"""<tr>
              <td><strong>{escape(r["filename"])}</strong></td>
              <td><span class="badge" style="background:#eef2ff;color:#4338ca;">{escape(getattr(analysis, 'figure_category', '일반'))}</span></td>
              <td><span class="badge">{escape(grade)}</span></td>
              <td><strong class="score">{analysis.final_score:.1f}</strong>{cross_check_badge}</td>
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
