"""
base.py — 抓取器基类

定义统一的接口和通用工具方法
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import requests


class BaseScraper(ABC):
    """定价抓取器基类"""

    # 子类应覆盖这些属性
    PROVIDER_NAME: str = ""
    SOURCE_URL: str = ""

    # 定价策略「标准暴露」：每个抓取器声明自己支持的取价策略 (value, label)。
    # UI 的下拉、core 的取价都以此为准，不再硬编码。默认只有一个「官方价」。
    # 若提供商存在多时段价（如 DeepSeek 峰/谷），子类覆写本列表与 select_prices()。
    PRICING_STRATEGIES: list[tuple[str, str]] = [("official", "官方价")]
    DEFAULT_STRATEGY: str = "official"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })

    def fetch_pricing(self) -> dict:
        """抓取并返回标准化的定价数据"""
        try:
            models = self._do_fetch()
            if not models:
                raise ValueError("未抓取到有效模型数据")
            return self._build_result(models, success=True)
        except Exception as e:
            models = self._get_fallback_data()
            return self._build_result(models, success=False, error=str(e))

    @abstractmethod
    def _do_fetch(self) -> list[dict]:
        """实际执行抓取（子类实现）"""
        ...

    @abstractmethod
    def _get_fallback_data(self) -> list[dict]:
        """内置降级数据（子类实现）"""
        ...

    def get_model_pricing(self, model_name: str) -> dict | None:
        """获取特定模型的定价，返回标准化格式或 None"""
        pricing = self.fetch_pricing()
        # 优先精确匹配，再模糊匹配
        target = model_name.lower().strip()
        for model in pricing.get("models", []):
            mid = model.get("model_id", "").lower().strip()
            mname = model.get("model_name", "").lower().strip()
            if target == mid or target == mname:
                return model
        for model in pricing.get("models", []):
            mid = model.get("model_id", "").lower().strip()
            mname = model.get("model_name", "").lower().strip()
            if target in mid or mid in target or target in mname:
                return model
        return None

    @classmethod
    def pricing_strategies(cls) -> list[tuple[str, str]]:
        """返回本提供商支持的取价策略 [(value, label), ...]。"""
        return cls.PRICING_STRATEGIES

    @classmethod
    def select_prices(cls, item: dict, strategy: str | None = None) -> dict:
        """从抓取到的某模型条目中，按定价策略挑出四维价（元/百万 token）。

        默认实现适用于「单一官方价」的抓取器；含多时段价的（DeepSeek 峰/谷）
        由子类覆写。core 层只认约定的 input/output/cache_* 键，不感知时段细节。
        """
        return {
            "input": item.get("input_price", 0.0),
            "output": item.get("output_price", 0.0),
            "cache_read": item.get("cache_read_price", 0.0),
            "cache_write": item.get("cache_write_price", 0.0),
        }

    def _get_json(self, url: str, **kwargs) -> Any:
        """GET 请求并解析 JSON"""
        resp = self.session.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _get_text(self, url: str, **kwargs) -> str:
        """GET 请求并返回文本"""
        resp = self.session.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.text

    def _extract_json_from_html(self, html: str, pattern: str = None) -> Any:
        """从 HTML 中提取 JSON 数据"""
        if pattern:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        # 尝试提取 <script> 标签中的 JSON
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
        for script in scripts:
            # 查找类似 window.__INITIAL_STATE__ = {...} 的模式
            match = re.search(r'(?:window\.__\w+__\s*=\s*|data\s*=\s*)(\{.*?\});?\s*$', script, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        return None

    def _parse_price(self, value: Any) -> float:
        """解析价格值，处理各种格式"""
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # 移除逗号
            cleaned = value.strip().replace(",", "")
            if '免费' in cleaned or 'free' in cleaned.lower():
                return 0.0
            # 使用正则提取数字部分
            match = re.search(r"(\d+\.?\d*)", cleaned)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return 0.0
            return 0.0
        return 0.0

    def _build_result(self, models: list[dict], **kwargs) -> dict:
        """构建标准化的返回结果"""
        return {
            "provider": self.PROVIDER_NAME,
            "currency": kwargs.get("currency", "CNY"),
            "pricing_unit": kwargs.get("pricing_unit", "per_million_tokens"),
            "models": models,
            "last_updated": datetime.now().isoformat(),
            "source_url": self.SOURCE_URL,
            "success": kwargs.get("success", True),
            "error": kwargs.get("error", None),
        }
