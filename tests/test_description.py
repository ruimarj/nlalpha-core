"""Canonical description revisions, section reads, and packaged guidance contracts."""

import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from nlalpha.core.description import (
    describe_document,
    markdown_sections,
    read_common_about,
    read_skill,
    skill_catalog,
)
from nlalpha.core.errors import InvalidRequestError
from nlalpha.core.result_contract import failure_response


class DescriptionTest(unittest.TestCase):
    def test_revision_covers_complete_document_independent_of_selected_sections(self):
        sections = {"contract": {"value": 1}, "notes": "Exact source notes"}
        complete = describe_document("family", "cta", "package", "1", sections)
        for selected in ([], ["notes"], ["notes", "contract"], ["contract", "notes"]):
            with self.subTest(selected=selected):
                partial = describe_document("family", "cta", "package", "1", sections, selected)
                self.assertEqual(partial["description_revision"], complete["description_revision"])
                self.assertEqual(list(partial["sections"]), selected)
                self.assertEqual(partial["available_sections"], ["contract", "notes"])
                for name in selected:
                    self.assertEqual(partial["sections"][name], complete["sections"][name])
        content = {name: value for name, value in complete.items() if name != "description_revision"}
        canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self.assertEqual(complete["description_revision"], hashlib.sha256(canonical.encode()).hexdigest())
        sections["contract"]["value"] = 2
        changed = describe_document("family", "cta", "package", "1", sections, ["notes"])
        self.assertNotEqual(changed["description_revision"], complete["description_revision"])
        self.assertEqual(complete["sections"]["contract"]["value"], 1)

    def test_unknown_duplicate_and_invalid_section_selection_are_canonical_requests(self):
        for selected in (["unknown"], ["notes", "notes"], "notes", [None]):
            with self.subTest(selected=selected):
                with self.assertRaises(InvalidRequestError) as raised:
                    describe_document("family", "cta", None, None, {"notes": "source"}, selected)
                self.assertEqual(failure_response(raised.exception)["error"]["type"], "invalid_request")

    def test_markdown_sections_preserve_original_material_and_ignore_fenced_headings(self):
        material = "# Title\n\nIntro.\n\n## Exact Contract\n\n```text\n## Fenced heading\n```\n\n## Inputs & Limits\n\nSource.\n"
        sections = markdown_sections(material)
        self.assertEqual(list(sections), ["overview", "exact-contract", "inputs-limits"])
        self.assertIn("## Fenced heading", sections["exact-contract"])
        self.assertEqual(sections["inputs-limits"], "## Inputs & Limits\n\nSource.")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            markdown_sections("## Duplicate\nOne\n## Duplicate\nTwo")

    def test_canonical_resources_are_required_and_language_is_one_explicit_selection(self):
        self.assertIn("NLAlpha shared principles", read_common_about())
        english = read_skill()
        self.assertIn("Language: en", english)
        chinese = read_skill("strategy-authoring", "zh")
        self.assertIn("Language: zh", chinese)
        self.assertNotEqual(english, chinese)
        for name, language in (("../secret", "en"), ("strategy-authoring", "both"), (None, "en")):
            with self.subTest(name=name, language=language):
                with self.assertRaises(InvalidRequestError):
                    read_skill(name, language)
        with patch("nlalpha.core.description.resources.files", return_value=Path("/nonexistent-required-nlalpha-resource")):
            with self.assertRaises(FileNotFoundError):
                read_common_about()
            with self.assertRaises(FileNotFoundError):
                read_skill()

    def test_skill_catalog_describes_packaged_skills_in_declared_order(self):
        catalog = skill_catalog()
        self.assertEqual(catalog["schema"], "nlalpha.skill_catalog.v1")
        self.assertEqual(catalog["language"], "en")
        self.assertEqual(catalog["languages"], ["en", "zh"])
        self.assertEqual(
            [skill["name"] for skill in catalog["skills"]],
            ["strategy-authoring", "data-readiness", "backtest-execution"],
        )
        for skill in catalog["skills"]:
            with self.subTest(skill=skill["name"]):
                self.assertTrue(skill["title"])
                self.assertTrue(skill["description"])
                self.assertTrue(skill["revision"])
                self.assertEqual(
                    skill["content_sha256"],
                    hashlib.sha256(read_skill(skill["name"], "en").encode()).hexdigest(),
                )

    def test_skill_catalog_chinese_entries_translate_titles_and_descriptions(self):
        english = {skill["name"]: skill for skill in skill_catalog("en")["skills"]}
        chinese = {skill["name"]: skill for skill in skill_catalog("zh")["skills"]}
        self.assertEqual(
            [chinese[name]["title"] for name in english],
            ["策略编写", "数据准备", "回测执行"],
        )
        self.assertTrue(
            chinese["strategy-authoring"]["description"].startswith(
                "将用户提出的交易规则忠实整理为策略规格和实现。"
            )
        )
        for name, skill in chinese.items():
            with self.subTest(skill=name):
                self.assertNotEqual(skill["description"], english[name]["description"])
                self.assertIn(skill["title"], read_skill(name, "zh"))
                self.assertEqual(
                    skill["content_sha256"],
                    hashlib.sha256(read_skill(name, "zh").encode()).hexdigest(),
                )

    def test_skill_catalog_rejects_an_unsupported_language(self):
        with self.assertRaises(InvalidRequestError) as raised:
            skill_catalog("both")
        self.assertEqual(raised.exception.details["available_languages"], ["en", "zh"])
        self.assertEqual(failure_response(raised.exception)["error"]["type"], "invalid_request")
