"""命令行入口：解析参数、写配置目录环境变量并启动 Textual TUI。

约定与三款 controller 一致：支持 `-D/--dir`（指定配置目录，main 在导入 App 前写入
环境变量 `LLM_PRICE_COMPARE_CONFIG_DIR`）与 `--version`；位置参数 `config` 显式指定配置文件。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .config import CONFIG_DIR_ENV, get_default_config_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="llm-price", description="LLM 价格对比 TUI（启动即拉取并计算）"
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="配置文件路径（缺省自动定位：当前目录 config.yaml > 用户配置目录）",
    )
    parser.add_argument(
        "-D",
        "--dir",
        default=None,
        help=f"配置文件目录（覆盖环境变量 {CONFIG_DIR_ENV}）",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"llm-price {__version__}",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dir:
        os.environ[CONFIG_DIR_ENV] = args.dir

    config_path = args.config
    if config_path is None:
        local_cfg = Path("config.yaml")
        config_path = str(local_cfg) if local_cfg.exists() else str(get_default_config_path())

    from .app import PriceCompareApp

    PriceCompareApp(config_path).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
