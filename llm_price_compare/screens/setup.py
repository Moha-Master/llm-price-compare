"""首启配置向导（ModalScreen）：选择初始模板与汇率并写盘。

沿用统一模态三段式外观（`.modal-box` / `.modal-title` / `.modal-main` / `.btn-row`，
控件 compact、按钮全局单行）。返回 "cancel"（放弃）或所选模板名 "default" / "blank"。
"""
from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from .. import config as cfg


class SetupScreen(ModalScreen[str]):
    """返回 "cancel"（用户放弃）或所选模板名 "default" / "blank"（已写盘、请继续）。"""

    DEFAULT_CSS = """
    SetupScreen { align: center middle; }
    SetupScreen > .modal-box { width: 76; min-height: 24; }
    SetupScreen .wiz-desc { color: $text-muted; height: auto; margin-bottom: 1; }
    SetupScreen .wiz-label { height: 1; text-style: bold; margin-top: 1; }
    SetupScreen Select, SetupScreen Input { width: 1fr; margin-top: 0; }
    SetupScreen .wiz-path { color: $text-muted; height: auto; margin-top: 1; }
    SetupScreen .modal-main { height: 1fr; }
    """

    BINDINGS = [Binding("escape,ctrl+c", "cancel", show=False)]

    def __init__(self, target_path: str | Path | None = None) -> None:
        super().__init__()
        self._target = Path(target_path) if target_path else cfg.get_default_config_path()

    def compose(self):
        with Vertical(classes="modal-box"):
            yield Static(Text("👋  欢迎使用 LLM Price Compare", style="bold"), classes="modal-title")
            with VerticalScroll(classes="modal-main"):
                yield Static(
                    "首次运行需要先创建一份配置文件。你可以直接套用推荐的对比组，\n"
                    "或从空白开始，稍后再编辑。所有价格都会在运行时自动抓取。",
                    classes="wiz-desc",
                )
                yield Label("初始配置模板", classes="wiz-label")
                yield Select(
                    [
                        ("推荐：内置 DeepSeek / 小米 / 智谱 / 阿里 对比组", "default"),
                        ("空白：进入后引导你在设置页添加第一个对比组", "blank"),
                    ],
                    value="default",
                    allow_blank=False,
                    compact=True,
                    id="wiz-template",
                )
                yield Label("美元 → 人民币汇率", classes="wiz-label")
                yield Input(value="6.71", compact=True, id="wiz-rate")
                yield Static(f"配置将写入：{self._target}", classes="wiz-path")
            with Horizontal(classes="btn-row"):
                yield Button("取消", id="cancel", variant="default")
                yield Button("生成并进入", id="generate", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss("cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss("cancel")
            return
        if event.button.id != "generate":
            return
        rate_raw = self.query_one("#wiz-rate", Input).value.strip()
        try:
            rate = float(rate_raw)
        except ValueError:
            rate = 6.71

        template = self.query_one("#wiz-template", Select).value or "default"
        data = cfg.get_default_config() if template == "default" else cfg.get_blank_config()
        data.setdefault("exchange_rate", {})["usd_to_cny"] = rate

        cfg.save_config(data, self._target)
        self.dismiss(str(template))
