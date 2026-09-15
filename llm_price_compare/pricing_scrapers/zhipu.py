"""
zhipu.py — 智谱 AI 官方定价实时抓取器
"""

from __future__ import annotations

from .base import BaseScraper
from .html_table import parse_html_tables


class ZhipuScraper(BaseScraper):
    PROVIDER_NAME = "Zhipu"
    SOURCE_URL = "https://docs.bigmodel.cn/cn/guide/start/pricing"

    def _do_fetch(self) -> list[dict]:
        resp = self.session.get(self.SOURCE_URL, timeout=15)
        resp.encoding = "utf-8"
        tables = parse_html_tables(resp.text)
        if not tables:
            raise ValueError("未找到表格")

        models = []
        for table in tables:
            if not table:
                continue
            header = table[0]
            # 检查是否是模型定价表
            if "模型名称" not in header[0]:
                continue

            # 确定索引
            col_map = {name: i for i, name in enumerate(header)}
            idx_name = col_map.get("模型名称", 0)
            idx_input = col_map.get("输入单价（元/百万 Tokens）", 2)
            idx_output = col_map.get("输出单价（元/百万 Tokens）", 3)
            idx_cache = col_map.get("缓存命中（元/百万 Tokens）", 5)

            for row in table[1:]:
                if len(row) < 4:
                    continue
                name = row[idx_name].strip()
                if not name:
                    continue

                # 智谱的模型名有时会重复（不同分段），我们只取第一个或合法的
                input_val = row[idx_input]
                output_val = row[idx_output]
                cache_val = row[idx_cache] if idx_cache < len(row) else "0"

                models.append({
                    "model_id": name.lower().replace(" ", "-"),
                    "model_name": name,
                    "input_price": self._parse_price(input_val),
                    "output_price": self._parse_price(output_val),
                    "cache_read_price": self._parse_price(cache_val),
                    "cache_write_price": 0.0,
                    "context_length": 1_000_000, # 默认
                    "notes": f"来自表格: {header[0]}",
                })
        return models

    def _get_fallback_data(self) -> list[dict]:
        return [
            {"model_id": "glm-5.3", "model_name": "GLM-5.3", "input_price": 8.0, "output_price": 28.0, "cache_read_price": 2.0},
            {"model_id": "glm-5.3-flash", "model_name": "GLM-5.3-Flash", "input_price": 0.8, "output_price": 2.8, "cache_read_price": 0.23},
            {"model_id": "glm-4.7-flash", "model_name": "GLM-4.7-Flash", "input_price": 0.0, "output_price": 0.0},
        ]
