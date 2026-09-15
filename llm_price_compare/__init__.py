"""
llm_price_compare — LLM 模型官方与 OpenRouter 价格全自动对比工具
"""

__version__ = "0.1.0"

from .main import PriceCompareApp, main

__all__ = [
    "PriceCompareApp",
    "__version__",
    "main",
]
