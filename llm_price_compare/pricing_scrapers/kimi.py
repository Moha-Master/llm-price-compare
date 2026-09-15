"""
kimi.py — Kimi (Moonshot AI) 官方定价实时抓取器
"""

from __future__ import annotations

import re

from .base import BaseScraper


class KimiScraper(BaseScraper):
    PROVIDER_NAME = "Kimi"
    SOURCE_URL = "https://platform.kimi.com/docs/pricing/chat"

    def _do_fetch(self) -> list[dict]:
        resp = self.session.get(self.SOURCE_URL, timeout=15)
        resp.encoding = "utf-8"

        # 匹配模式: [`kimi-k3`,`1M tokens`,`¥2.00`,`¥20.00`,`¥100.00`,`1,048,576 tokens`]
        pattern = r"\[`([a-zA-Z0-9\.\-_]+)`,`1M tokens`,`([^`]+)`,`([^`]+)`,`([^`]+)`,`([^`]+)`\]"
        matches = re.findall(pattern, resp.text)
        if not matches:
            raise ValueError("未在 Kimi 页面中匹配到模型定价条目")

        models = []
        for name, cache_hit_str, input_str, output_str, context_str in matches:
            models.append({
                "model_id": name,
                "model_name": name,
                "input_price": self._parse_price(input_str),
                "output_price": self._parse_price(output_str),
                "cache_read_price": self._parse_price(cache_hit_str),
                "cache_write_price": 0.0,
                "context_length": int(context_str.replace(",", "").replace("tokens", "").strip() or 0),
                "notes": f"上下文: {context_str}",
            })
        return models

    def _get_fallback_data(self) -> list[dict]:
        return [
            {"model_id": "kimi-k3", "model_name": "kimi-k3", "input_price": 20.0, "output_price": 100.0, "cache_read_price": 2.0},
            {"model_id": "kimi-k2.7-code", "model_name": "kimi-k2.7-code", "input_price": 6.5, "output_price": 27.0, "cache_read_price": 1.3},
            {"model_id": "kimi-k2.6", "model_name": "kimi-k2.6", "input_price": 6.5, "output_price": 27.0, "cache_read_price": 1.1},
        ]
