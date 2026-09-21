#!/usr/bin/env python3
"""
main.py — LLM 价格对比工具（Textual TUI）

启动即拉取 OpenRouter + 各官方来源价格并计算，随后展示：
  · 「总览」tab —— 各模型横向对比（官方价 / 最优 OR 价 / 场景成本节省）
  · 每个模型一个 tab —— 内部各 OpenRouter 版本价格对比、场景成本排名、供应商端点明细

数据抓取与计算全部在 core.py，本文件只负责界面。

用法：
    llm-price [config.yaml]

快捷键：
    r         重新拉取并计算        ctrl+s    打开设置页（增删改配置）
    [ / ]     上一个 / 下一个 tab   1..9      跳到第 N 个 tab     g  总览
    ↑ ↓ ← →   表格内移动光标（cell 光标，可移列）
    s         按当前光标列排序（等价于点击表头，再按反向）
    q         退出
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget

try:  # 兼容不同 Textual 版本中 NoMatches 的位置
    from textual.exceptions import NoMatches
except ImportError:  # pragma: no cover
    from textual.css.query import NoMatches
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    LoadingIndicator,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

try:
    from . import core
    from .config import config_exists, get_default_config_path
    from .settings_screen import SettingsScreen
    from .setup_wizard import SetupScreen
except ImportError:
    import core
    from config import config_exists, get_default_config_path
    from settings_screen import SettingsScreen
    from setup_wizard import SetupScreen

# 涨跌方向 dir(-1/0/1) → 颜色。这是「数据编码色」，刻意固定、不接入主题语义色：
# 它编码的是「相对官方价更便宜/更贵」这一数值含义，需在任意主题、截图、录屏下保持一致，
# 若随主题反而会让语义漂移。↑ / ↓ 箭头（见 core.compare_cell）另作非颜色的冗余编码，
# 因此红绿并非唯一区分手段（对色盲也友好）。
# 对比之下，状态栏的 ⏳ / ✅ / ❌ 属「UI 状态色」，走主题 $warning/$success/$error
# （见 app.tcss 里 #status.ok/.warn/.err），随主题变化。
DIR_COLOR: dict[int, str] = {-1: "#4ec96a", 0: "", 1: "#e88282"}

OVERVIEW_ID = "tab-overview"
TAB_ID_PREFIX = "tab-model-"


def model_tab_id(pair_index: int) -> str:
    return f"{TAB_ID_PREFIX}{pair_index}"


# --------------------------------------------------------------------------- #
# 通用控件
# --------------------------------------------------------------------------- #

def sort_key(cell: dict) -> tuple:
    """单元格排序键：数值排前、字符串排后，避免混合类型比较报错。"""
    value = cell.get("value")
    if isinstance(value, bool):
        return (0, float(value), "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    return (1, 0.0, str("" if value is None else value))


class CellText(Text):
    """带排序键的单元格文本。

    rich.Text 用 __slots__，实例不能挂任意属性；本子类**刻意不定义 __slots__**，
    于是获得 __dict__，可携带 ``_sort_value`` 让 DataTable 就地排序时取用
    （显示与排序解耦，无需在 widget 上另存行/列副本）。
    """


def as_cell(cell: dict) -> CellText:
    """core 的单元格 dict → 带颜色的富文本，并附带预排序键。"""
    text = CellText(cell["text"])
    style = DIR_COLOR.get(cell.get("dir", 0), "")
    if style:
        text.stylize(style)
    # 排序键随单元格一起进入 DataTable；sort 时取 values[index]._sort_value 比较。
    text._sort_value = sort_key(cell)  # type: ignore[attr-defined]
    return text


class Section(Static):
    """区块标题"""


class Hint(Static):
    """次级说明文字"""


class TabsHost(Widget):
    """承载 TabbedContent 的容器；刷新时整体替换其子树"""

    DEFAULT_CSS = """
    TabsHost {
        height: 1fr;
    }
    """


class SortTable(DataTable):
    """可排序数据表：点表头或按 s 键，用 DataTable.sort 就地重排，不重建 DOM。

    单元格用 as_cell 生成，携带 ``_sort_value`` 作为排序键，故排序不依赖
    表头显示文本，也不需要在本 widget 上另存行/列副本。
    """

    BINDINGS = [Binding("s", "sort_cursor_column", "按光标列排序", show=False)]

    def load(self, spec: dict) -> SortTable:
        """用 core.build_* 返回的 {headers, rows} 填充（一次性渲染）。"""
        self.clear(columns=True)
        self.add_columns(*spec["headers"])
        for row in spec["rows"]:
            self.add_row(*[as_cell(cell) for cell in row])
        self._sort_col: int | None = None
        self._sort_desc = False
        return self

    def sort_column(self, index: int | None) -> None:
        """按第 index 列排序；重复排同一列则反向。"""
        if index is None or index < 0 or index >= len(self.ordered_columns):
            return
        if self._sort_col == index:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col, self._sort_desc = index, False

        # 不指定 columns → key 回调收到整行 values 元组（顺序=添加列顺序），
        # 取第 index 列单元格的预排序键比较即可，绕开对 ColumnKey 的依赖。
        self.sort(key=lambda values: values[index]._sort_value, reverse=self._sort_desc)

    def action_sort_cursor_column(self) -> None:
        self.sort_column(self.cursor_column)


def make_table(spec: dict, *, fixed_columns: int = 0) -> SortTable:
    table = SortTable(classes="tbl", zebra_stripes=True, fixed_columns=fixed_columns)
    # cell 光标：↑↓←→ 可达任意列，配合 s 键实现「纯键盘也能选列排序」；
    # 冻结首列（fixed_columns）在 cell 模式下同样有效。
    table.cursor_type = "cell"
    return table.load(spec)


# --------------------------------------------------------------------------- #
# 页面装配
# --------------------------------------------------------------------------- #

def endpoints_of(snapshot: core.Snapshot, pair_index: int, version_index: int) -> list[core.EndpointRow]:
    pair = snapshot.pairs[pair_index]
    if version_index >= len(pair.versions):
        return []
    return pair.endpoints.get(pair.versions[version_index].model_id, [])


def build_overview_pane(snapshot: core.Snapshot) -> TabPane:
    children: list[Static | SortTable] = [
        Hint(
            f"汇率 1 USD = {snapshot.exchange_rate} CNY · headline 覆盖 "
            f"{snapshot.headline_count} 个模型 · 数据时间 "
            f"{snapshot.fetched_at.strftime('%H:%M:%S')} · "
            "节省 = 最优 OpenRouter 版本相对官方价的降幅"
            + ("  ⏳ 期望价计算中，当前为最低价估算" if snapshot.pending_expected else "")
        ),
        Section("📊 基础价横向对比（输入 + 输出 直算口径）"),
        make_table(core.build_overview_table(snapshot), fixed_columns=1),
    ]

    for scenario in snapshot.scenarios:
        name = scenario.get("name", "未命名场景")
        children.append(Section(f"💰 场景横向对比：{name}"))
        children.append(Hint(f"token 构成 → {core.scenario_ratio_str(scenario['tokens'])}"))
        children.append(
            make_table(core.build_cross_model_table(snapshot, name), fixed_columns=1)
        )

    if not snapshot.scenarios:
        children.append(Hint("（config.yaml 的 scenarios 为空，未生成场景横向对比）"))

    # tab 标题刻意不加 emoji：CJK/emoji 的双宽在不同终端实现不一，
    # 会影响 Textual 的 tab 宽度与下划线定位；emoji 只保留在正文（宽度错一点不碍事）。
    return TabPane(
        "总览",
        VerticalScroll(*children, classes="pane"),
        id=OVERVIEW_ID,
    )


def build_model_pane(snapshot: core.Snapshot, pair_index: int) -> TabPane:
    pair = snapshot.pairs[pair_index]
    children: list = []

    # 价格对比
    children.append(Section("📊 官方价 vs OpenRouter 各版本（¥/百万 token）"))
    children.append(make_table(core.build_comparison_table(pair), fixed_columns=1))

    legend: list[str] = []
    if any(v.strategy == "expected" for v in pair.versions):
        legend.append("* = 期望价（默认路由加权平均），无标记 = 最低价")
    legend.append("绿 = 低于官方价，红 = 高于官方价")
    if pair.missing:
        legend.append("⚠️ 未找到：" + "、".join(f"{n} ({i})" for n, i in pair.missing))
    for v in pair.versions:
        if v.note:
            legend.append(f"⚠️ {v.name}：{v.note}")
    children.append(Hint("  ·  ".join(legend)))

    # 场景成本排名
    for ranking in pair.scenarios:
        scenario = ranking.scenario
        name = scenario.get("name", "?")
        if ranking.skipped_reason:
            children.append(Section(f"💰 场景成本：{name}（跳过：{ranking.skipped_reason}）"))
            continue
        children.append(Section(f"💰 场景成本：{name}"))
        children.append(
            Hint(
                f"{scenario.get('description', '')}  ·  token 构成 → "
                f"{core.scenario_ratio_str(scenario['tokens'])}"
            )
        )
        children.append(
            make_table(
                core.build_scenario_table(ranking, core.official_cost(ranking)),
                fixed_columns=1,
            )
        )

    # 端点明细
    children.append(Section("🔌 供应商端点明细（点表头 / 按 s 可按价格、权重排序）"))
    if pair.versions:
        selector = Select(
            [(v.label, str(i)) for i, v in enumerate(pair.versions)],
            value="0",
            allow_blank=False,
            prompt="",
            classes="version-select",
        )
        children.append(Horizontal(Hint("版本："), selector, classes="select-row"))
        rows = endpoints_of(snapshot, pair_index, 0)
    else:
        rows = []
        children.append(Hint("（没有可展示的 OpenRouter 版本）"))

    if rows:
        children.append(make_table(core.build_endpoint_table(rows), fixed_columns=1))
    else:
        children.append(Hint("（无端点数据：该模型可能未上架或接口返回 404）"))
        children.append(make_table(core.build_endpoint_table([]), fixed_columns=1))

    return TabPane(
        pair.display_name,
        VerticalScroll(*children, classes="pane"),
        id=model_tab_id(pair_index),
    )


# --------------------------------------------------------------------------- #
# 应用
# --------------------------------------------------------------------------- #

class PriceCompareApp(App):
    """LLM 价格对比 TUI"""

    CSS_PATH = Path(__file__).parent / "app.tcss"
    TITLE = "LLM Price Compare"
    SUB_TITLE = "正在加载…"

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("r", "refresh", "刷新", priority=True),
        Binding("ctrl+s", "open_settings", "设置", priority=True),
        Binding("[", "prev_tab", "上页", priority=True),
        Binding("]", "next_tab", "下页", priority=True),
        Binding("g", "goto_overview", "总览", priority=True),
    ] + [
        Binding(str(n), f"goto_tab({n - 1})", show=False, priority=True) for n in range(1, 10)
    ]

    def __init__(self, config_path: str | None = None) -> None:
        super().__init__()
        self.config_path = config_path
        self.snapshot: core.Snapshot | None = None
        self._tab_ids: list[str] = [OVERVIEW_ID]
        self._active_tab: str = OVERVIEW_ID

    # ---------------- 生命周期 ----------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield TabsHost(
            VerticalScroll(
                LoadingIndicator(),
                Hint("📡 正在拉取官方与 OpenRouter 价格并计算…"),
                id="loading",
            ),
            id="tabs-host",
        )
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.bootstrap()

    @work(exclusive=True)
    async def bootstrap(self) -> None:
        """启动流程：缺配置先走向导；选「空白」则接着打开引导式设置页，再加载数据。"""
        target = self.config_path or str(get_default_config_path())
        self.config_path = target
        if not config_exists(target):
            self._status("📭 未发现配置，正在启动配置向导…")
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
                    self._status(f"⚠️ 设置页初始化失败：{type(exc).__name__}: {exc}", "warn")
        self.load_data()


    # ---------------- 设置页 ----------------

    def action_open_settings(self) -> None:
        if isinstance(self.screen_stack[-1], SettingsScreen):
            return
        target = self.config_path or str(get_default_config_path())
        if not config_exists(target):
            self._status("请先完成初始配置", "warn")
            return
        try:
            cfg = core.load_config(target)
        except Exception as exc:  # noqa: BLE001
            self._status(f"❌ 配置读取失败：{type(exc).__name__}: {exc}", "err")
            return
        self.push_screen(SettingsScreen(cfg, target), self._on_settings_closed)

    def _on_settings_closed(self, saved: bool) -> None:
        if saved:
            self._status("💾 配置已保存，正在重新抓取…", "ok")
            self.load_data()

    # ---------------- 数据加载 ----------------

    @work(exclusive=True)
    async def load_data(self) -> None:
        """两段式加载：先用 headline 价秒开界面，再拉端点补算期望价。

        OpenRouter 端点接口在走代理时动辄十几秒，先出图再补数据比长时间空等更好。
        耗时抓取放在 asyncio.to_thread 里（core 为同步阻塞），其进度日志经
        _log → call_from_thread 安全投回 UI 线程，无需自建队列+轮询。
        """
        self._status("🔄 第一阶段：拉取官方与 headline 价格…")
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
            self._status(f"❌ 加载失败：{type(exc).__name__}: {exc}", "err")
            return

        if not phase1.pairs:
            self._status("❌ 没有可用数据（检查配置的 groups / 网络）", "err")
            return

        self.snapshot = phase1
        await self._rebuild(final=False)

        # 第二阶段：并发拉取全部端点，重算期望价
        self._status("⏳ 已出图（最低价口径），正在补算期望价…", "warn")
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
            self._status(f"⚠️ 端点数据拉取失败，保留最低价视图：{type(exc).__name__}: {exc}", "warn")
            return

        self.snapshot = phase2
        await self._rebuild(final=True)

    async def _rebuild(self, *, final: bool = True) -> None:
        """重建整个 TabbedContent。

        说明（版本相关，升级后应回归一次）：Textual 8.2.8 里动态
        ``clear_panes()`` + ``add_pane()`` 之后，``tabs.active`` 会被一条排队的
        ``TabActivated`` 消息回滚，导致程序化切页失效（经静态 compose 对照确认是
        库问题，非本程序逻辑）。因此这里采用「一次成型 + 整体替换子树」的写法，
        与静态 compose 行为一致，可保持当前活动页。若升级到修复了该行为的版本，
        这段可简化为直接 add_pane/remove_pane。
        """
        snapshot = self.snapshot
        assert snapshot is not None
        host = self.query_one("#tabs-host", TabsHost)
        await host.remove_children()

        panes = [build_overview_pane(snapshot)]
        panes += [build_model_pane(snapshot, i) for i in range(len(snapshot.pairs))]
        self._tab_ids = [pane.id or "" for pane in panes]

        initial = self._active_tab if self._active_tab in self._tab_ids else OVERVIEW_ID
        # TabbedContent 的位参是「标题」而非 pane；程序式构建走 compose_add_child
        # （与 `with TabbedContent():` 语法同一入口）。
        tabs = TabbedContent(initial=initial, id="tabs")
        for pane in panes:
            tabs.compose_add_child(pane)
        await host.mount(tabs)
        self._active_tab = initial

        self.sub_title = (
            f"{len(snapshot.pairs)} 个模型 · "
            f"{sum(len(p.versions) for p in snapshot.pairs)} 个 OR 版本 · "
            f"汇率 {snapshot.exchange_rate} · "
            f"{snapshot.fetched_at.strftime('%H:%M:%S')}"
        )
        if final and not snapshot.pending_expected:
            self._status(
                f"✅ 就绪 · {snapshot.headline_count} 个模型价 · r 刷新 · [ ] 切页",
                "ok",
            )
        else:
            self._status("⏳ 已显示最低价视图 · 期望价计算中…", "warn")

        self._focus_active_pane()

    def _focus_active_pane(self) -> None:
        """把焦点给当前页的第一张表"""
        try:
            pane = self.query_one(f"#{self._active_tab}", TabPane)
        except NoMatches:
            return
        for table in pane.query(SortTable):
            table.focus()
            break

    # ---------------- 状态栏 ----------------

    def _log(self, message: str) -> None:
        """core 的进度回调：运行在 to_thread 的工作线程里，经 call_from_thread 投回 UI。"""
        self.call_from_thread(self._status, f"📡 {message}")

    def _status(self, message: str, tone: str = "") -> None:
        """更新底部状态栏。tone ∈ {"", "ok", "warn", "err"} 走主题语义色（UI 状态色）。"""
        try:
            status = self.query_one("#status", Static)
            status.remove_class("ok", "warn", "err")
            if tone:
                status.add_class(tone)
            status.update(message)
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 事件 ----------------

    @on(DataTable.HeaderSelected, ".tbl")
    def _header_clicked(self, event: DataTable.HeaderSelected) -> None:
        table = event.control
        table.sort_column(event.column_index)
        table.focus()

    @on(Select.Changed, ".version-select")
    def _version_changed(self, event: Select.Changed) -> None:
        if self.snapshot is None or event.value is Select.NULL:
            return
        select = event.control
        # 从所在 TabPane 的 id（"tab-model-<i>"）反解 pair_index，
        # 不再往 Select 实例上挂私有属性（跨版本更稳）。
        pane = select.query_ancestor(TabPane)
        if pane is None or not pane.id or not pane.id.startswith(TAB_ID_PREFIX):
            return
        try:
            pair_index = int(pane.id[len(TAB_ID_PREFIX):])
        except ValueError:
            return
        rows = endpoints_of(self.snapshot, pair_index, int(str(event.value)))
        tables = list(pane.query(SortTable))
        if tables:
            tables[-1].load(core.build_endpoint_table(rows))

    # ---------------- Actions ----------------

    def action_refresh(self) -> None:
        self.load_data()

    def action_goto_overview(self) -> None:
        self._activate_tab(0)

    def action_goto_tab(self, index: int) -> None:
        self._activate_tab(index)

    def action_next_tab(self) -> None:
        self._activate_tab(self._current_tab_index() + 1)

    def action_prev_tab(self) -> None:
        self._activate_tab(self._current_tab_index() - 1)

    def _current_tab_index(self) -> int:
        try:
            active = self.query_one("#tabs", TabbedContent).active
        except NoMatches:
            return 0
        try:
            return self._tab_ids.index(active)
        except ValueError:
            return 0

    def _activate_tab(self, index: int) -> None:
        if not self._tab_ids:
            return
        try:
            tabs = self.query_one("#tabs", TabbedContent)
        except NoMatches:
            return
        index = max(0, min(index, len(self._tab_ids) - 1))
        tab_id = self._tab_ids[index]
        tabs.active = tab_id
        self._active_tab = tab_id
        self._focus_active_pane()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="llm-price", description="LLM 价格对比 TUI（启动即拉取并计算）"
    )
    parser.add_argument("config", nargs="?", default=None, help="配置文件路径（缺省自动使用全局或当前目录配置）")
    args = parser.parse_args()

    config_path = args.config
    if config_path is None:
        # 优先当前目录 config.yaml；否则用用户全局配置（是否创建交给首次启动向导）
        local_cfg = Path("config.yaml")
        config_path = str(local_cfg) if local_cfg.exists() else str(get_default_config_path())

    PriceCompareApp(config_path).run()


if __name__ == "__main__":
    main()
