"""Canonical self-description documents and packaged task guidance."""

from copy import deepcopy
import hashlib
from importlib import resources
from importlib.metadata import version
import json
import re
from typing import Any

from nlalpha.core.errors import InvalidRequestError

DESCRIPTION_SCHEMA = "nlalpha.description.v1"
SKILL_CATALOG_SCHEMA = "nlalpha.skill_catalog.v1"
SKILL_NAMES = ("strategy-authoring", "data-readiness", "backtest-execution")
SKILL_LANGUAGES = ("en", "zh")


def describe_document(
    kind: str,
    id: str,
    package: str | None,
    version: str | None,
    sections: dict[str, Any],
    selected_sections: list[str] | None = None,
) -> dict[str, Any]:
    """Build a versioned description whose revision covers every section."""
    if selected_sections is not None:
        if (not isinstance(selected_sections, list)
                or any(not isinstance(section, str) for section in selected_sections)):
            raise InvalidRequestError("sections must be a list of section identifiers", stage="request")
        if len(selected_sections) != len(set(selected_sections)):
            raise InvalidRequestError("sections must not contain duplicate identifiers", stage="request")
        unknown = sorted(set(selected_sections) - sections.keys())
        if unknown:
            raise InvalidRequestError(
                f"Unknown description sections: {', '.join(unknown)}",
                details={"unknown_sections": unknown, "available_sections": list(sections)},
                stage="request",
            )
    document = {
        "schema": DESCRIPTION_SCHEMA, "id": id, "kind": kind,
        "package": package, "version": version,
        "available_sections": list(sections), "sections": deepcopy(sections),
    }
    canonical = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    document["description_revision"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if selected_sections is not None:
        document["sections"] = {name: document["sections"][name] for name in selected_sections}
    return document


def markdown_sections(markdown: str) -> dict[str, str]:
    """Split level-two English headings into stable section identifiers."""
    sections: dict[str, str] = {}
    name = "overview"
    lines: list[str] = []
    fenced = False
    fence_marker = ""
    for line in markdown.splitlines(keepends=True):
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)[0]
            if not fenced:
                fenced, fence_marker = True, marker
            elif marker == fence_marker:
                fenced = False
        heading = None if fenced else re.match(r"^##\s+(.+?)\s*#*\s*$", line)
        if heading:
            content = "".join(lines).strip()
            if content:
                sections[name] = content
            name = re.sub(r"[^a-z0-9]+", "-", heading.group(1).lower()).strip("-")
            if not name or name in sections:
                raise ValueError(f"Invalid or duplicate Markdown section: {heading.group(1)}")
            lines = [line]
        else:
            lines.append(line)
    content = "".join(lines).strip()
    if content:
        if name in sections:
            raise ValueError(f"Duplicate Markdown section: {name}")
        sections[name] = content
    return sections


def read_common_about() -> str:
    """Read the required packaged common principles."""
    return resources.files("nlalpha.core").joinpath("knowledge", "about.md").read_text(encoding="utf-8")


def common_description() -> dict[str, Any]:
    """Describe shared principles with their own package identity and revision."""
    return describe_document(
        "common", "nlalpha.common", "nlalpha-core", version("nlalpha-core"),
        markdown_sections(read_common_about()),
    )


def read_skill(name: str = "strategy-authoring", language: str = "en") -> str:
    """Read one canonical task skill in the requested language."""
    if name not in SKILL_NAMES:
        raise InvalidRequestError(
            f"Unknown skill: {name}", details={"available_skills": list(SKILL_NAMES)}, stage="request",
        )
    if language not in SKILL_LANGUAGES:
        raise InvalidRequestError(
            f"Unsupported skill language: {language}",
            details={"available_languages": list(SKILL_LANGUAGES)}, stage="request",
        )
    return resources.files("nlalpha.core").joinpath("skills", f"{name}.{language}.md").read_text(encoding="utf-8")


def _first_section_paragraph(lines: list[str]) -> str:
    # 首个二级标题下的首段：跳过标题后的空行，遇到空行或下一个标题即结束
    in_section = False
    paragraph: list[str] = []
    for line in lines:
        if not in_section:
            in_section = bool(re.match(r"^##\s+", line))
            continue
        if re.match(r"^##\s+", line):
            break
        if not line.strip():
            if paragraph:
                break
            continue
        paragraph.append(line.strip())
    return " ".join(paragraph).strip()


def _skill_metadata(name: str, language: str, markdown: str) -> dict[str, str]:
    """Extract the required title, revision, and first-section description from one skill."""
    lines = markdown.splitlines()
    title = next((match.group(1).strip() for line in lines if (match := re.match(r"^#\s+(.+?)\s*$", line))), "")
    revision = next(
        (match.group(1).strip() for line in lines if (match := re.match(r"^Revision:\s*(\S+)\s*$", line))), "",
    )
    description = _first_section_paragraph(lines)
    if not (title and revision and description):
        missing = ", ".join(
            field for field, value in (("title", title), ("revision", revision), ("description", description))
            if not value
        )
        raise ValueError(f"Skill {name}.{language}.md has unparsable metadata: {missing}")
    return {"title": title, "revision": revision, "description": description}


def skill_catalog(language: str = "en") -> dict[str, Any]:
    """Describe every packaged task skill in one language, in declared order."""
    if language not in SKILL_LANGUAGES:
        raise InvalidRequestError(
            f"Unsupported skill language: {language}",
            details={"available_languages": list(SKILL_LANGUAGES)}, stage="request",
        )
    skills: list[dict[str, str]] = []
    for name in SKILL_NAMES:
        markdown = read_skill(name, language)
        metadata = _skill_metadata(name, language, markdown)
        skills.append({
            "name": name,
            "title": metadata["title"],
            "description": metadata["description"],
            "revision": metadata["revision"],
            "content_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        })
    return {
        "schema": SKILL_CATALOG_SCHEMA,
        "language": language,
        "languages": list(SKILL_LANGUAGES),
        "skills": skills,
    }
