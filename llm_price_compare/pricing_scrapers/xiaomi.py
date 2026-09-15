"""
xiaomi.py — 小米 MiMo 官方定价实时抓取器
"""

from __future__ import annotations

from .base import BaseScraper
from .html_table import parse_html_tables


class XiaomiScraper(BaseScraper):
    PROVIDER_NAME = "Xiaomi"
    SOURCE_URL = "https://mimo.mi.com/docs/zh-CN/price/pay-as-you-go"

    def _do_fetch(self) -> list[dict]:
        resp = self.session.get(self.SOURCE_URL, timeout=15)
        resp.encoding = "utf-8"
        tables = parse_html_tables(resp.text)
        if not tables:
            raise ValueError("未找到表格")

        # 第一个表格是国内 LLM 定价
        table = tables[0]
        models = []
        for row in table[1:]:
            if len(row) < 4:
                continue
            name = row[0].strip()
            cache_hit = self._parse_price(row[1])
            input_price = self._parse_price(row[2])
            output_price = self._parse_price(row[3])

            models.append({
                "model_id": name,
                "model_name": name,
                "input_price": input_price,
                "output_price": output_price,
                "cache_read_price": cache_hit,
                "cache_write_price": 0.0,
                "context_length": 1_000_000,
                "notes": "官方定价",
            })
        return models

    def _get_fallback_data(self) -> list[dict]:
        return [
            {"model_id": "mimo-v2.5-pro", "model_name": "mimo-v2.5-pro", "input_price": 3.0, "output_price": 6.0, "cache_read_price": 0.025},
            {"model_id": "mimo-v2.5", "model_name": "mimo-v2.5", "input_price": 1.0, "output_price": 2.0, "cache_read_price": 0.02},
        ]
