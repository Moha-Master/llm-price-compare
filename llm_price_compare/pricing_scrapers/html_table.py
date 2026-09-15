"""
html_table.py — 纯标准库轻量 HTML 表格提取器
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag = tag.lower()
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._current_row = []
        elif tag in ("th", "td") and self._in_row:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag == "table" and self._in_table:
            self._in_table = False
            if self._current_table:
                self.tables.append(self._current_table)
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._current_row:
                self._current_table.append(self._current_row)
        elif tag in ("th", "td") and self._in_cell:
            self._in_cell = False
            cell_text = "".join(self._current_cell).strip()
            # 压缩空白字符
            cell_text = re.sub(r"\s+", " ", cell_text)
            self._current_row.append(cell_text)

    def handle_data(self, data: str):
        if self._in_cell:
            self._current_cell.append(data)


def parse_html_tables(html: str) -> list[list[list[str]]]:
    """解析 HTML 中的所有表格，返回结构: [表格1, 表格2, ...]
    每个表格为行列表，每行为单元格文本列表。
    """
    parser = TableParser()
    parser.feed(html)
    return parser.tables
