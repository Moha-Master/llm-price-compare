"""
settings_screen.py — 程序内设置页

提供汇率、场景、对比组与模型的可视化增删改；保存后写回 config.yaml。
组列表与模型列表均用 DataTable 实现，规避 Textual 各版本 ListView/OptionList 的 API 差异。
"""

from __future__ import annotations

import copy
from pathlib import Path

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from . import config as cfg

TOKEN_ROWS: list[tuple[str, str]] = [
    ("cache_read", "缓存读"),
    ("cache_write", "缓存写"),
    ("input", "输入"),
    ("output", "输出"),
]


class ModelEditScreen(ModalScreen["dict | None"]):
    """新增 / 编辑单个模型条目。"""

    DEFAULT_CSS = """
    ModelEditScreen { align: center middle; }
    ModelEditScreen > Vertical {
        width: 64; max-height: 90%; padding: 1 2;
        border: round $primary; background: $surface;
    }
    ModelEditScreen Input, ModelEditScreen Select { width: 100%; margin-bottom: 1; }
    ModelEditScreen .edit-actions { align-horizontal: right; }
    ModelEditScreen .edit-actions Button { margin-left: 2; }
    """

    def __init__(self, model: dict | None = None) -> None:
        super().__init__()
        self._model = dict(model) if model else {}

    def compose(self):
        m = self._model
        with Vertical():
            yield Label("编辑模型" if m else "添加模型")
            yield Input(placeholder="显示名称", value=m.get("name", ""), id="me-name")
            yield Input(
                placeholder="模型 ID（官方模型填官方 id，OR 填 provider/name）",
                value=m.get("id", ""),
                id="me-id",
            )
            yield Label("定价来源 type")
            yield Select(
                [(t, t) for t in cfg.PROVIDER_TYPES],
                value=m.get("type", "openrouter"),
                allow_blank=False,
                id="me-type",
            )
            yield Label("定价策略 pricing（仅 openrouter 生效）")
            yield Select(
                [(p, p) for p in cfg.PRICING_STRATEGIES],
                value=m.get("pricing", "expected"),
                allow_blank=False,
                id="me-pricing",
            )
            with Horizontal(classes="edit-actions"):
                yield Button("取消", id="me-cancel", variant="default")
                yield Button("确定", id="me-ok", variant="primary")

    @on(Button.Pressed, "#me-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#me-ok")
    def _ok(self) -> None:
        name = self.query_one("#me-name", Input).value.strip()
        mid = self.query_one("#me-id", Input).value.strip()
        mtype = self.query_one("#me-type", Select).value
        pricing = self.query_one("#me-pricing", Select).value
        model: dict = {"name": name or mid or mtype, "id": mid, "type": mtype}
        if mtype == "openrouter":
            model["pricing"] = pricing
        self.dismiss(model)


