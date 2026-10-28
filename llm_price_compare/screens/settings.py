"""设置页（全屏 PageScreen）：汇率 / 场景 / 对比组与模型的可视化增删改。

统一规范落地：
- 重命名 → widgets.InputModal；模型新增 / 编辑 → widgets.FormModal 子类（定价策略随来源动态刷新）；
  删除组 / 模型 → widgets.ConfirmModal（危险项默认不回车放行）。
- 列表用 widgets.ClickTable(activate="click")：单击 = 选择（编辑仍由按钮 / 回车执行）。
- 未保存修改时返回（Esc / ◀ 返回 / 放弃）会先确认。
"""
from __future__ import annotations

import copy
from pathlib import Path

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, Label, Select, Static, TabbedContent, TabPane

from .. import config as cfg
from ..ui import PageScreen
from ..widgets import ClickTable, ConfirmModal, FormField, FormModal, InputModal

TOKEN_ROWS: list[tuple[str, str]] = [
    ("cache_read", "缓存读"),
    ("cache_write", "缓存写"),
    ("input", "输入"),
    ("output", "输出"),
]


def _frac_to_pct(frac: object) -> str:
    """0.85 → '85%'（去掉浮点尾零）。"""
    try:
        return f"{float(frac) * 100:g}%"
    except (TypeError, ValueError):
        return "0%"


def _pct_to_frac(raw: str) -> float:
    """'85%' / '85' → 0.85；无法解析按 0。"""
    s = raw.strip().replace("％", "%").replace("%", "").strip()
    if not s:
        return 0.0
    try:
        return float(s) / 100.0
    except ValueError:
        return 0.0


class ModelFormModal(FormModal):
    """新增 / 编辑单个模型条目；定价策略下拉随来源类型动态刷新。"""

    def __init__(self, model: dict | None = None) -> None:
        m = dict(model) if model else {}
        mtype = m.get("type", "openrouter")
        values = [v for v, _ in cfg.pricing_strategies_for(mtype)]
        cur_pricing = m.get("pricing") or cfg.default_pricing(mtype)
        if cur_pricing not in values:
            cur_pricing = values[0] if values else cur_pricing
        fields = [
            FormField("name", "显示名称", value=m.get("name", ""), placeholder="如 DeepSeek 官方"),
            FormField("id", "模型 ID", value=m.get("id", ""), placeholder="官方 id 或 provider/name"),
            FormField("type", "定价来源", kind="choice", value=mtype, options=[(t, t) for t in cfg.PROVIDER_TYPES]),
            FormField(
                "pricing",
                "定价策略",
                kind="choice",
                value=cur_pricing,
                options=[(label, value) for value, label in cfg.pricing_strategies_for(mtype)],
            ),
        ]
        super().__init__("编辑模型" if m else "添加模型", fields, ok_label="确定")

    @on(Select.Changed, "#se-type")
    def _type_changed(self) -> None:
        newt = self.query_one("#se-type", Select).value
        if not newt:
            return
        opts = cfg.pricing_strategies_for(str(newt))
        sel = self.query_one("#se-pricing", Select)
        sel.set_options([(label, value) for value, label in opts])
        vals = [v for v, _ in opts]
        d = cfg.default_pricing(str(newt))
        sel.value = d if d in vals else (vals[0] if vals else Select.NULL)


