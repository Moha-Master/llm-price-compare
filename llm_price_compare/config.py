"""
config.py — 配置文件加载、保存及配置目录管理
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

CONFIG_DIR_ENV = "LLM_PRICE_COMPARE_CONFIG_DIR"
DEFAULT_CONFIG_DIR = "~/.config/llm-price-compare"

# 定价来源类型：openrouter 走官方 REST API，其余走各自定价页抓取器
OFFICIAL_TYPES = ["deepseek", "zhipu", "alibaba", "xiaomi", "kimi"]
PROVIDER_TYPES = [*OFFICIAL_TYPES, "openrouter"]

# OpenRouter 的两种取价策略（其余来源的策略由各抓取器标准暴露，见 pricing_scrapers）
OR_PRICING_STRATEGIES: list[tuple[str, str]] = [
    ("lowest", "最低价(headline)"),
    ("expected", "期望价(路由加权)"),
]
OR_DEFAULT_STRATEGY = "expected"


def pricing_strategies_for(ptype: str) -> list[tuple[str, str]]:
    """按定价来源类型返回其取价策略 [(value, label), ...]。

    统一入口：openrouter 用内置两种；官方提供商转交给对应抓取器
    （如 DeepSeek 峰/谷/自动），不再在 UI 层硬编码。
    """
    if ptype == "openrouter":
        return list(OR_PRICING_STRATEGIES)
    try:
        from .pricing_scrapers import provider_pricing_strategies
    except ImportError:  # pragma: no cover
        from pricing_scrapers import provider_pricing_strategies  # type: ignore
    return provider_pricing_strategies(ptype)


def default_pricing(ptype: str) -> str:
    """某来源类型的默认定价策略 value。"""
    if ptype == "openrouter":
        return OR_DEFAULT_STRATEGY
    try:
        from .pricing_scrapers import provider_default_strategy
    except ImportError:  # pragma: no cover
        from pricing_scrapers import provider_default_strategy  # type: ignore
    return provider_default_strategy(ptype)


def pricing_label(ptype: str, value: str | None) -> str:
    """策略 value → 中文 label（用于模型表展示）。"""
    for v, label in pricing_strategies_for(ptype):
        if v == value:
            return label
    return value or "—"



def get_config_dir() -> Path:
    """获取配置目录路径"""
    config_dir = os.environ.get(
        CONFIG_DIR_ENV,
        DEFAULT_CONFIG_DIR,
    )
    return Path(config_dir).expanduser()


def get_default_config_path() -> Path:
    """获取默认配置文件路径"""
    return get_config_dir() / "config.yaml"


def get_default_config() -> dict:
    """返回内置「推荐」模板（对齐用户线上 config.yaml 的四组）。"""
    return {
        "exchange_rate": {
            "usd_to_cny": 6.71
        },
        "scenarios": [
            {
                "name": "Claude Code",
                "tokens": {
                    "cache_read": 0.85,
                    "cache_write": 0.10,
                    "input": 0.04,
                    "output": 0.01
                }
            }
        ],
        "groups": [
            {
                "display_name": "DeepSeek V4.1 Flash",
                "models": [
                    {"name": "DeepSeek 官方", "id": "deepseek-flash", "type": "deepseek", "pricing": "auto"},
                    {"name": "OpenRouter", "id": "deepseek/deepseek-4.1-flash", "type": "openrouter", "pricing": "expected"},
                ]
            },
            {
                "display_name": "Xiaomi MiMo V2.5",
                "models": [
                    {"name": "MiMo 官方", "id": "mimo-v2.5", "type": "xiaomi"},
                    {"name": "MiMo V2.5", "id": "xiaomi/mimo-v2.5", "type": "openrouter", "pricing": "expected"}
                ]
            },
            {
                "display_name": "Zhipu GLM 5.3 Flash",
                "models": [
                    {"name": "GLM 官方", "id": "glm-5.3-flash", "type": "zhipu"},
                    {"name": "GLM 5.3F", "id": "z-ai/glm-5.3-flash", "type": "openrouter", "pricing": "expected"},
                    {"name": "GLM Flash Latest", "id": "z-ai/glm-flash-latest", "type": "openrouter", "pricing": "expected"}
                ]
            },
            {
                "display_name": "Qwen3.8 Flash",
                "models": [
                    {"name": "Qwen 官方", "id": "qwen3.8-flash", "type": "alibaba"},
                    {"name": "Qwen3.8 Flash", "id": "qwen/qwen3.8-flash", "type": "openrouter", "pricing": "expected"}
                ]
            }
        ]
    }


def config_exists(config_path: str | Path | None = None) -> bool:
    """判断配置文件是否已存在（存在性检查，不触发写入）"""
    target = get_default_config_path() if config_path is None else Path(config_path)
    return target.exists()


def get_blank_config() -> dict:
    """空白骨架：仅汇率 + 默认场景，对比组留空。

    向导选「空白」后，主程序会自动打开设置页并给出去噪引导，
    由用户在「对比组」里亲手添加第一个组，故此处 groups 为空。
    """
    return {
        "exchange_rate": {"usd_to_cny": 6.71},
        "scenarios": [
            {
                "name": "Claude Code",
                "tokens": {"cache_read": 0.85, "cache_write": 0.10, "input": 0.04, "output": 0.01},
            }
        ],
        "groups": [],
    }



def ensure_config_exists(config_path: str | Path | None = None) -> Path:
    """确保配置文件存在，若不存在则自动初始化默认配置文件"""
    if config_path is None:
        target_path = get_default_config_path()
    else:
        target_path = Path(config_path)

    if not target_path.exists():
        save_config(get_default_config(), target_path)

    return target_path


def load_config(config_path: str | Path | None = None) -> dict:
    """加载并解析配置文件"""
    if config_path is None:
        target_path = ensure_config_exists()
    else:
        target_path = Path(config_path)

    if not target_path.exists():
        target_path = ensure_config_exists(target_path)

    with open(target_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError("配置文件必须为映射结构")

    if "groups" not in config and "sync_pairs" not in config:
        raise ValueError("配置文件中必须包含 groups 字段或旧版 sync_pairs 字段")

    return config


def save_config(config: dict, config_path: str | Path | None = None) -> Path:
    """保存配置"""
    if config_path is None:
        target_path = get_default_config_path()
    else:
        target_path = Path(config_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return target_path
