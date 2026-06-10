"""语义切块器（v1.2 批次①）。

在 parsers 产出"自然段级"块之后、进抽取管道之前做一次结构化重组：

  - 识别法律条文边界（第X条 / 第X章）和标题块，按"条/标题"聚合；
  - 合并相邻小块，目标块大小由颗粒度档位决定（1200–3000 字）；
  - 每个合并块携带上下文头（所属章节路径），让跨段的
    假定条件/行为模式/法律后果能在同一次 LLM 调用里拼齐；
  - 直通文件（is_passthrough）不做任何处理。

收益：一份 150 自然段的文件从 150 次 LLM 调用降到 15–25 次。
"""
from __future__ import annotations

import re

from .parsers import ContentBlock, ParsedDocument

# 颗粒度档位 → 目标块字符数（档位越细块越小，规则越原子）
GRANULARITY_CHUNK_SIZES: dict[int, int] = {
    1: 3000,
    2: 2500,
    3: 2000,
    4: 1500,
    5: 1200,
}
DEFAULT_CHUNK_SIZE = 2000

# 超过目标的 1.6 倍就强制开新块（防止单块过大导致输出截断）
_OVERFLOW_FACTOR = 1.6

_ARTICLE_RX = re.compile(r"^\s*第[一二三四五六七八九十百千零0-9]+条")
_CHAPTER_RX = re.compile(r"^\s*第[一二三四五六七八九十百千零0-9]+[章节编]")

# 合同/协议常用大纲编号（"一、""（一）""1、""1."）。法规走"第X条"体例，
# 不识别这类编号；仅对合同类文件启用，避免把法条子项过度切碎。
_OUTLINE_RX = re.compile(
    r"^\s*(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十]+[）)]|\d+[、.．])"
)

# 法规来源标签：这些文件用"第X条"切块，不启用合同大纲编号边界。
_LAW_SOURCE_TAGS = frozenset({"法规", "监管文件"})


def chunk_target_size(granularity_level: int) -> int:
    return GRANULARITY_CHUNK_SIZES.get(int(granularity_level), DEFAULT_CHUNK_SIZE)


def chunk_document(doc: ParsedDocument, target_chars: int = DEFAULT_CHUNK_SIZE) -> ParsedDocument:
    """返回块已合并的新 ParsedDocument。直通文件原样返回。"""
    from dataclasses import replace

    if doc.is_passthrough or len(doc.blocks) <= 1:
        return doc
    enable_outline = doc.source_tag not in _LAW_SOURCE_TAGS
    merged = merge_blocks(doc.blocks, target_chars, enable_outline_split=enable_outline)
    return replace(doc, blocks=merged)


def merge_blocks(
    blocks: tuple[ContentBlock, ...],
    target_chars: int = DEFAULT_CHUNK_SIZE,
    enable_outline_split: bool = False,
) -> tuple[ContentBlock, ...]:
    """把段落级块聚合为语义块。

    切块规则（按优先级）：
      1. 章/编级标题：刷新上下文路径并强制开新块；
      2. "第X条"开头：若当前块已有内容则开新块（一条尽量完整落在一个块里）；
      3. 普通标题块（block_type=heading）：累计字数超过目标的一半就开新块；
      4. 累计字数达到目标即开新块；单块永不拆分（超长块独立成块）。
    """
    overflow = int(target_chars * _OVERFLOW_FACTOR)

    chunks: list[ContentBlock] = []
    buf: list[ContentBlock] = []
    buf_chars = 0
    buf_has_body = False  # 缓冲区是否含正文（仅标题不算，避免标题独立成块）
    context_path: list[str] = []  # 章节上下文，如 ["第三章 法律责任"]

    def flush() -> None:
        nonlocal buf, buf_chars, buf_has_body
        if not buf:
            return
        first, last = buf[0], buf[-1]
        header = f"【所属章节】{ ' ＞ '.join(context_path) }\n" if context_path else ""
        text = header + "\n".join(b.text for b in buf)
        location = (
            first.location
            if first.location == last.location
            else f"{first.location}~{last.location}"
        )
        block_type = "chunk" if len(buf) > 1 else first.block_type
        chunks.append(ContentBlock(
            block_id=f"{first.block_id}+{len(buf) - 1}" if len(buf) > 1 else first.block_id,
            text=text,
            location=location,
            block_type=block_type,
        ))
        buf = []
        buf_chars = 0
        buf_has_body = False

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue

        is_chapter = bool(_CHAPTER_RX.match(text))
        is_article = bool(_ARTICLE_RX.match(text))
        is_outline = enable_outline_split and bool(_OUTLINE_RX.match(text))
        is_heading = block.block_type == "heading"

        if is_chapter:
            flush()
            context_path = [text[:50]]
            # 章标题本身并入下一个块（保留语境）
            buf.append(block)
            buf_chars += len(text)
            continue

        # "第X条"或合同大纲编号（一、/（一）/1、）开头：当前块已有正文则开新块，
        # 让每一条/项尽量独立成块，避免多个子项挤进一次 LLM 调用而被漏抽。
        if (is_article or is_outline) and buf_has_body:
            flush()
        elif is_heading and buf_chars >= target_chars // 2:
            flush()
        elif buf_chars >= target_chars:
            flush()

        buf.append(block)
        buf_chars += len(text)
        # 法条"第X条"/合同大纲项是正文承载单元（解析器常把它标成 heading），必须计入正文，
        # 否则相邻条/项的"按条开新块"永远不触发，多条会挤进同一个块。
        if not is_heading or is_article or is_outline:
            buf_has_body = True

        if buf_chars >= overflow:
            flush()

    flush()
    return tuple(chunks)
