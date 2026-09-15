"""
deepseek.py — DeepSeek 官方定价实时抓取器
"""

from __future__ import annotations

from .base import BaseScraper
from .html_table import parse_html_tables


class DeepSeekScraper(BaseScraper):
    PROVIDER_NAME = "DeepSeek"
    SOURCE_URL = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"

    def _do_fetch(self) -> list[dict]:
        resp = self.session.get(self.SOURCE_URL, timeout=15)
        resp.encoding = "utf-8"
        tables = parse_html_tables(resp.text)
        if not tables:
            raise ValueError("未找到表格")

        table = tables[0]
        model_ids = ["deepseek-flash", "deepseek-v4-pro"]
        model_names = ["DeepSeek-V4.1-Flash", "DeepSeek-V4-Pro-0813"]

        peak_rows = []
        for row in table:
            if row and row[0].strip() == "高峰时段":
                peak_rows.append(row)

        cache_read_prices = [0.04, 0.30]
        input_prices = [2.0, 9.0]
        output_prices = [8.0, 27.0]

        if len(peak_rows) >= 3:
            cache_read_prices = [self._parse_price(x) for x in peak_rows[0][1:]]
            input_prices = [self._parse_price(x) for x in peak_rows[1][1:]]
            output_prices = [self._parse_price(x) for x in peak_rows[2][1:]]

        models = []
        for i, mid in enumerate(model_ids):
            models.append({
                "model_id": mid,
                "model_name": model_names[i],
                "input_price": input_prices[i] if i < len(input_prices) else 2.0,
                "output_price": output_prices[i] if i < len(output_prices) else 8.0,
                "cache_read_price": cache_read_prices[i] if i < len(cache_read_prices) else 0.04,
                "cache_write_price": 0.0,
                "context_length": 1_000_000,
                "notes": "高峰时段价格；空闲时段折半",
            })
        return models

    def _get_fallback_data(self) -> list[dict]:
        return [
            {
                "model_id": "deepseek-flash",
                "model_name": "DeepSeek-V4.1-Flash",
                "input_price": 2.0,
                "output_price": 8.0,
                "cache_read_price": 0.04,
                "cache_write_price": 0.0,
                "context_length": 1_000_000,
                "notes": "高峰时段价格；空闲时段折半",
            },
            {
                "model_id": "deepseek-v4-pro",
                "model_name": "DeepSeek-V4-Pro-0813",
                "input_price": 9.0,
                "output_price": 27.0,
                "cache_read_price": 0.30,
                "cache_write_price": 0.0,
                "context_length": 1_000_000,
                "notes": "高峰时段价格；空闲时段折半",
            },
        ]
