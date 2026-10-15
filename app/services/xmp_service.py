"""app.services.xmp_service - Adobe Lightroom / Capture One compatible XMP sidecar generator."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from app.models.analysis import get_score_grade


def score_to_rating_and_label(score: float) -> tuple[int, str]:
    """Convert photo grading score (0~10) to Lightroom 1~5 stars and color label."""
    if score >= 9.0:
        return 5, "Purple"
    if score >= 8.0:
        return 4, "Blue"
    if score >= 7.0:
        return 3, "Green"
    if score >= 5.0:
        return 2, "Yellow"
    return 1, "Red"


def generate_xmp_xml(
    score: float,
    reason: str,
    figure_category: str = "일반 피규어 촬영",
    tags: list[str] | None = None,
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
) -> str:
    """Generate valid Adobe XMP Core sidecar XML content."""
    rating, color_label = score_to_rating_and_label(score)
    grade = get_score_grade(score)

    keywords = [figure_category, f"등급:{grade}"]
    if tags:
        keywords.extend(tags)

    description_parts = [f"[{grade} {score:.1f}점] {reason}"]
    if strengths:
        description_parts.append("[장점] " + " · ".join(strengths))
    if improvements:
        description_parts.append("[보완점] " + " · ".join(improvements))
    full_description = "\n\n".join(description_parts)

    keyword_items = "\n     ".join(f"<rdf:li>{escape(k)}</rdf:li>" for k in keywords if k)
    escaped_desc = escape(full_description)

    return f"""<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="FigurePhotoGrader XMP 1.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/">
   <xmp:Rating>{rating}</xmp:Rating>
   <xmp:Label>{color_label}</xmp:Label>
   <photoshop:ColorLabel>{color_label}</photoshop:ColorLabel>
   <dc:description>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{escaped_desc}</rdf:li>
    </rdf:Alt>
   </dc:description>
   <dc:subject>
    <rdf:Bag>
     {keyword_items}
    </rdf:Bag>
   </dc:subject>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""


def write_xmp_sidecar(
    photo_path: Path,
    score: float,
    reason: str,
    figure_category: str = "일반 피규어 촬영",
    tags: list[str] | None = None,
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
    target_xmp_path: Path | None = None,
) -> Path:
    """Write an XMP sidecar file for a photo and return its path."""
    xmp_file = target_xmp_path if target_xmp_path else photo_path.with_suffix(".xmp")
    content = generate_xmp_xml(
        score=score,
        reason=reason,
        figure_category=figure_category,
        tags=tags,
        strengths=strengths,
        improvements=improvements,
    )
    xmp_file.write_text(content, encoding="utf-8")
    return xmp_file
