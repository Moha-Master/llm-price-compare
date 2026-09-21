"""
deepseek.py — DeepSeek 官方定价实时抓取器（含峰 / 谷时段）

官方定价页（Docusaurus 服务端渲染，可静态解析）把每个价类拆成两行：
「空闲时段」行带维度标签与谷价，紧随的「高峰时段」行只带时段与峰价。
本抓取器把峰 / 谷两组价都结构化，并通过标准接口暴露三种取价策略：
peak / valley / auto。

auto 判定（依据官方公告）：
- 周末（无论是否调休）→ 谷价
- 中国法定节假日 → 谷价（数据来自 GitHub holiday-cn 项目）
- 工作日 09:00-12:00、14:00-18:00 → 峰价
- 其余时间 → 谷价
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

import requests as _requests

from .base import BaseScraper
from .html_table import parse_html_tables

CST = timezone(timedelta(hours=8))  # 固定偏移，无需 tzdata
PEAK_WINDOWS: list[tuple[dtime, dtime]] = [
    (dtime(9, 0), dtime(12, 0)),
    (dtime(14, 0), dtime(18, 0)),
]

# ---- 中国法定节假日数据（来自 GitHub） ---------------------------------------- #
_HOLIDAYS_URL = "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json"
_holidays_cache: set[str] | None = None
_holidays_cache_year: int | None = None


def _fetch_holidays(year: int) -> set[str]:
    """获取指定年份的节假日日期集合（格式 'YYYY-MM-DD'）。"""
    global _holidays_cache, _holidays_cache_year
    if _holidays_cache_year == year and _holidays_cache is not None:
        return _holidays_cache
    try:
        resp = _requests.get(_HOLIDAYS_URL.format(year=year), timeout=5)
        resp.raise_for_status()
        data = resp.json()
        _holidays_cache = {d["date"] for d in data.get("days", []) if d.get("isOffDay")}
        _holidays_cache_year = year
        return _holidays_cache
    except Exception:
        return set()


def _is_cn_holiday(d) -> bool:
    """判断指定日期是否为中国法定节假日（休息日）。"""
    if hasattr(d, "date"):
        d = d.date()
    return _fetch_holidays(d.year).__contains__(d.isoformat())


# 维度顺序（页面行序：缓存命中 → 缓存未命中 → 输出）
_DIMS = ("cache_read", "input", "output")
_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*元")


def is_peak(now: datetime | None = None) -> bool:
    """判断给定时刻（默认当前）是否处于 DeepSeek 高峰时段。

    规则（依据官方公告）：
    - 周末（无论是否调休）→ 谷价
    - 中国法定节假日 → 谷价
    - 工作日 09:00-12:00、14:00-18:00 → 峰价
    - 其余时间 → 谷价
    """
    now = now.astimezone(CST) if now else datetime.now(CST)
    if now.weekday() >= 5:  # 周六(5)/周日(6)
        return False
    if _is_cn_holiday(now):
        return False
    t = now.time()
    return any(start <= t < end for start, end in PEAK_WINDOWS)


class DeepSeekScraper(BaseScraper):
    PROVIDER_NAME = "DeepSeek"
    SOURCE_URL = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"

    PRICING_STRATEGIES: list[tuple[str, str]] = [
        ("peak", "峰价（高峰时段）"),
        ("valley", "谷价（空闲时段）"),
        ("auto", "自动（按当前时间）"),
    ]
    DEFAULT_STRATEGY = "auto"

    MODEL_IDS = ["deepseek-flash", "deepseek-v4-pro"]
    MODEL_NAMES = ["DeepSeek-V4.1-Flash", "DeepSeek-V4-Pro-0813"]

    # ---- 标准暴露：按策略取价 ------------------------------------------------ #
    @classmethod
    def select_prices(cls, item: dict, strategy: str | None = None) -> dict:
        s = strategy or cls.DEFAULT_STRATEGY
        if s == "auto":
            s = "peak" if is_peak() else "valley"
        suffix = "_peak" if s == "peak" else "_valley"
        return {
            "input": item.get(f"input_price{suffix}", item.get("input_price", 0.0)),
            "output": item.get(f"output_price{suffix}", item.get("output_price", 0.0)),
            "cache_read": item.get(f"cache_read_price{suffix}", item.get("cache_read_price", 0.0)),
            "cache_write": item.get("cache_write_price", 0.0),
        }

    # ---- 解析辅助 ---------------------------------------------------------- #
    @staticmethod
    def _period_of(joined: str) -> str | None:
        if "空闲" in joined:
            return "valley"
        if "高峰" in joined:
            return "peak"
        return None

    @staticmethod
    def _dim_of(joined: str) -> str | None:
        if "缓存命中" in joined:
            return "cache_read"
        if "缓存未命中" in joined:
            return "input"
        if "输出" in joined:
            return "output"
        if "输入" in joined:
            return "input"
        return None

    @staticmethod
    def _price_cells(row: list[str]) -> list[float]:
        """抽取形如「0.02元 / 1元」的价格单元 → 浮点列表（按列顺序）。"""
        out: list[float] = []
        for cell in row:
            m = _PRICE_RE.search(cell)
            if m:
                out.append(float(m.group(1)))
        return out

    def _do_fetch(self) -> list[dict]:
        resp = self.session.get(self.SOURCE_URL, timeout=15)
        resp.encoding = "utf-8"
        tables = parse_html_tables(resp.text)
        if not tables:
            raise ValueError("未找到定价表格")

        n = len(self.MODEL_IDS)
        periods: dict[str, dict[str, list[float]]] = {"peak": {}, "valley": {}}
        current_dim: str | None = None
        for row in tables[0]:
            if not row:
                continue
            joined = "".join(row)
            period = self._period_of(joined)
            if period is None:
                continue
            # 维度标签只在「空闲」行；「高峰」行继承上一个维度
            dim = self._dim_of(joined) or current_dim
            if dim is None:
                continue
            current_dim = dim
            vals = self._price_cells(row)
            if len(vals) >= n and dim not in periods[period]:
                periods[period][dim] = vals[:n]

        peak, valley = periods["peak"], periods["valley"]
        missing = [d for d in _DIMS if d not in peak]
        if missing:
            raise ValueError(f"高峰价缺少: {missing}")
        # 谷价缺项则按官方「峰价折半」补齐
        if any(d not in valley for d in _DIMS):
            valley = {d: [p / 2 for p in peak[d]] for d in _DIMS}

        models = []
        for i, mid in enumerate(self.MODEL_IDS):
            p_in, p_out, p_cache = peak["input"][i], peak["output"][i], peak["cache_read"][i]
            v_in, v_out, v_cache = valley["input"][i], valley["output"][i], valley["cache_read"][i]
            models.append({
                "model_id": mid,
                "model_name": self.MODEL_NAMES[i],
                # 向后兼容字段（= 峰价）
                "input_price": p_in,
                "output_price": p_out,
                "cache_read_price": p_cache,
                "cache_write_price": 0.0,
                # 峰 / 谷双价
                "input_price_peak": p_in,
                "output_price_peak": p_out,
                "cache_read_price_peak": p_cache,
                "input_price_valley": v_in,
                "output_price_valley": v_out,
                "cache_read_price_valley": v_cache,
                "context_length": 1_000_000,
                "currency": "CNY",
                "notes": "官方峰/谷双时段价（元/百万 token）",
            })
        return models

    def _get_fallback_data(self) -> list[dict]:
        peak = {"deepseek-flash": (2.0, 8.0, 0.04), "deepseek-v4-pro": (9.0, 27.0, 0.30)}
        models = []
        for mid, name in zip(self.MODEL_IDS, self.MODEL_NAMES, strict=True):
            p_in, p_out, p_cache = peak[mid]
            models.append({
                "model_id": mid,
                "model_name": name,
                "input_price": p_in,
                "output_price": p_out,
                "cache_read_price": p_cache,
                "cache_write_price": 0.0,
                "input_price_peak": p_in,
                "output_price_peak": p_out,
                "cache_read_price_peak": p_cache,
                "input_price_valley": p_in / 2,
                "output_price_valley": p_out / 2,
                "cache_read_price_valley": p_cache / 2,
                "context_length": 1_000_000,
                "currency": "CNY",
                "notes": "官方峰/谷双时段价（降级数据，谷价=峰价/2）",
            })
        return models
