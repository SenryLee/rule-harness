from __future__ import annotations

from pathlib import Path

import openpyxl

from backend.parsers import parse_excel


def _write_xlsx(path: Path, sheets: dict[str, list[list]]) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    wb.save(str(path))
    return path


def test_rule_library_xlsx_is_passthrough_per_row(tmp_path):
    """规则库表（表头命中审查类关键词）→ 直通，每条数据行一个 table_row 块。"""
    p = _write_xlsx(tmp_path / "rules.xlsx", {
        "规则": [
            ["检查项", "审查要求", "风险程度", "审查说明"],
            ["保密条款是否到位", "不得向第三方披露", "高", "核对范围"],
            ["管辖是否约定", "明确管辖法院", "中", "注意倾向性"],
        ],
    })
    doc = parse_excel(p, source_tag="审查清单", contract_types=[])
    assert doc.is_passthrough is True
    rows = [b for b in doc.blocks if b.block_type == "table_row"]
    assert len(rows) == 2
    assert "检查项: 保密条款是否到位" in rows[0].text
    assert "风险程度: 高" in rows[0].text


def test_content_xlsx_emits_labeled_per_row_blocks_not_one_blob(tmp_path):
    """内容表（非规则库）→ 不再整表拼成一个巨块；每行一个带"表头: 值"标注的块。

    且表头之上的标题行不被误当表头（列不错位）。
    """
    p = _write_xlsx(tmp_path / "content.xlsx", {
        "明细": [
            ["2024年酒店预付款明细表", None, None],   # 标题行（应被跳过）
            ["甲方", "金额", "期限"],                  # 真正表头
            ["和峰投资", "200000", "2024-12-31"],
            ["天夏旅行社", "40000", "2024-12-31"],
            [None, None, None],                        # 空行（应跳过）
            ["备注", "赠送额度不退款", None],
        ],
    })
    doc = parse_excel(p, source_tag="历史合同", contract_types=["酒店预付款"])
    assert doc.is_passthrough is False
    content = [b for b in doc.blocks if b.block_type == "paragraph"]
    # 3 条非空数据行各自成块，而不是 1 个巨块
    assert len(content) == 3
    # 列语义保留：值带各自表头标注，不串味
    assert "甲方: 和峰投资" in content[0].text
    assert "金额: 200000" in content[0].text
    assert "期限: 2024-12-31" in content[0].text
    # 空单元格被跳过（备注行只有两列有值）
    assert content[2].text == "甲方: 备注; 金额: 赠送额度不退款"


def test_blank_header_cell_gets_column_fallback_label(tmp_path):
    p = _write_xlsx(tmp_path / "blankhdr.xlsx", {
        "S": [
            ["项目", None, "金额"],   # 第二列表头空
            ["客房", "标准间", "300"],
        ],
    })
    doc = parse_excel(p, source_tag="历史合同", contract_types=[])
    content = [b for b in doc.blocks if b.block_type == "paragraph"]
    assert len(content) == 1
    # 空表头列兜底为 列B，值不丢、不并入相邻列
    assert "列B: 标准间" in content[0].text


def test_multi_sheet_content_has_sheet_heading_context(tmp_path):
    p = _write_xlsx(tmp_path / "multi.xlsx", {
        "客房价": [["房型", "价格"], ["大床房", "300"]],
        "会议室价": [["类型", "价格"], ["小厅", "800"]],
    })
    doc = parse_excel(p, source_tag="历史合同", contract_types=[])
    headings = [b for b in doc.blocks if b.block_type == "heading"]
    texts = " ".join(h.text for h in headings)
    assert "【工作表：客房价】" in texts
    assert "【工作表：会议室价】" in texts


def test_xls_emits_clear_warning_not_silent_empty(tmp_path):
    # 造一个假的 .xls（内容不是真 OLE2，仅验证扩展名分支给出明确提示）
    fake = tmp_path / "old.xls"
    fake.write_bytes(b"\xd0\xcf\x11\xe0not-a-real-xls")
    doc = parse_excel(fake, source_tag="历史合同", contract_types=[])
    assert doc.blocks == ()
    assert "xls_unsupported_convert_to_xlsx" in doc.parse_warnings
