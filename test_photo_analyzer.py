from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational
from pydantic import ValidationError

import photo_analyzer
from photo_analyzer import PhotoAnalysis, analyze_with_gemini, prepare_photo, save_analysis
from photo_tag_schema import AestheticTags


class PhotoAnalyzerTests(unittest.TestCase):
    def _make_jpeg(self, path: Path, *, with_exif: bool = False) -> None:
        image = Image.new("RGB", (16, 12), (90, 120, 150))
        save_options = {"format": "JPEG"}
        if with_exif:
            exif = Image.Exif()
            exif[271] = "Example Camera"  # Make
            exif[272] = "Model X"  # Model
            exif[306] = "2026:01:02 03:04:05"  # DateTime; must be omitted
            exif[315] = "Private Owner"  # Artist; must be omitted
            exif[34853] = {
                1: "N",
                2: (IFDRational(37, 1), IFDRational(30, 1), IFDRational(0, 1)),
                3: "E",
                4: (IFDRational(127, 1), IFDRational(0, 1), IFDRational(0, 1)),
            }  # GPS IFD; must be omitted
            exif[34665] = {
                33434: IFDRational(1, 125),  # ExposureTime
                33437: IFDRational(56, 10),  # FNumber
                34855: 400,  # ISOSpeedRatings
            }
            save_options["exif"] = exif
        image.save(path, **save_options)

    def _valid_analysis(self) -> PhotoAnalysis:
        return PhotoAnalysis(
            composition_score=8,
            composition_notes="주제가 잘 배치되었습니다.",
            lighting_score=7.5,
            lighting_notes="부드러운 빛이 사용되었습니다.",
            color_score=8,
            color_notes="색 조화가 자연스럽습니다.",
            technique_score=7,
            technique_notes="초점이 안정적입니다.",
            final_score=7.8,
            final_reason="전체 완성도가 좋습니다.",
            strengths=["안정된 구도"],
            improvements=["배경을 단순화해 보세요."],
            aesthetic_tags=AestheticTags.empty().model_copy(
                update={
                    "viewpoint": ["정면"],
                    "composition_space": ["삼분할 구도"],
                    "mood": ["고요함"],
                }
            ),
        )

    def test_exif_allowlist_is_embedded_but_private_metadata_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path, with_exif=True)
            photo = prepare_photo(image_path)

            self.assertEqual(photo.safe_exif["Make"], "Example Camera")
            self.assertEqual(photo.safe_exif["Model"], "Model X")
            self.assertAlmostEqual(photo.safe_exif["ExposureTime"], 1 / 125)
            self.assertAlmostEqual(photo.safe_exif["FNumber"], 5.6)
            self.assertEqual(photo.safe_exif["ISOSpeedRatings"], 400)
            self.assertNotIn("DateTime", photo.safe_exif)
            self.assertNotIn("Artist", photo.safe_exif)

            with Image.open(BytesIO(photo.upload_bytes)) as uploaded_image:
                uploaded_exif = uploaded_image.getexif()
                self.assertNotIn(34853, uploaded_exif)
                self.assertNotIn(306, uploaded_exif)
                self.assertNotIn(315, uploaded_exif)
                uploaded_ifd = uploaded_exif.get_ifd(photo_analyzer.EXIF_IFD_ID)
                uploaded_fields = {
                    ExifTags.TAGS.get(tag_id): value
                    for tag_id, value in uploaded_ifd.items()
                }
                self.assertAlmostEqual(float(uploaded_fields["ExposureTime"]), 1 / 125)
                self.assertAlmostEqual(float(uploaded_fields["FNumber"]), 5.6)
                self.assertEqual(uploaded_fields["ISOSpeedRatings"], 400)

    def test_gemini_request_includes_safe_settings_and_loads_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            image_path = directory / "sample.jpg"
            env_path = directory / ".env"
            env_path.write_text("GEMINI_API_KEY=unit-test-key\n", encoding="utf-8")
            self._make_jpeg(image_path, with_exif=True)
            photo = prepare_photo(image_path)

            with patch.object(photo_analyzer, "ENV_FILE_PATH", env_path), patch.dict(os.environ):
                os.environ.pop("GEMINI_API_KEY", None)
                with patch.object(photo_analyzer.genai, "Client") as client_factory:
                    client = client_factory.return_value
                    client.interactions.create.return_value.output_text = (
                        self._valid_analysis().model_dump_json()
                    )
                    result = analyze_with_gemini(photo)

                self.assertEqual(result.final_score, 7.8)
                client_factory.assert_called_once_with(api_key="unit-test-key")
                request = client.interactions.create.call_args.kwargs
                prompt = request["input"][0]["text"]
                self.assertIn('"ExposureTime": 0.008', prompt)
                self.assertIn('"FNumber": 5.6', prompt)
                self.assertIn('"ISOSpeedRatings": 400', prompt)
                self.assertNotIn("2026:01:02 03:04:05", prompt)
                self.assertIn("aesthetic_tags", prompt)
                self.assertIn("정면, 측면, 후면", prompt)
                self.assertIn("0~3개 선택하세요", prompt)
                schema = request["response_format"]["schema"]
                self.assertIn("aesthetic_tags", schema["required"])
                self.assertEqual(
                    set(schema["$defs"]["AestheticTags"]["required"]),
                    set(AestheticTags.model_fields),
                )

                sent_image = base64.b64decode(request["input"][1]["data"])
                with Image.open(BytesIO(sent_image)) as uploaded_image:
                    uploaded_exif = uploaded_image.getexif()
                    self.assertNotIn(34853, uploaded_exif)
                    sent_ifd = uploaded_exif.get_ifd(photo_analyzer.EXIF_IFD_ID)
                sent_names = {ExifTags.TAGS.get(tag_id) for tag_id in sent_ifd}
                self.assertTrue(
                    {"ExposureTime", "FNumber", "ISOSpeedRatings"} <= sent_names
                )

    def test_mpo_input_is_reencoded_as_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "sample.mpo"
            self._make_jpeg(image_path)
            with Image.open(image_path) as source:
                source.format = "MPO"
                with patch.object(photo_analyzer.Image, "open", return_value=source):
                    photo = prepare_photo(image_path)

            self.assertEqual(photo.image_format, "MPO")
            self.assertEqual(photo.upload_mime_type, "image/jpeg")
            with Image.open(BytesIO(photo.upload_bytes)) as uploaded_image:
                self.assertEqual(uploaded_image.format, "JPEG")

    def test_scores_outside_zero_to_ten_are_rejected(self) -> None:
        payload = self._valid_analysis().model_dump()
        payload["final_score"] = 10.1
        with self.assertRaises(ValidationError):
            PhotoAnalysis.model_validate(payload)

    def test_unknown_or_excessive_aesthetic_tags_are_rejected(self) -> None:
        payload = self._valid_analysis().model_dump()
        payload["aesthetic_tags"]["viewpoint"] = ["정면", "측면", "후면", "사선"]
        with self.assertRaises(ValidationError):
            PhotoAnalysis.model_validate(payload)

        payload["aesthetic_tags"]["viewpoint"] = ["파노라마 시점"]
        with self.assertRaises(ValidationError):
            PhotoAnalysis.model_validate(payload)

    def test_legacy_analysis_without_tag_field_uses_empty_tag_defaults(self) -> None:
        payload = self._valid_analysis().model_dump(exclude={"aesthetic_tags"})
        restored = PhotoAnalysis.model_validate(payload)
        self.assertEqual(restored.aesthetic_tags.viewpoint, [])
        self.assertEqual(restored.aesthetic_tags.narrative_implication, [])

    def test_validated_analysis_and_safe_exif_are_saved_to_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            image_path = directory / "sample.jpg"
            database_path = directory / "analysis.sqlite3"
            self._make_jpeg(image_path, with_exif=True)
            photo = prepare_photo(image_path)

            record_id = save_analysis(database_path, photo, "test-model", self._valid_analysis())
            self.assertGreater(record_id, 0)

            with closing(sqlite3.connect(database_path)) as connection:
                row = connection.execute(
                    "SELECT exif_json, analysis_json FROM photo_analyses WHERE id = ?",
                    (record_id,),
                ).fetchone()
                stored_tags = connection.execute(
                    "SELECT category_key, tag FROM photo_analysis_tags WHERE analysis_id = ? ORDER BY category_key",
                    (record_id,),
                ).fetchall()
                catalog_count = connection.execute(
                    "SELECT COUNT(*) FROM photo_tag_catalog"
                ).fetchone()[0]
            self.assertIsNotNone(row)
            exif_data = json.loads(row[0])
            analysis_data = json.loads(row[1])
            self.assertNotIn("GPSInfo", exif_data)
            self.assertNotIn("DateTime", exif_data)
            self.assertEqual(analysis_data["final_score"], 7.8)
            self.assertEqual(
                stored_tags,
                [("composition_space", "삼분할 구도"), ("mood", "고요함"), ("viewpoint", "정면")],
            )
            self.assertGreater(catalog_count, 0)


if __name__ == "__main__":
    unittest.main()
