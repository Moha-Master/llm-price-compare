"""
setup_wizard.py — 首次启动配置向导（Textual ModalScreen）

当目标配置文件不存在时展示，引导用户选择初始模板与汇率并写盘。
"""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from . import config as cfg


class SetupScreen(ModalScreen[str]):
    """返回 "done"（已生成配置）或 "cancel"（用户放弃）。"""

    DEFAULT_CSS = """
    SetupScreen {
        align: center middle;
    }
    SetupScreen > Vertical {
        width: 72;
        max-width: 92%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    SetupScreen #wizard-title {
        text-align: center;
        padding-bottom: 1;
    }
    SetupScreen #wizard-desc {
        text-style: dim;
        padding-bottom: 1;
    }
    SetupScreen .wizard-field {
        margin-top: 1;
    }
    SetupScreen Select, SetupScreen Input {
        width: 100%;
    }
    SetupScreen #wizard-path {
        text-style: dim;
        padding-top: 1;
    }
    SetupScreen .wizard-actions {
        align-horizontal: right;
        padding-top: 1;
    }
    SetupScreen .wizard-actions Button {
        margin-left: 2;
    }
    """

    def __init__(self, target_path: str | Path | None = None) -> None:
        super().__init__()
        self._target = Path(target_path) if target_path else cfg.get_default_config_path()

    def compose(self):
        with Vertical():
            yield Label("👋  欢迎使用 LLM Price Compare", id="wizard-title")
            yield Static(
                "首次运行需要先创建一份配置文件。你可以直接套用推荐的对比组，\n"
                "或从空白开始，稍后再编辑。所有价格都会在运行时自动抓取。",
                id="wizard-desc",
            )
            yield Label("初始配置模板", classes="wizard-field")
            yield Select(
                [
                    ("推荐：内置 DeepSeek / 小米 / 智谱 / 阿里 对比组", "default"),
                    ("空白：仅一个示例组，稍后自行编辑", "blank"),
                ],
                value="default",
                allow_blank=False,
                id="wizard-template",
            )
            yield Label("美元 → 人民币汇率", classes="wizard-field")
            yield Input(value="6.71", id="wizard-rate")
            yield Static(f"配置将写入：{self._target}", id="wizard-path")
            with Horizontal(classes="wizard-actions"):
                yield Button("取消", id="cancel", variant="default")
                yield Button("生成并进入", id="generate", variant="primary")

    @on(Button.Pressed, "#cancel")
    def _on_cancel(self) -> None:
        self.dismiss("cancel")

    @on(Button.Pressed, "#generate")
    def _on_generate(self) -> None:
        rate_raw = self.query_one("#wizard-rate", Input).value.strip()
        try:
            rate = float(rate_raw)
        except ValueError:
            rate = 6.71

        template = self.query_one("#wizard-template", Select).value or "default"
        data = cfg.get_default_config() if template == "default" else cfg.get_blank_config()
        data.setdefault("exchange_rate", {})["usd_to_cny"] = rate

        cfg.save_config(data, self._target)
        self.dismiss("done")