class SettingsScreen(Screen):
    """保存后 dismiss(True)，主界面据此热刷新。"""

    DEFAULT_CSS = """
    SettingsScreen { background: $surface; }
    SettingsScreen #settings-title { padding: 1 2; text-style: bold; }
    SettingsScreen #settings-body { height: 1fr; }
    SettingsScreen .field-label { margin-top: 1; padding-top: 1; }
    SettingsScreen #rate { width: 24; }
    SettingsScreen .scenario-row { margin: 0 0 1 0; padding: 1; border: round $secondary; height: auto; }
    SettingsScreen .scenario-row Input { width: 16; margin-left: 1; }
    SettingsScreen .scenario-row .sc-name { width: 24; margin-left: 0; }
    SettingsScreen .group-side { width: 34; padding-right: 1; }
    SettingsScreen #group-table { height: 1fr; }
    SettingsScreen .group-side Button { width: 100%; margin-top: 1; }
    SettingsScreen #group-editor { width: 1fr; padding: 0 0 0 2; }
    SettingsScreen #group-name { width: 40; }
    SettingsScreen #models-table { height: 1fr; margin-top: 1; }
    SettingsScreen .row-actions Button { margin-left: 1; }
    SettingsScreen #settings-bar { dock: bottom; height: 3; padding: 1 2; align-horizontal: right; background: $panel; }
    SettingsScreen #settings-bar Button { margin-left: 2; }
    """

    BINDINGS = [("escape", "abandon", "放弃修改")]

    def __init__(self, config: dict, target_path: str | Path | None = None) -> None:
        super().__init__()
        self._config = copy.deepcopy(config)
        self._target = Path(target_path) if target_path else cfg.get_default_config_path()
        self._group_index = 0
        self._edit_index = -1

    # ---------------- 结构 ----------------

    def compose(self):
        yield Static("⚙️  设置", id="settings-title")
        with TabbedContent(id="settings-body"):
            with TabPane("常规", id="tab-general"):
                with VerticalScroll():
                    yield Label("美元 → 人民币汇率", classes="field-label")
                    yield Input(id="rate")
            with TabPane("场景", id="tab-scenario"):
                with VerticalScroll(id="scenario-scroll"):
                    yield VerticalScroll(id="scenario-list")
                    yield Button("＋ 添加场景", id="add-scenario", variant="default")
            with TabPane("对比组", id="tab-group"):
                with Horizontal():
                    with Vertical(classes="group-side"):
                        yield Label("对比组")
                        yield DataTable(id="group-table")
                        yield Button("＋ 新建组", id="add-group")
                        yield Button("🗑 删除组", id="del-group", variant="error")
                    with VerticalScroll(id="group-editor"):
                        yield Label("组显示名", classes="field-label")
                        yield Input(id="group-name")
                        yield Label("模型条目（选中下表行后可编辑/删除）", classes="field-label")
                        yield DataTable(id="models-table")
                        with Horizontal(classes="row-actions"):
                            yield Button("＋ 添加模型", id="add-model")
                            yield Button("✎ 编辑模型", id="edit-model")
                            yield Button("🗑 删除模型", id="del-model", variant="error")
        with Horizontal(id="settings-bar"):
            yield Button("放弃", id="btn-cancel", variant="default")
            yield Button("💾 保存", id="btn-save", variant="success")

    async def on_mount(self) -> None:
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

    # ---------------- 场景 ----------------

    async def _rebuild_scenarios(self) -> None:
        box = self.query_one("#scenario-list")
        await box.remove_children()
        rows: list[Horizontal] = []
        for idx, sc in enumerate(self._config.get("scenarios", [])):
            tokens = sc.get("tokens", {})
            children: list = [Input(placeholder="场景名", value=sc.get("name", ""), classes="sc-name")]
            for key, label in TOKEN_ROWS:
                inp = Input(value=str(tokens.get(key, 0)), classes=f"sc-{key}")
                inp.tooltip = label
                children.append(inp)
            # 用 widget 的一等公民 id 携带行号（而非往实例挂私有属性），删除时反解。
            del_btn = Button("🗑", classes="sc-del", id=f"sc-del-{idx}", variant="error")
            children.append(del_btn)
            row = Horizontal(*children, classes="scenario-row")
            rows.append(row)
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
        # 从被点按钮的 id（"sc-del-<idx>"）反解行号，避免在 widget 实例上挂私有属性。
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
                raw = row.query_one(f".sc-{key}", Input).value.strip()
                try:
                    tokens[key] = float(raw)
                except ValueError:
                    tokens[key] = 0.0
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
            self.query_one("#group-name", Input).value = ""
            return
        self.query_one("#group-name", Input).value = group.get("display_name", "")
        for m in group.get("models", []):
            table.add_row(
                m.get("name", ""),
                m.get("id", ""),
                m.get("type", ""),
                m.get("pricing", "—") if m.get("type") == "openrouter" else "—",
            )

    @on(DataTable.RowSelected, "#group-table")
    def _select_group(self, event: DataTable.RowSelected) -> None:
        self._commit_group_name()
        self._group_index = self.query_one("#group-table", DataTable).cursor_row
        self._load_group()

    def _commit_group_name(self) -> None:
        group = self._current_group()
        if group is not None:
            new_name = self.query_one("#group-name", Input).value.strip()
            group["display_name"] = new_name
            table = self.query_one("#group-table", DataTable)
            if 0 <= self._group_index < table.row_count:
                try:
                    table.update_cell(self._group_index, 1, new_name or "(未命名)")
                except Exception:  # noqa: BLE001
                    pass

    @on(Input.Changed, "#group-name")
    def _on_group_name_changed(self) -> None:
        group = self._current_group()
        if group is not None:
            group["display_name"] = self.query_one("#group-name", Input).value.strip()

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
        groups.pop(self._group_index)
        self._group_index = max(0, self._group_index - 1)
        self._refresh_group_table()
        self._load_group()

    # ---------------- 模型 ----------------

    @on(Button.Pressed, "#add-model")
    def _add_model(self) -> None:
        if self._current_group() is None:
            return
        self._edit_index = -1
        self.app.push_screen(ModelEditScreen(), self._on_model_result)

    @on(Button.Pressed, "#edit-model")
    def _edit_model(self) -> None:
        group = self._current_group()
        table = self.query_one("#models-table", DataTable)
        if group is None or not group.get("models"):
            return
        idx = table.cursor_row
        if idx is None or idx < 0:
            return
        self._edit_index = idx
        self.app.push_screen(ModelEditScreen(group["models"][idx]), self._on_model_result)

    def _on_model_result(self, model: dict | None) -> None:
        if model is None:
            return
        group = self._current_group()
        if group is None:
            return
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
        group["models"].pop(idx)
        self._load_group()

    # ---------------- 保存 / 放弃 ----------------

    @on(Button.Pressed, "#btn-save")
    def _save(self) -> None:
        raw = self.query_one("#rate", Input).value.strip()
        try:
            self._config.setdefault("exchange_rate", {})["usd_to_cny"] = float(raw)
        except ValueError:
            pass
        self._commit_scenarios()
        self._commit_group_name()
        cfg.save_config(self._config, self._target)
        self.dismiss(True)

    @on(Button.Pressed, "#btn-cancel")
    def _cancel(self) -> None:
        self.dismiss(False)

    def action_abandon(self) -> None:
        self.dismiss(False)
