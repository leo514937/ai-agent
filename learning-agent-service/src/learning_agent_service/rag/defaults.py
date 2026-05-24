from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .models import KnowledgeChunk


def _optional_str(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _repo_root() -> Optional[Path]:
    try:
        return Path(__file__).resolve().parents[4]
    except Exception:
        return None


def _markdown_sources() -> Tuple[Path, ...]:
    root = _repo_root()
    if root is None:
        return ()
    candidates = (
        root / "learning-agent-service" / "README.md",
        root / "doc" / "progress.md",
    )
    return tuple(path for path in candidates if path.is_file())


def _split_markdown_sections(text: str) -> Tuple[Tuple[str, int, str, int, int], ...]:
    sections: list[Tuple[str, int, str, int, int]] = []
    lines = text.splitlines()
    current_heading = "Overview"
    current_level = 1
    current_lines: list[str] = []
    current_start_line = 1

    for line_number, line in enumerate(lines, start=1):
        match = _HEADING_PATTERN.match(line)
        if match:
            section_text = "\n".join(current_lines).strip()
            if section_text:
                sections.append((current_heading, current_level, section_text, current_start_line, line_number - 1))
            current_heading = match.group(2).strip()
            current_level = len(match.group(1))
            current_lines = []
            current_start_line = line_number + 1
            continue
        current_lines.append(line)

    section_text = "\n".join(current_lines).strip()
    if section_text:
        sections.append((current_heading, current_level, section_text, current_start_line, len(lines) or 1))

    return tuple(sections)


def _normalize_tokens(text: str) -> Tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{2,}", text or ""):
        normalized = token.strip().lower()
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(normalized)
    return tuple(tokens[:8])


def _summarize_section(text: str) -> str:
    collapsed = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(collapsed) <= 220:
        return collapsed
    return collapsed[:217].rstrip() + "..."


def _infer_chunk_type(source_path: Path, heading: str, text: str) -> str:
    probe = f"{source_path.stem} {heading} {text[:240]}".lower()
    if any(keyword in probe for keyword in ("roadmap", "progress", "plan", "milestone")):
        return "roadmap"
    if any(keyword in probe for keyword in ("compare", "vs", "对比", "区别")):
        return "comparison"
    if any(keyword in probe for keyword in ("faq", "question", "answer", "q&a")):
        return "qa"
    if any(keyword in probe for keyword in ("pitfall", "risk", "warning", "注意")):
        return "pitfall"
    return "concept"


def _load_repo_local_rows() -> Tuple[Dict[str, Any], ...]:
    root = _repo_root()
    if root is None:
        return ()

    rows: list[Dict[str, Any]] = []
    for source_path in _markdown_sources():
        try:
            text = source_path.read_text(encoding="utf-8")
        except Exception:
            continue

        try:
            relative_path = source_path.relative_to(root)
        except Exception:
            relative_path = source_path

        document_id = "repo-md-{slug}".format(slug=str(relative_path.as_posix()).replace("/", "-").replace("\\", "-").lower())
        sections = _split_markdown_sections(text)
        if not sections:
            sections = (("Overview", 1, text.strip(), 1, len(text.splitlines()) or 1),)

        for index, (heading, heading_level, section_text, line_start, line_end) in enumerate(sections, start=1):
            normalized_text = section_text.strip()
            if not normalized_text:
                continue

            normalized_heading = heading or source_path.stem.replace("_", " ").title()
            chunk_id = "repo-{slug}-{index}-{digest}".format(
                slug=str(relative_path.as_posix()).replace("/", "-").replace("\\", "-").lower(),
                index=index,
                digest=hashlib.sha1(
                    f"{relative_path.as_posix()}:{index}:{normalized_heading}:{normalized_text}".encode("utf-8")
                ).hexdigest()[:12],
            )
            rows.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "title": normalized_heading,
                    "summary": _summarize_section(normalized_text),
                    "category": "repo",
                    "subcategory": source_path.stem,
                    "chunk_type": _infer_chunk_type(source_path, normalized_heading, normalized_text),
                    "source_type": "document",
                    "version": "repo-local",
                    "difficulty": "intermediate",
                    "tags": _normalize_tokens(f"{source_path.stem} {normalized_heading} {normalized_text[:160]}"),
                    "text": normalized_text,
                    "metadata": {
                        "source_path": str(relative_path.as_posix()),
                        "heading": normalized_heading,
                        "heading_level": heading_level,
                        "section_index": index,
                        "line_start": line_start,
                        "line_end": line_end,
                        "source_kind": "repo_local_markdown",
                    },
                }
            )
    return tuple(rows)


_DEFAULT_ROWS: Tuple[Dict[str, Any], ...] = ()


def build_default_chunks(rows: Sequence[Mapping[str, Any]] = _DEFAULT_ROWS) -> Tuple[KnowledgeChunk, ...]:
    return tuple(
        KnowledgeChunk(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            text=str(row["text"]),
            title=str(row.get("title") or row["chunk_id"]),
            summary=_optional_str(row.get("summary")),
            category=_optional_str(row.get("category")),
            subcategory=_optional_str(row.get("subcategory")),
            difficulty=_optional_str(row.get("difficulty")),
            source_type=_optional_str(row.get("source_type")),
            chunk_type=_optional_str(row.get("chunk_type")),
            version=_optional_str(row.get("version")),
            parent_id=_optional_str(row.get("parent_id")),
            is_latest=bool(row.get("is_latest", True)),
            hash=_optional_str(row.get("hash"))
            or hashlib.sha1(f'{row["document_id"]}:{row["chunk_id"]}:{row["text"]}'.encode("utf-8")).hexdigest(),
            tags=tuple(str(tag) for tag in row.get("tags", ()) if tag),
            metadata=dict(row.get("metadata", {})),
        )
        for row in rows
    )


@lru_cache(maxsize=1)
def build_repo_local_chunks() -> Tuple[KnowledgeChunk, ...]:
    return build_default_chunks(_load_repo_local_rows())


DEFAULT_KNOWLEDGE_CHUNKS: Tuple[KnowledgeChunk, ...] = build_default_chunks() + build_repo_local_chunks()
