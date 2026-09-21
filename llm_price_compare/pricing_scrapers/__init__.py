"""
pricing_scrapers — 各 LLM 提供商定价抓取器

每个抓取器实现统一接口：
  - fetch_pricing() -> dict: 返回标准化的定价数据
  - get_model_pricing(model_name: str) -> dict: 获取特定模型的定价

标准化输出格式：
{
    "provider": str,                    # 提供商名称
    "currency": str,                    # 货币单位 (CNY/USD)
    "pricing_unit": str,                # 计价单位 (per_million_tokens/per_1k_tokens等)
    "models": [
        {
            "model_id": str,            # 模型标识
            "model_name": str,          # 模型显示名称
            "input_price": float,       # 输入价格
            "output_price": float,      # 输出价格
            "cache_read_price": float,  # 缓存读取价格 (可选)
            "cache_write_price": float, # 缓存写入价格 (可选)
            "context_length": int,      # 上下文长度 (可选)
            "notes": str,               # 备注 (可选)
        }
    ],
    "last_updated": str,                # 最后更新时间
    "source_url": str,                  # 数据来源URL
}
"""

from .alibaba import AlibabaScraper
from .base import BaseScraper
from .deepseek import DeepSeekScraper
from .kimi import KimiScraper
from .xiaomi import XiaomiScraper
from .zhipu import ZhipuScraper

__all__ = [
    "AlibabaScraper",
    "BaseScraper",
    "DeepSeekScraper",
    "KimiScraper",
    "XiaomiScraper",
    "ZhipuScraper",
]

# 提供商映射，便于工厂函数使用
PROVIDER_SCRAPERS = {
    "deepseek": DeepSeekScraper,
    "zhipu": ZhipuScraper,
    "alibaba": AlibabaScraper,
    "xiaomi": XiaomiScraper,
    "kimi": KimiScraper,
}


def get_scraper(provider: str) -> BaseScraper:
    """工厂函数：根据提供商名称返回对应的抓取器实例"""
    scraper_cls = PROVIDER_SCRAPERS.get(provider.lower())
    if scraper_cls is None:
        raise ValueError(f"未知的提供商: {provider}，可用的提供商: {list(PROVIDER_SCRAPERS.keys())}")
    return scraper_cls()


# ---- 定价策略标准查询（供 config / UI 动态生成下拉，不再硬编码）---- #
_STRATEGY_FALLBACK: list[tuple[str, str]] = [("official", "官方价")]


def provider_pricing_strategies(provider: str) -> list[tuple[str, str]]:
    """返回某官方提供商抓取器支持的取价策略 [(value, label), ...]。"""
    cls = PROVIDER_SCRAPERS.get((provider or "").lower())
    return cls.pricing_strategies() if cls else list(_STRATEGY_FALLBACK)


def provider_default_strategy(provider: str) -> str:
    cls = PROVIDER_SCRAPERS.get((provider or "").lower())
    return cls.DEFAULT_STRATEGY if cls else "official"


def strategy_label(provider: str, value: str | None) -> str:
    """把策略 value 反查为中文 label（未知则原样返回）。"""
    for v, label in provider_pricing_strategies(provider):
        if v == value:
            return label
    return value or "—"

