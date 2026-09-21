"""Textual 应用入口：全局配置、两段式数据加载、状态栏与首启向导编排。

外框遵循统一规范（见 AGENTS.md 第一部分）：无 Header / Footer，App 仅 yield 一个
底部 `#status`；看板即根屏（启动直接进数据视图）。键位：Ctrl+Q 任意退出、Ctrl+S 设置。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from . import core
from .config import config_exists, get_default_config_path


class StatusBar(Static):
    """底部状态栏：展示最近一次操作结果 / 进行中提示。"""


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

    def status(self, message: str, kind: str = "") -> None:
        try:
            bar = self.query_one("#status", StatusBar)
        except Exception:  # noqa: BLE001
            return
        bar.update_classes({"ok": kind == "ok", "warn": kind == "warn", "err": kind == "err"})
        bar.update(message)

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
        """两段式加载：先用 headline 价秒开界面，再拉端点补算期望价。

        OpenRouter 端点接口在走代理时动辄十几秒，先出图再补数据比长时间空等更好。
        耗时抓取放在 asyncio.to_thread 里（core 为同步阻塞），其进度日志经
        _log → call_from_thread 安全投回 UI 线程，无需自建队列+轮询。
        """
        self.status("🔄 第一阶段：拉取官方与 headline 价格…")
        try:
            config = await asyncio.to_thread(core.load_config, self.config_path)
            models = await asyncio.to_thread(core.fetch_openrouter_models)
            phase1 = await asyncio.to_thread(
                core.build_snapshot,
                self.config_path,
                log=self._log,
                endpoints_mode=core.ENDPOINTS_NONE,
                endpoints_cache={},
                or_models=models,
            )
        except Exception as exc:  # noqa: BLE001
            self.notify_err(f"❌ 加载失败：{type(exc).__name__}: {exc}")
            return

        if not phase1.pairs:
            self.status("❌ 没有可用数据（检查配置的 groups / 网络）", "err")
            return

        self.snapshot = phase1
        await self._render(final=False)

        # 第二阶段：并发拉取全部端点，重算期望价
        self.status("⏳ 已出图（最低价口径），正在补算期望价…", "warn")
        try:
            ids = core.config_or_model_ids(config)
            cache = await asyncio.to_thread(core.fetch_endpoints_many, ids, log=self._log)
            phase2 = await asyncio.to_thread(
                core.build_snapshot,
                self.config_path,
                log=self._log,
                endpoints_mode=core.ENDPOINTS_NONE,
                endpoints_cache=cache,
                or_models=models,
            )
        except Exception as exc:  # noqa: BLE001
            self.status(f"⚠️ 端点数据拉取失败，保留最低价视图：{type(exc).__name__}: {exc}", "warn")
            return

        self.snapshot = phase2
        await self._render(final=True)

    async def _render(self, *, final: bool) -> None:
        if self._dashboard is not None:
            await self._dashboard.rebuild(final=final)
