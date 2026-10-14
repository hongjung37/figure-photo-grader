"""Unit tests for Lightroom / Capture One XMP sidecar generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from photo_xmp_manager import generate_xmp_xml, score_to_rating_and_label, write_xmp_sidecar


class PhotoXmpManagerTests(unittest.TestCase):
    def test_score_to_rating_and_label_mapping(self) -> None:
        self.assertEqual(score_to_rating_and_label(9.5), (5, "Purple"))
        self.assertEqual(score_to_rating_and_label(8.3), (4, "Blue"))
        self.assertEqual(score_to_rating_and_label(7.4), (3, "Green"))
        self.assertEqual(score_to_rating_and_label(6.2), (2, "Yellow"))
        self.assertEqual(score_to_rating_and_label(4.5), (1, "Red"))

    def test_generate_xmp_xml_contains_standard_tags_and_escapes(self) -> None:
        xml = generate_xmp_xml(
            score=8.5,
            reason="빛과 그림자의 대비가 <뛰어남> & 완성도 높음",
            figure_category="스튜디오 연출/디오라마",
            tags=["삼분할 구도", "로우 앵글"],
            strengths=["선명한 조형"],
            improvements=["상단 여백 정리"],
        )
        self.assertIn("<xmp:Rating>4</xmp:Rating>", xml)
        self.assertIn("<xmp:Label>Blue</xmp:Label>", xml)
        self.assertIn("<photoshop:ColorLabel>Blue</photoshop:ColorLabel>", xml)
        self.assertIn("&lt;뛰어남&gt; &amp; 완성도 높음", xml)
        self.assertIn("<rdf:li>스튜디오 연출/디오라마</rdf:li>", xml)
        self.assertIn("<rdf:li>삼분할 구도</rdf:li>", xml)
        self.assertIn("<rdf:li>로우 앵글</rdf:li>", xml)
        self.assertIn("[장점] 선명한 조형", xml)
        self.assertIn("[보완점] 상단 여백 정리", xml)

    def test_write_xmp_sidecar_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            photo_file = Path(temp_dir) / "sample_fig.webp"
            photo_file.write_bytes(b"dummy")

            xmp_path = write_xmp_sidecar(
                photo_path=photo_file,
                score=7.8,
                reason="우수한 조명 컨트롤",
                figure_category="접사/디테일",
                tags=["칼초점"],
            )
            self.assertTrue(xmp_path.is_file())
            self.assertEqual(xmp_path.name, "sample_fig.xmp")
            content = xmp_path.read_text(encoding="utf-8")
            self.assertIn("<xmp:Rating>3</xmp:Rating>", content)
            self.assertIn("<xmp:Label>Green</xmp:Label>", content)
            self.assertIn("접사/디테일", content)


if __name__ == "__main__":
    unittest.main()
