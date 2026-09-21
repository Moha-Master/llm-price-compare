"""看板屏（根屏）：总览 tab + 每个对比组一个 tab，纵向堆叠多张可排序表格。

保留本项目特色的「多维比价看板」：启动即看数据、`[`/`]`/`1-9`/`g` 切页、
`←→` 选列 + `s` 排序（cell 光标）。外框、键位、模态则对齐统一规范。
"""
from __future__ import annotations

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from .. import core
from ..ui import PageScreen

# 涨跌方向 dir(-1/0/1) → 颜色。这是「数据编码色」，刻意固定、不接入主题语义色：
# 它编码「相对官方价更便宜/更贵」的数值含义，需在任意主题、截图下保持一致；
# ↑ / ↓ 箭头（见 core.compare_cell）另作非颜色冗余编码，故对色盲也友好。
# 对比之下状态栏的 ⏳ / ✅ / ❌ 属「UI 状态色」，走主题 $warning/$success/$error。
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
        ),
        Section("📊 基础价横向对比（输入 + 输出 直算口径）"),
        make_table(core.build_overview_table(snapshot), fixed_columns=1),
    ]

    for scenario in snapshot.scenarios:
        name = scenario.get("name", "未命名场景")
        children.append(Section(f"💰 场景横向对比：{name}"))
        children.append(Hint(f"token 构成 → {core.scenario_ratio_str(scenario['tokens'])}"))
        children.append(make_table(core.build_cross_model_table(snapshot, name), fixed_columns=1))

    if not snapshot.scenarios:
        children.append(Hint("（config.yaml 的 scenarios 为空，未生成场景横向对比）"))

    # tab 标题刻意不加 emoji：CJK/emoji 的双宽在不同终端实现不一，会影响 tab 宽度与下划线定位。
    return TabPane("总览", VerticalScroll(*children, classes="pane"), id=OVERVIEW_ID)


def build_model_pane(snapshot: core.Snapshot, pair_index: int) -> TabPane:
    pair = snapshot.pairs[pair_index]
    children: list = []

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
            make_table(core.build_scenario_table(ranking, core.official_cost(ranking)), fixed_columns=1)
        )

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

    return TabPane(pair.display_name, VerticalScroll(*children, classes="pane"), id=model_tab_id(pair_index))


# --------------------------------------------------------------------------- #
# 看板屏
# --------------------------------------------------------------------------- #

class DashboardScreen(PageScreen):
    """多维比价看板：承载 TabbedContent，两段式渲染由 App 回调 rebuild()。"""

    TITLE = "LLM 价格对比"
    BACK_LABEL = "◀ 退出"
    HINT = "[ ] 切页 · g 总览 · 1-9 直达 · ←→ 选列 · s 排序 · Ctrl+R 刷新 · Ctrl+S 设置 · Esc/Ctrl+C 退出"

    BINDINGS = PageScreen.BINDINGS + [
        Binding("[", "prev_tab", "上页", priority=True),
        Binding("]", "next_tab", "下页", priority=True),
        Binding("g", "goto_overview", "总览", priority=True),
    ] + [Binding(str(n), f"goto_tab({n - 1})", show=False, priority=True) for n in range(1, 10)]

    def __init__(self) -> None:
        super().__init__()
        self._tab_ids: list[str] = [OVERVIEW_ID]
        self._active: str = OVERVIEW_ID
        self._rebuilding = False

    # ------------------------------------------------------------ 组合

    def compose_toolbar(self):
        yield Button("🔄 刷新", id="tb-refresh")
        yield Button("⚙️ 设置", id="tb-settings")

    def compose_page(self):
        yield TabsHost(id="tabs-host")

    def on_mount(self) -> None:
        self.app._dashboard = self
        if self.app.snapshot is None:
            # 看板就绪后再触发首次抓取（此时 _dashboard 已回填，_render 回调有效）。
            self.app.load_data()
        else:
            self.call_after_refresh(self._kick_rebuild)

    def _kick_rebuild(self) -> None:
        self.run_worker(self.rebuild(final=True), exclusive=True)

    # ------------------------------------------------------------ 渲染

    async def rebuild(self, *, final: bool = True) -> None:
        """重建整个 TabbedContent（一次成型 + 整体替换子树，保持当前活动页）。

        说明（版本相关，升级后应回归一次）：Textual 8.2.8 里动态 clear_panes()+add_pane()
        之后 tabs.active 会被一条排队的 TabActivated 回滚，导致程序化切页失效，故整体替换。
        这里再加 `inflight` 互斥，防止两段式加载的 remove/mount 与自身回调整齐重入。
        """
        snapshot = self.app.snapshot
        if snapshot is None or self._rebuilding:
            return
        self._rebuilding = True
        try:
            host = self.query_one("#tabs-host", TabsHost)
            await host.remove_children()

            panes = [build_overview_pane(snapshot)]
            panes += [build_model_pane(snapshot, i) for i in range(len(snapshot.pairs))]
            self._tab_ids = [pane.id or "" for pane in panes]

            initial = self._active if self._active in self._tab_ids else OVERVIEW_ID
            tabs = TabbedContent(initial=initial, id="tabs")
            for pane in panes:
                tabs.compose_add_child(pane)
            await host.mount(tabs)
            self._active = initial

            self.set_subtitle(
                f"{len(snapshot.pairs)} 个模型 · "
                f"{sum(len(p.versions) for p in snapshot.pairs)} 个 OR 版本 · "
                f"汇率 {snapshot.exchange_rate} · {snapshot.fetched_at.strftime('%H:%M:%S')}"
            )
            self.app.status(
                f"✅ 就绪 · {snapshot.headline_count} 个模型价 · Ctrl+R 刷新 · [ ] 切页",
                "ok",
            )

            self._focus_active_pane()
        finally:
            self._rebuilding = False

    def _focus_active_pane(self) -> None:
        """把焦点给当前页的第一张表"""
        try:
            pane = self.query_one(f"#{self._active}", TabPane)
        except NoMatches:
            return
        for table in pane.query(SortTable):
            table.focus()
            break

    # ------------------------------------------------------------ 根屏返回 = 退出

    def action_page_back(self) -> None:
        self.app.exit()

    def reload_page(self) -> None:
        self.app.load_data()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tb-refresh":
            self.reload_page()
        elif event.button.id == "tb-settings":
            self.app.run_action("open_settings")
        else:
            super().on_button_pressed(event)

    # ------------------------------------------------------------ 事件

    @on(DataTable.HeaderSelected, ".tbl")
    def _header_clicked(self, event: DataTable.HeaderSelected) -> None:
        table = event.control
        table.sort_column(event.column_index)
        table.focus()

    @on(Select.Changed, ".version-select")
    def _version_changed(self, event: Select.Changed) -> None:
        snapshot = self.app.snapshot
        if snapshot is None or event.value is Select.NULL:
            return
        select = event.control
        pane = select.query_ancestor(TabPane)
        if pane is None or not pane.id or not pane.id.startswith(TAB_ID_PREFIX):
            return
        try:
            pair_index = int(pane.id[len(TAB_ID_PREFIX):])
        except ValueError:
            return
        rows = endpoints_of(snapshot, pair_index, int(str(event.value)))
        tables = list(pane.query(SortTable))
        if tables:
            tables[-1].load(core.build_endpoint_table(rows))

    # ------------------------------------------------------------ Tab 动作

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
        self._active = tab_id
        self._focus_active_pane()
