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
PRICING_STRATEGIES = ["lowest", "expected"]


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
    """返回完美的默认初始配置模板"""
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
                "display_name": "DeepSeek V4 Flash",
                "models": [
                    {"name": "DeepSeek 官方", "id": "deepseek-flash", "type": "deepseek"},
                    {"name": "V4F 0423", "id": "deepseek/deepseek-v4-flash", "type": "openrouter", "pricing": "expected"},
                    {"name": "V4F 0731", "id": "deepseek/deepseek-v4-flash-0731", "type": "openrouter", "pricing": "expected"},
                    {"name": "V4F Latest", "id": "~deepseek/deepseek-v4-flash-latest", "type": "openrouter", "pricing": "expected"},
                    {"name": "V4F Vision Exp", "id": "deepseek/deepseek-v4-flash-vision-exp", "type": "openrouter", "pricing": "expected"}
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
    """返回一个可编辑的空白骨架配置（向导「从零开始」用）"""
    return {
        "exchange_rate": {"usd_to_cny": 6.71},
        "scenarios": [
            {
                "name": "Claude Code",
                "tokens": {"cache_read": 0.85, "cache_write": 0.10, "input": 0.04, "output": 0.01},
            }
        ],
        "groups": [
            {
                "display_name": "My Model",
                "models": [
                    {"name": "官方", "id": "", "type": "deepseek"},
                    {"name": "OpenRouter", "id": "", "type": "openrouter", "pricing": "expected"},
                ],
            }
        ],
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
