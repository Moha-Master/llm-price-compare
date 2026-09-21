"""Textual 应用入口：全局配置、一次性数据加载（带确定式进度）、状态栏与首启向导编排。

外框遵循统一规范（见 AGENTS.md 第一部分）：无 Header / Footer，App 仅 yield 一个
底部 `#status`；看板即根屏（启动直接进数据视图）。键位：Ctrl+Q 任意退出、Ctrl+S 设置。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from rich.spinner import SPINNERS
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Static

from . import core
from .config import config_exists, get_default_config_path
from .widgets import ProgressCover, busy

_DOTS = SPINNERS["dots"]


class StatusBar(Static):
    """底部状态栏：展示最近一次操作结果 / 进行中提示；spinner=True 时显示点阵转圈。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._text = ""
        self._busy = False
        self._frame = 0
        self._timer = None

    def render(self) -> Text:
        if self._busy:
            glyph = _DOTS["frames"][self._frame % len(_DOTS["frames"])]
            return Text.assemble((glyph, "bold"), " ", self._text)
        return Text(self._text)

    def set_status(self, text: str) -> None:
        self._busy = False
        self._text = text
        self._stop_timer()
        self.refresh()

    def set_spinner(self, text: str) -> None:
        self._busy = True
        self._text = text
        self._ensure_timer()
        self.refresh()

    def _ensure_timer(self) -> None:
        if self._timer is None and self.is_mounted:
            self._timer = self.set_interval(_DOTS["interval"] / 1000, self._tick)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._frame += 1
        self.refresh()

    def on_mount(self) -> None:
        self._ensure_timer()