class SettingsScreen(PageScreen):
    """保存后 dismiss(True)，主界面据此热刷新。guide=True 为首次空白引导。"""

    TITLE = "设置"
    SUBTITLE = ""
    HINT = "↑↓ 选择 · 回车 编辑 · Tab 切焦点 · Ctrl+S 保存 · Esc/Ctrl+C 放弃返回"

    DEFAULT_CSS = """
    SettingsScreen #settings-body { height: 1fr; }
    SettingsScreen #group-body { height: 1fr; }
    SettingsScreen .field-label { margin-top: 1; padding-top: 1; }
    SettingsScreen .tab-hint { padding: 1 0; color: $text-muted; }
    SettingsScreen #rate { width: 24; }

    SettingsScreen .scenario-row { margin-bottom: 1; height: auto; align-vertical: middle; }
    SettingsScreen .scenario-row Input.sc-name { width: 18; margin-left: 0; }
    SettingsScreen .scenario-row Label { margin-left: 1; }
    SettingsScreen .scenario-row Input.sc-pct { width: 8; margin-left: 0; }
    SettingsScreen .scenario-row Button.sc-del { margin-left: 1; }

    SettingsScreen .group-side { width: 34; padding-right: 1; }
    SettingsScreen .group-side #group-table { height: 1fr; }
    SettingsScreen .grp-btns { height: auto; margin-top: 1; }
    SettingsScreen .grp-btns Button { margin-right: 1; }
    SettingsScreen .mini-hint { color: $text-muted; padding-top: 1; }

    SettingsScreen #group-editor { width: 1fr; padding-left: 2; }
    SettingsScreen #group-guide { border: round $success; padding: 1 2; margin-bottom: 1; background: $panel; }
    SettingsScreen #models-table { height: auto; margin-top: 1; }
    SettingsScreen .row-actions { height: auto; margin-top: 1; }
    SettingsScreen .row-actions Button { margin-right: 1; }

    SettingsScreen .settings-actions { height: auto; margin-top: 1; align-horizontal: right; }
    SettingsScreen .settings-actions Button { margin-left: 2; }
    """

    def __init__(
        self, config: dict, target_path: str | Path | None = None, *, guide: bool = False
    ) -> None:
        super().__init__()
        self._config = copy.deepcopy(config)
        self._config_orig = copy.deepcopy(config)
        self._target = Path(target_path) if target_path else cfg.get_default_config_path()
        self._group_index = 0
        self._edit_index = -1
        self._rename_target = -1
        self._guide = guide

    # ---------------- 结构 ----------------

    def compose_page(self):
        with TabbedContent(id="settings-body"):
            with TabPane("常规", id="tab-general"):
                with VerticalScroll(classes="pane"):
                    yield Label("美元 → 人民币汇率", classes="field-label")
                    yield Input(id="rate")
            with TabPane("场景", id="tab-scenario"):
                with VerticalScroll(classes="pane"):
                    yield Static(
                        "各 token 类型占比（百分比），四项相加应为 100%。用于场景成本估算。",
                        classes="tab-hint",
                    )
                    yield VerticalScroll(id="scenario-list")
                    yield Button("＋ 添加场景", id="add-scenario", variant="default")
            with TabPane("对比组", id="tab-group"):
                with Horizontal(id="group-body"):
                    with Vertical(classes="group-side"):
                        yield Label("对比组")
                        yield ClickTable(id="group-table", cursor_type="row", classes="", activate="click")
                        with Horizontal(classes="grp-btns"):
                            yield Button("＋ 新建", id="add-group")
                            yield Button("✎ 重命名", id="rename-group")
                            yield Button("🗑 删除", id="del-group", variant="error")
                        yield Static("单击切换 · 回车 / 重命名按钮改名", classes="mini-hint")
                    with VerticalScroll(id="group-editor", classes="pane"):
                        if self._guide:
                            yield Static(
                                "👋 欢迎！还没有对比组。点左侧「＋ 新建」创建第一个对比组，\n"
                                "再在右侧「添加模型」加入要互相比较的模型（同一模型的不同来源，\n"
                                "如官方直连 + OpenRouter）。配好后点右下角「保存」即可自动抓取价格。",
                                id="group-guide",
                            )
                        yield Label("模型条目（单击选择，回车 / 编辑按钮修改）", classes="field-label")
                        yield ClickTable(id="models-table", cursor_type="row", classes="", activate="click")
                        with Horizontal(classes="row-actions"):
                            yield Button("＋ 添加模型", id="add-model")
                            yield Button("✎ 编辑模型", id="edit-model")
                            yield Button("🗑 删除模型", id="del-model", variant="error")
        with Horizontal(classes="settings-actions"):
            yield Button("放弃", id="btn-cancel", variant="default")
            yield Button("💾 保存", id="btn-save", variant="primary")

    async def on_mount(self) -> None:
        self.set_subtitle(str(self._target))
        rate = self._config.get("exchange_rate", {}).get("usd_to_cny", 6.71)
        self.query_one("#rate", Input).value = str(rate)

        gtable = self.query_one("#group-table", DataTable)
        gtable.cursor_type = "row"
        gtable.add_columns("#", "组名")

        mtable = self.query_one("#models-table", DataTable)
        mtable.cursor_type = "row"
        mtable.add_columns("名称", "ID", "来源", "策略")

        await self._rebuild_scenarios()
        self._refresh_group_table()
        self._load_group()

        if self._guide:
            self.query_one("#settings-body", TabbedContent).active = "tab-group"

    # ---------------- 场景 ----------------

    async def _rebuild_scenarios(self) -> None:
        box = self.query_one("#scenario-list")
        await box.remove_children()
        rows: list[Horizontal] = []
        for idx, sc in enumerate(self._config.get("scenarios", [])):
            tokens = sc.get("tokens", {})
            children: list = [Input(placeholder="场景名", value=sc.get("name", ""), classes="sc-name", compact=True)]
            for key, label in TOKEN_ROWS:
                children.append(Label(label))
                children.append(Input(value=_frac_to_pct(tokens.get(key, 0)), classes=f"sc-pct sc-{key}", compact=True))
            children.append(Button("🗑", classes="sc-del", id=f"sc-del-{idx}", variant="error"))
            rows.append(Horizontal(*children, classes="scenario-row"))
        if rows:
            await box.mount(*rows)

    @on(Button.Pressed, "#add-scenario")
    async def _add_scenario(self) -> None:
        self._commit_scenarios()
        self._config.setdefault("scenarios", []).append(
            {
                "name": "新场景",
                "tokens": {"cache_read": 0.7, "cache_write": 0.1, "input": 0.15, "output": 0.05},
            }
        )
        await self._rebuild_scenarios()

    @on(Button.Pressed, ".sc-del")
    async def _del_scenario(self, event: Button.Pressed) -> None:
        self._commit_scenarios()
        try:
            idx = int((event.button.id or "").rsplit("-", 1)[-1])
        except ValueError:
            idx = None
        scenarios = self._config.get("scenarios", [])
        if idx is not None and 0 <= idx < len(scenarios):
            scenarios.pop(idx)
        await self._rebuild_scenarios()

    def _commit_scenarios(self) -> None:
        scenarios = []
        for row in self.query(".scenario-row"):
            name = row.query_one(".sc-name", Input).value.strip()
            tokens = {}
            for key, _label in TOKEN_ROWS:
                tokens[key] = _pct_to_frac(row.query_one(f".sc-{key}", Input).value)
            scenarios.append({"name": name or "未命名", "tokens": tokens})
        self._config["scenarios"] = scenarios

    # ---------------- 对比组列表 ----------------

    def _refresh_group_table(self) -> None:
        groups = self._config.get("groups", [])
        self._group_index = max(0, min(self._group_index, len(groups) - 1)) if groups else 0
        table = self.query_one("#group-table", DataTable)
        table.clear()
        for i, g in enumerate(groups):
            label = g.get("display_name", "(未命名)") or "(未命名)"
            table.add_row(str(i + 1), label, key=str(i))
        if groups:
            try:
                table.move_cursor(row=self._group_index)
            except Exception:  # noqa: BLE001
                pass

    def _current_group(self) -> dict | None:
        groups = self._config.get("groups", [])
        if 0 <= self._group_index < len(groups):
            return groups[self._group_index]
        return None

    def _load_group(self) -> None:
        group = self._current_group()
        table = self.query_one("#models-table", DataTable)
        table.clear()
        if group is None:
            return
        for m in group.get("models", []):
            mtype = m.get("type", "openrouter")
            strategy = cfg.pricing_label(mtype, m.get("pricing") or cfg.default_pricing(mtype))
            table.add_row(m.get("name", ""), m.get("id", ""), mtype, strategy)

    @on(DataTable.RowSelected, "#group-table")
    def _group_selected(self, event: DataTable.RowSelected) -> None:
        # RowSelected 只有 cursor_row / row_key，没有 row_index
        groups = self._config.get("groups", [])
        if 0 <= event.cursor_row < len(groups):
            self._group_index = event.cursor_row
            self._load_group()

    @on(Button.Pressed, "#rename-group")
    def _rename_group(self) -> None:
        groups = self._config.get("groups", [])
        if not 0 <= self._group_index < len(groups):
            return
        self._rename_target = self._group_index
        current = groups[self._group_index].get("display_name", "")
        self.app.push_screen(InputModal("新的组名称", title="重命名对比组", value=current), self._on_rename)

    def _on_rename(self, name: str | None) -> None:
        if name is None:
            return
        groups = self._config.get("groups", [])
        if 0 <= self._rename_target < len(groups):
            groups[self._rename_target]["display_name"] = name
            self._refresh_group_table()

    @on(Button.Pressed, "#add-group")
    def _add_group(self) -> None:
        self._config.setdefault("groups", []).append({"display_name": "New Group", "models": []})
        self._group_index = len(self._config["groups"]) - 1
        self._refresh_group_table()
        self._load_group()

    @on(Button.Pressed, "#del-group")
    def _del_group(self) -> None:
        groups = self._config.get("groups", [])
        if not groups:
            return
        name = groups[self._group_index].get("display_name", "")
        self.app.push_screen(
            ConfirmModal(
                f"删除对比组「{name}」及其全部模型条目？（点「保存」后才会写盘）",
                title="删除对比组",
                yes="删除",
                default_yes=False,
            ),
            self._confirm_del_group,
        )

    def _confirm_del_group(self, ok: bool) -> None:
        if not ok:
            return
        groups = self._config.get("groups", [])
        if not groups:
            return
        groups.pop(self._group_index)
        self._group_index = max(0, self._group_index - 1)
        self._refresh_group_table()
        self._load_group()

    # ---------------- 模型 ----------------

    @on(DataTable.RowSelected, "#models-table")
    def _model_selected(self, event: DataTable.RowSelected) -> None:
        group = self._current_group()
        if group is not None and 0 <= event.cursor_row < len(group.get("models", [])):
            self._edit_index = event.cursor_row

    @on(Button.Pressed, "#add-model")
    def _add_model(self) -> None:
        if self._current_group() is None:
            return
        self._edit_index = -1
        self.app.push_screen(ModelFormModal(), self._on_model_result)

    @on(Button.Pressed, "#edit-model")
    def _edit_model(self) -> None:
        self._open_model_edit(self.query_one("#models-table", DataTable).cursor_row)

    def _open_model_edit(self, idx: int | None) -> None:
        group = self._current_group()
        if group is None or not group.get("models"):
            return
        if idx is None or idx < 0 or idx >= len(group["models"]):
            return
        self._edit_index = idx
        self.app.push_screen(ModelFormModal(group["models"][idx]), self._on_model_result)

    def _on_model_result(self, data: dict | None) -> None:
        if data is None:
            return
        group = self._current_group()
        if group is None:
            return
        model = {"name": data["name"] or data["id"] or data["type"], "id": data["id"], "type": data["type"]}
        if data.get("pricing"):
            model["pricing"] = data["pricing"]
        models = group.setdefault("models", [])
        if self._edit_index is not None and 0 <= self._edit_index < len(models):
            models[self._edit_index] = model
        else:
            models.append(model)
        self._load_group()

    @on(Button.Pressed, "#del-model")
    def _del_model(self) -> None:
        group = self._current_group()
        table = self.query_one("#models-table", DataTable)
        if group is None or not group.get("models"):
            return
        idx = table.cursor_row
        if idx is None or idx < 0 or idx >= len(group["models"]):
            return
        self.app.push_screen(
            ConfirmModal(
                f"删除模型条目「{group['models'][idx].get('name', '')}」？（点「保存」后才会写盘）",
                title="删除模型",
                yes="删除",
                default_yes=False,
            ),
            lambda ok: self._confirm_del_model(idx) if ok else None,
        )

    def _confirm_del_model(self, idx: int) -> None:
        group = self._current_group()
        if group is None or not group.get("models"):
            return
        if 0 <= idx < len(group["models"]):
            group["models"].pop(idx)
        self._load_group()

    # ---------------- 保存 / 放弃 ----------------

    def _working(self) -> dict:
        probe = copy.deepcopy(self._config)
        raw = self.query_one("#rate", Input).value.strip()
        try:
            probe.setdefault("exchange_rate", {})["usd_to_cny"] = float(raw)
        except ValueError:
            pass
        self._commit_scenarios()
        probe["scenarios"] = copy.deepcopy(self._config["scenarios"])
        return probe

    def _is_dirty(self) -> bool:
        try:
            return self._working() != self._config_orig
        except Exception:  # noqa: BLE001
            return True

    @on(Button.Pressed, "#btn-save")
    def _save(self) -> None:
        raw = self.query_one("#rate", Input).value.strip()
        try:
            self._config.setdefault("exchange_rate", {})["usd_to_cny"] = float(raw)
        except ValueError:
            pass
        self._commit_scenarios()
        cfg.save_config(self._config, self._target)
        self.dismiss(True)

    @on(Button.Pressed, "#btn-cancel")
    def _cancel(self) -> None:
        self._try_abandon()

    def action_page_back(self) -> None:
        self._try_abandon()

    def _try_abandon(self) -> None:
        if self._is_dirty():
            self.app.push_screen(
                ConfirmModal(
                    "有未保存的修改，放弃并返回？",
                    title="放弃修改",
                    yes="放弃",
                    default_yes=False,
                ),
                lambda ok: self.dismiss(False) if ok else None,
            )
        else:
            self.dismiss(False)
