"""
alibaba.py — 阿里云百炼平台 Qwen 模型定价抓取器
"""

from __future__ import annotations

from .base import BaseScraper


class AlibabaScraper(BaseScraper):
    PROVIDER_NAME = "Alibaba"
    SOURCE_URL = "https://bailian.console.aliyun.com/cn-beijing/pricing"

    def _do_fetch(self) -> list[dict]:
        # 目前阿里云页面内容完全使用客户端 JS 异步请求，网页不含静态 JSON
        # 这里返回降级数据作为基准，若后期提供开放 API 可在此扩展
        return self._get_fallback_data()

    def _get_fallback_data(self) -> list[dict]:
        return [
            {"model_id": "qwen3.8-max", "model_name": "qwen3.8-max", "input_price": 12.0, "output_price": 36.0, "cache_read_price": 1.5, "cache_write_price": 15.0},
            {"model_id": "qwen3.8-flash", "model_name": "qwen3.8-flash", "input_price": 0.8, "output_price": 2.7, "cache_read_price": 0.1, "cache_write_price": 1.25},
            {"model_id": "qwen3.8-27b", "model_name": "qwen3.8-27b", "input_price": 3.0, "output_price": 12.0, "cache_read_price": 0.3, "cache_write_price": 4.0},
            {"model_id": "qwen3.7-plus", "model_name": "qwen3.7-plus", "input_price": 2.0, "output_price": 8.0, "cache_read_price": 0.2, "cache_write_price": 3.0},
            {"model_id": "qwen3.7-max", "model_name": "qwen3.7-max", "input_price": 12.0, "output_price": 36.0, "cache_read_price": 1.2, "cache_write_price": 15.0},
        ]