class PriceCompareApp(App):
    """LLM 价格对比 TUI。"""

    CSS_PATH = Path(__file__).parent / "app.tcss"
    TITLE = "LLM Price Compare"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+q", "quit", "退出", priority=True),
        Binding("ctrl+s", "open_settings", "设置", priority=True),
    ]

    def __init__(self, config_path: str | None = None) -> None:
        super().__init__()
        self.config_path = config_path
        self.snapshot: core.Snapshot | None = None
        self._dashboard = None  # 看板挂载后回填，供数据加载完成时回调刷新

    # ------------------------------------------------------------ 状态栏 / 提示

    def compose(self) -> ComposeResult:
        yield StatusBar("", id="status")

    def get_loading_widget(self) -> Widget:
        """全局默认：任意控件 .loading=True 时用 indeterminate 进度条覆盖其区域。"""
        return ProgressCover()

    def status(self, message: str, kind: str = "") -> None:
        try:
            bar = self.query_one("#status", StatusBar)
        except Exception:  # noqa: BLE001
            return
        bar.update_classes({"ok": kind == "ok", "warn": kind == "warn", "err": kind == "err"})
        bar.set_status(message)

    def spinner(self, on: bool, message: str = "加载中…") -> None:
        """状态栏点阵 spinner（无遮罩、不阻断输入）。"""
        try:
            bar = self.query_one("#status", StatusBar)
        except Exception:  # noqa: BLE001
            return
        bar.update_classes({})
        if on:
            bar.set_spinner(message)
        else:
            bar.set_status("")

    def notify_ok(self, message: str) -> None:
        self.status(message, "ok")
        self.notify(message, severity="success", timeout=4)

    def notify_err(self, message: str) -> None:
        self.status(message, "err")
        self.notify(message, severity="error", timeout=8)

    def notify_warn(self, message: str) -> None:
        self.status(message, "warn")
        self.notify(message, severity="warning", timeout=5)

    def _log(self, message: str) -> None:
        """core 的进度回调：运行在工作线程里，经 call_from_thread 投回 UI 线程。"""
        self.call_from_thread(self.status, f"📡 {message}")

    # ------------------------------------------------------------ 启动

    def on_mount(self) -> None:
        self._bootstrap()

    @work(exclusive=True)
    async def _bootstrap(self) -> None:
        from .screens.dashboard import DashboardScreen
        from .screens.settings import SettingsScreen
        from .screens.setup import SetupScreen

        target = self.config_path or str(get_default_config_path())
        self.config_path = target
        if not config_exists(target):
            self.status("📭 未发现配置，正在启动配置向导…", "warn")
            result = await self.push_screen_wait(SetupScreen(target))
            if result in (None, "cancel"):
                self.exit()
                return
            if result == "blank":
                # 空白模板：复用设置页的「对比组」并附引导文本，让用户亲手建第一个组
                try:
                    cfg = core.load_config(target)
                    await self.push_screen_wait(SettingsScreen(cfg, target, guide=True))
                except Exception as exc:  # noqa: BLE001
                    self.status(f"⚠️ 设置页初始化失败：{type(exc).__name__}: {exc}", "warn")
        # 看板挂载后再由 DashboardScreen.on_mount 触发首次 load_data，
        # 避免 push_screen 与 load_data 的 rebuild 竞态（8.2.8 ContentTabs 双挂会崩）。
        self.push_screen(DashboardScreen())

    # ------------------------------------------------------------ 设置页

    def action_open_settings(self) -> None:
        from .screens.settings import SettingsScreen

        if isinstance(self.screen_stack[-1], SettingsScreen):
            return
        target = self.config_path or str(get_default_config_path())
        if not config_exists(target):
            self.status("请先完成初始配置", "warn")
            return
        try:
            cfg = core.load_config(target)
        except Exception as exc:  # noqa: BLE001
            self.status(f"❌ 配置读取失败：{type(exc).__name__}: {exc}", "err")
            return
        self.push_screen(SettingsScreen(cfg, target), self._on_settings_closed)

    def _on_settings_closed(self, saved: bool) -> None:
        if saved:
            self.status("💾 配置已保存，正在重新抓取…", "ok")
            self.load_data()

    # ------------------------------------------------------------ 数据加载

    @work(exclusive=True)
    async def load_data(self) -> None:
        """一次性加载：并发抓取全部端点，用确定式进度条反馈（模型总数先验已知），完成后单次渲染。

        耗时抓取放在 asyncio.to_thread（core 为同步阻塞）；每个模型完成时经
        on_done → call_from_thread 推进全屏遮罩内的进度条，无需自建队列 / 轮询。
        """
        try:
            config = await asyncio.to_thread(core.load_config, self.config_path)
        except Exception as exc:  # noqa: BLE001
            self.notify_err(f"❌ 配置读取失败：{type(exc).__name__}: {exc}")
            return
        ids = core.config_or_model_ids(config)
        total = len(ids)

        try:
            async with busy(
                self, "📡 正在拉取端点数据", mode="percent" if total else "bar", total=total
            ) as ov:
                def _on_done() -> None:  # 由 core 的抓取线程调用，投回 UI 线程推进进度
                    self.call_from_thread(ov.advance)

                models, cache = await asyncio.to_thread(
                    self._fetch_all, ids, _on_done if total else None
                )
                snapshot = await asyncio.to_thread(
                    core.build_snapshot,
                    self.config_path,
                    log=self._log,
                    endpoints_mode=core.ENDPOINTS_NONE,
                    endpoints_cache=cache,
                    or_models=models,
                )
        except Exception as exc:  # noqa: BLE001
            self.notify_err(f"❌ 加载失败：{type(exc).__name__}: {exc}")
            return

        if not snapshot.pairs:
            self.status("❌ 没有可用数据（检查配置的 groups / 网络）", "err")
            return
        self.snapshot = snapshot
        await self._render(final=True)

    def _fetch_all(self, ids: list[str], on_done) -> tuple[dict, dict]:
        """在工作线程内完成 OpenRouter headline + 全部端点的抓取，返回 (models, endpoints_cache)。"""
        models = core.fetch_openrouter_models(log=self._log)
        cache = core.fetch_endpoints_many(ids, log=self._log, on_done=on_done) if ids else {}
        return models, cache

    async def _render(self, *, final: bool) -> None:
        if self._dashboard is not None:
            await self._dashboard.rebuild(final=final)
