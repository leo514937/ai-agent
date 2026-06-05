from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import KnowledgeChunk


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _repo_root() -> Path | None:
    try:
        return Path(__file__).resolve().parents[4]
    except Exception:
        return None


def _markdown_sources() -> tuple[Path, ...]:
    root = _repo_root()
    if root is None:
        return ()
    candidates = (
        root / "learning-agent-service" / "README.md",
        root / "doc" / "progress.md",
    )
    return tuple(path for path in candidates if path.is_file())


def _split_markdown_sections(text: str) -> tuple[tuple[str, int, str, int, int], ...]:
    sections: list[tuple[str, int, str, int, int]] = []
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


def _normalize_tokens(text: str) -> tuple[str, ...]:
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


def _load_repo_local_rows() -> tuple[dict[str, Any], ...]:
    root = _repo_root()
    if root is None:
        return ()

    rows: list[dict[str, Any]] = []
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
                    f"{relative_path.as_posix()}:{index}:{normalized_heading}:{normalized_text}".encode()
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


_DEFAULT_ROWS: tuple[dict[str, Any], ...] = (
    {
        "chunk_id": "rag-concept",
        "document_id": "doc-rag",
        "title": "RAG是什么",
        "text": "RAG (Retrieval-Augmented Generation) 检索增强生成，通过从外部知识库检索相关信息来增强语言模型回答的准确性。",
        "summary": "RAG concept and overview",
        "category": "ai",
        "subcategory": "rag",
        "chunk_type": "concept",
        "tags": ("rag", "concept", "检索增强生成", "rag是什么"),
        "metadata": {},
    },
    {
        "chunk_id": "spring-aop-compare",
        "document_id": "doc-spring",
        "title": "Spring AOP vs 动态代理",
        "text": "Spring AOP 底部使用 JDK 动态代理和 CGLIB 字节码生成来提供面向切面编程的支持。",
        "summary": "Spring AOP vs dynamic proxy comparison",
        "category": "java",
        "subcategory": "spring",
        "chunk_type": "comparison",
        "tags": ("spring", "aop", "动态代理", "cglib", "spring aop vs 动态代理"),
        "metadata": {},
    },
    {
        "chunk_id": "java-threadpool-concept",
        "document_id": "doc-java-threadpool",
        "title": "ThreadPoolExecutor 的核心参数有哪些",
        "text": "ThreadPoolExecutor 的核心参数包括：corePoolSize (核心线程数), maximumPoolSize (最大线程数), keepAliveTime (线程保持活跃时间), workQueue (工作队列) 等。",
        "summary": "ThreadPoolExecutor parameters description",
        "category": "java",
        "subcategory": "concurrency",
        "chunk_type": "concept",
        "tags": ("java", "threadpool", "threadpoolexecutor", "核心参数"),
        "metadata": {},
    },
    {
        "chunk_id": "react-cot-compare",
        "document_id": "doc-agent",
        "title": "ReAct 和 CoT 区别",
        "text": "ReAct 将推理 (Reasoning) 和行动 (Acting) 结合起来，而 CoT (Chain of Thought) 仅关注推理链的生成。",
        "summary": "ReAct and CoT comparison",
        "category": "ai",
        "subcategory": "agent",
        "chunk_type": "comparison",
        "tags": ("react", "cot", "agent", "推理", "行动", "react 和 cot 区别"),
        "metadata": {},
    },
    {
        "chunk_id": "family-dinner-restaurant",
        "document_id": "doc-family-dinner",
        "title": "适合带父母吃饭的餐厅",
        "text": "北京适合带爸妈吃饭的餐厅推荐：静雅轩，环境安静，菜品清淡，老年人特别喜欢。",
        "summary": "Family dinner restaurants recommendation",
        "category": "local_life",
        "subcategory": "restaurant",
        "chunk_type": "recommendation",
        "tags": ("推荐", "餐厅", "带爸妈", "带长辈", "适合带爸妈吃饭的餐厅", "适合", "带父母", "family_dinner"),
        "metadata": {"shop_name": "静雅轩", "voucher_count": 2, "package_description": "带爸妈四人套餐"},
    },
)


def build_default_chunks(rows: Sequence[Mapping[str, Any]] = _DEFAULT_ROWS) -> tuple[KnowledgeChunk, ...]:
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
            or hashlib.sha1(f'{row["document_id"]}:{row["chunk_id"]}:{row["text"]}'.encode()).hexdigest(),
            tags=tuple(str(tag) for tag in row.get("tags", ()) if tag),
            metadata=dict(row.get("metadata", {})),
        )
        for row in rows
    )


@lru_cache(maxsize=1)
def build_repo_local_chunks() -> tuple[KnowledgeChunk, ...]:
    return build_default_chunks(_load_repo_local_rows())


DEFAULT_KNOWLEDGE_CHUNKS: tuple[KnowledgeChunk, ...] = build_default_chunks() + build_repo_local_chunks()
