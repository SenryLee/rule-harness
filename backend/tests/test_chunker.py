from __future__ import annotations

from backend.chunker import chunk_target_size, merge_blocks
from backend.parsers import ContentBlock


def _block(i: int, text: str, block_type: str = "paragraph") -> ContentBlock:
    return ContentBlock(block_id=f"p{i}", text=text, location=str(i), block_type=block_type)


def test_chunk_target_size_by_level():
    assert chunk_target_size(1) == 3000
    assert chunk_target_size(3) == 2000
    assert chunk_target_size(5) == 1200
    assert chunk_target_size(99) == 2000  # 非法档位回退默认


def test_merge_blocks_reduces_block_count():
    blocks = tuple(_block(i, f"第{i}段，" + "内容" * 50) for i in range(40))  # 每段约104字
    merged = merge_blocks(blocks, target_chars=2000)
    assert len(merged) < len(blocks) / 3
    # 不丢内容
    assert sum("内容" in b.text for b in merged) == len(merged)


def test_merge_blocks_article_boundary_starts_new_chunk():
    blocks = (
        _block(0, "第一条 " + "甲" * 1500),
        _block(1, "第二条 " + "乙" * 100),
    )
    merged = merge_blocks(blocks, target_chars=2000)
    # "第二条"开头且缓冲区已有内容 → 开新块
    assert len(merged) == 2
    assert merged[0].text.startswith("第一条")
    assert merged[1].text.startswith("第二条")


def test_merge_blocks_splits_heading_typed_articles():
    """回归：解析器把"第X条"标成 heading 时，多条短法条不得被并进一个块。

    这正是法规类文件欠抽的根因——条文被当标题导致 buf_has_body 永不置真，
    "按条开新块"从不触发，10 条法条挤进一次 LLM 调用。
    """
    blocks = tuple(
        _block(i, f"第{i}条 " + "甲" * 40, block_type="heading")
        for i in range(1, 11)  # 10 条短法条，每条约 44 字，远不到 target
    )
    merged = merge_blocks(blocks, target_chars=2000)
    # 每条法条各自成块，而不是全部并成 1 块
    assert len(merged) == 10
    assert all(b.text.startswith(f"第{i}条") for i, b in enumerate(merged, start=1))


def test_merge_blocks_chapter_context_header():
    blocks = (
        _block(0, "第三章 法律责任"),
        _block(1, "第四十二条 " + "违" * 100),
    )
    merged = merge_blocks(blocks, target_chars=2000)
    assert len(merged) == 1
    assert merged[0].text.startswith("【所属章节】第三章 法律责任")


def test_merge_blocks_keeps_oversized_block_whole():
    big = _block(0, "超" * 5000)
    merged = merge_blocks((big, _block(1, "尾段")), target_chars=2000)
    assert any("超" * 100 in b.text for b in merged)
    # 超长块不被拆分
    assert sum(b.text.count("超") for b in merged) == 5000


def test_outline_split_separates_contract_subitems():
    """合同大纲编号（1、/2、…）开启时，相邻短子项各自成块，不被并进一块。

    这正是合同末尾"双方责任"6 个小项挤进一个 chunk、管辖/解释权被漏抽的根因。
    """
    blocks = tuple(
        _block(i, f"{i}、本项约定内容 " + "甲" * 30)
        for i in range(1, 7)  # 6 个子项，每个约 40 字，远不到 target
    )
    merged = merge_blocks(blocks, target_chars=2000, enable_outline_split=True)
    assert len(merged) == 6
    assert all(b.text.lstrip().startswith(f"{i}、") for i, b in enumerate(merged, start=1))


def test_outline_split_handles_chinese_numerals():
    blocks = (
        _block(0, "一、目的：互利互惠。"),
        _block(1, "二、协议内容：" + "乙" * 30),
        _block(2, "（三）补充说明：" + "丙" * 30),
    )
    merged = merge_blocks(blocks, target_chars=2000, enable_outline_split=True)
    assert len(merged) == 3


def test_outline_split_disabled_keeps_law_chunking_unchanged():
    """法规（enable_outline_split=False，默认）下，大纲编号不触发开新块——

    保证法规切块行为与改造前逐字一致。
    """
    blocks = tuple(_block(i, f"{i}、短项内容") for i in range(1, 7))
    off = merge_blocks(blocks, target_chars=2000)  # 默认 False
    # 6 个短项按字数合并为单块，与历史行为一致
    assert len(off) == 1
