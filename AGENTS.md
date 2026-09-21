# AGENTS.md — llm-price-compare

# 第一部分 · UI 开发统一规范

> 本部分在 aliyun-controller、`../clash-controller`、`../litellm-controller`、`../llm-price-compare` 四项目间**保持同一份文本**（个别差异会显式标注）。任何一侧修订必须同步其余项目，保证各项目的 Agent 拿到相同标准。
> 依据均为本地 Textual 8.2.8 实测结论，逐条验证记录见 `docs/textual-dev-guide.md`。

## 1. 技术栈与代码质量

- Python >= 3.10；`textual >= 8.0`（依赖 compact Input、`overlay: screen` 等 8.x 特性）；UI 用到新特性时同步抬版本下限。
- 入口命令 `<pkg>ctl`，支持 `-D/--dir`（指定配置目录，main 在 import app 前写环境变量）与 `--version`。
- ruff：`line-length = 120`，`select = ["E","F","W","I","UP","B","C4"]`，忽略 `E501`；改动后必须零告警。
- 应用代码**禁止 `print`**（破坏 TUI）；调试信息走 `app.add_log` / 状态栏。
- 仓库不提交测试文件；验证用 `/tmp` 一次性脚本（模板见第二部分「验证」）。

## 2. 分层架构

- 展示层：`screens/`、`ui.py`、`widgets.py`、`app.tcss`。`ui.py` 只放可复用界面组件与页面骨架，不写业务取数。
- 服务层：顶层模块（不建 `modules/` 子包），零 Textual 依赖、不 print；失败统一抛项目异常类型（如 `AliyunApiError` / `RuntimeError`），由屏幕层捕获后 `notify_err`。
- 屏幕层通过 App 的懒加载 getter 拿客户端（`app.get_billing()` 模式）。

## 3. App 级约定

- 无 `Header` / `Footer`；App `compose()` 只 yield 一个 `#status`（`height: 1; dock: bottom`）。
- `ENABLE_COMMAND_PALETTE = False`。
- App 绑定 `Binding("ctrl+q", "quit", priority=True)`——任意焦点/输入态都能退出。
- 状态栏 API：`app.status(msg, kind)`，`kind ∈ "" | ok | warn | err`（对应绿/黄/红着色）；`app.notify_ok/notify_err/notify_warn`（status + 右下角 toast）。
- 不要用 `App` 已有只读属性名（`debug` 等）作实例属性（用 `debug_mode` 之类）。

## 4. 页面骨架（ui.PageScreen）

- 功能页一律继承 `ui.PageScreen`，结构固定：
  顶栏 `#topbar`（左 `◀ 返回` 按钮 + Title/SubTitle 靠左；右侧 `compose_toolbar()` 控件 + 可选折叠菜单按钮）→ `#page`（`height: 1fr; overflow-y: hidden`）→ 底部 `.page-hint` 提示栏贴底。
- 子类只写：`TITLE` / `HINT`（及可选 `SUBTITLE`）、`compose_page()`、`compose_toolbar()`、`reload_page()`；键位/Esc/滚动自动获得。
- 副标题动态更新用 `set_subtitle()`；根屏（启动页/选择页）若需与首页一致的居中版式，采用 `Screen` + `.logo-page`（`ui.LOGO_LINES` + `OptionList`）；亦可复用 PageScreen 覆写 `action_page_back()` 为 `app.exit()`，并把返回按钮 label 改成 `◀ 退出`。
- 折叠菜单 `self.menu = [(label|callable, callback, danger)]`：语义对齐 Android ⋮，**只放次要/低频项**；主要操作必须以容器内按钮常驻可见；`menu` 为空时菜单按钮自动不渲染；危险项文本染红。
- 首页：`ui.LOGO_LINES` 艺术字（`#home-banner` **`text-align: left`**，整块靠 `#home-col` 居中，避免逐行居中造成错位）+ 版本副标题右对齐 + 菜单项 + 底部提示栏。列宽由 `ui.home_col_width()`（= `max(LOGO_WIDTH, 40)`，`LOGO_WIDTH` 由 `cell_len(line.rstrip())` 自动计算）在 `on_resize` 动态写回 `#home-col`，版本号因此始终对齐 Logo 右缘。窄终端 `width < LOGO_WIDTH + 6` 挂 `-sm` 降级为普通文本。整组居中用容器 `align: center middle`（`content-align` 不定位子件）。
- 首页菜单描述**右对齐**；描述超宽时用 `widgets.MenuMarquee` 在选项区域内来回跑马灯（不换行）。

## 5. 内容区版式与滚动

- 主模式「**小容器 + 大容器**」：小容器 `.panel`（`padding: 1 2; border: round`）或容器内 `.filter-row` 行放筛选/排序/主操作按钮；大容器是表格（`make_table()` 自带 `.tbl` 类 → `height: 1fr`）。排列方向可变（上大下小 / 上小下大 / 左右）。
- **一切内容皆入容器**：功能页所有可见组件必须包裹在 `.panel` 或 `.tbl` 内，严禁直接在 `#page` 下漂浮。
- 只读状态行用 `.kv-row/.kv-label/.kv-value`（标签定宽、值加粗）。
- **外层永不滚动**：`#page` overflow hidden；固定行 `height: auto`。`Vertical`/`Horizontal` 默认 `height: 1fr`，放进 auto 上下文必须显式 `height: auto`。全页只允许表格一个滚动条。
- Home/End/PgUp/PgDn 由 PageScreen 绑定（不加 priority，Input 聚焦时让位），目标 `_scroller()`：优先 `#page` 内第一个 VerticalScroll，否则 `#page`；表格滚动走 DataTable 自身键位。

## 6. 模态（widgets.py）

- **`Button` 全局单行**：各项目 `app.tcss` 统一 `Button { height: 1; border: none; min-width: 0; padding: 0 1 }` + `Button:focus { text-style: bold reverse }`（等价于旧 `compact=True`，调用处不再传）；变体色（primary/error/…）即背景色。**同属性下 app.tcss 元素规则会压过一切 widget `DEFAULT_CSS` 类/ID 规则**，加全局控件样式前必须审查小尺寸控件（见 §12）。
- 全部模态为 `ModalScreen[T]`，统一三段式：`.modal-title`（`border-bottom: hkey`）→ 内容区 → `.btn-row`（`border-top: hkey; dock: bottom; align-horizontal: right`）。
- 按钮语义：default=一般、primary=推荐、error=危险；顺序 `[取消] [主操作] … [危险放最右]`。
- `ConfirmModal`：回车=确认；不可逆操作 `default_yes=False`（确认按钮变 error 色、回车不再直接放行按钮，仅按钮点击生效）。
- `InputModal`：单行 + validator，留空=不更改语义由调用方决定；`[取消][确定]`。
- `FormModal`：字段 `kind: text | password | choice | switch | note`（clash/litellm 另有 `textarea` 供长文本如私钥；litellm 另有 `browse`：Input + 「选择…」弹 `PickModal` 回填）。
- 字段过多的复合表单（如模型参数、路由组成员勾选）用 **sheet 式模态**：`ModalScreen` + `.modal-box` 定宽（≤104）/ `height 88~90%` + `.modal-title` + `VerticalScroll` 内容 + docked `.btn-row`；不拆多步问询弹窗串联。Input/Select 一律 `compact=True`；`.frm-row { margin-bottom: 1 }`、无 hint 行高恰好 1；`.modal-box { min-height: 24 }`；底部错误行 `#frm-error`（validator 失败提示且不关闭）。
  - 密码框：占位符使用 `widgets.mask_secret()` 脱敏显示，**留空 = 保持原值**。
  - 布尔开关：表单内 `kind="switch"`（Switch 用 `border: none; height: 1` 压单行），**不要**独立动作按钮、不要 Checkbox。
  - **`Switch` / `Checkbox` / `RadioButton` 一律全局压成一行**（`height: 1; border: none; padding: 0 1`，focus 用 background-tint）：litellm 在 `app.tcss` 全局规则；aliyun/clash 在 `.frm-field` / `.kv-row` 上下文同名规则。
  - `extra_buttons`（按按钮 id 返回结果）与功能型按钮必须互斥：如 litellm 的 `browse`「选择…」按钮在 `on_button_pressed` 里按 `.frm-browse` 类名排除，否则会被当额外按钮误 dismiss（历史事故：编辑 Upstream provider 崩溃）。
  - 焦点：`on_mount` 聚焦第一个字段；Tab/Shift+Tab 轮切（Screen 原生焦点链）；Enter（Input.Submitted）= 提交；Esc / Ctrl+C = 取消。
- `OutputModal`：只读长文本，VerticalScroll + `[关闭]`。
- **不要用行内 `display` 切换做就地编辑**——隐藏 Input 不进 Tab 焦点链、编辑态难以退出（已被否，用 FormModal）。
- 调用：worker 内 `await app.push_screen_wait(modal)`；事件回调里 `app.push_screen(modal, callback)`。

## 7. 键位总表（统一，勿另起方案）

| 键 | 行为 |
|---|---|
| `↑↓←→` | 移动焦点/光标 |
| `Tab` / `Shift+Tab` | 轮切焦点（表单内轮切字段） |
| `Enter` | 确认 / 提交 / 执行所选行 |
| `Esc` / `Ctrl+C` | 关闭层级：**浮层 > 模态 > 返回上一页**；**根屏 / 主菜单为退出程序**（Textual 无默认 Esc，每屏必须自绑） |
| `Ctrl+Q` | **任意界面**直接退出程序（App priority 绑定，浮层 / 模态 / 输入态均生效） |
| `Home/End/PgUp/PgDn` | 功能页（PageScreen）滚动（不抢 Input 的文本导航） |
| `Ctrl+R` | 功能页刷新（调 `reload_page()`） |
| `Ctrl+N` / `Ctrl+E` / `Ctrl+D` | 条目页 新增 / 编辑 / 删除 |
| 单字母 `1-9` | 仅限**无输入框的主菜单 / 列表页**（快捷直达） |
| 单字母 `/` | 仅限**确有搜索框的列表页**（聚焦搜索；无搜索框的项目不设） |

- **无 `q` 绑定**：退出统一走 `Ctrl+Q`（任意界面）与 `Esc`/`Ctrl+C`（根屏 / 主菜单）。
- **提示栏只写本页真实有效的键**：`.page-hint` / `HINT` 必须与本页 `BINDINGS` + 继承绑定逐条对应，不得出现该页不可用的键。
- `Ctrl+C` 在 `Input` / `TextArea` 聚焦时仍是「复制文本」（Textual 框架行为），其余位置等价于 `Esc`。

### 7.1 四项目键位设计对照

> 原则：能对齐就对齐；确无对应操作/确实多出操作的，允许差异并在此登记。

| 场景 / 页面 | aliyun-controller | clash-controller | litellm-controller | llm-price-compare |
|---|---|---|---|---|
| App 全局 | `Ctrl+Q` 任意退出；`Tab/Shift+Tab` 焦点轮切 | 同左 | 同左 | 同左；另有 `Ctrl+S` 全局打开设置 |
| 功能页基类 PageScreen | `Esc`/`Ctrl+C` 返回、`Ctrl+R` 刷新、`Home/End/PgUp/PgDn` 滚动 | 同左 | 同左 | 同左 |
| 首启 / 根屏 | `SetupWizardScreen`：`Enter` 提交、`Esc`/`Ctrl+C` 取消并退出 | `ProfileListScreen`：`↑↓` 移动、`Enter`/单击 连接、`1-9` 直连、`Ctrl+N/E/D` 增删改、`Ctrl+R` 刷新、`Esc`/`Ctrl+C` 退出 | `SetupWizardScreen`（模态向导）：`Enter` 提交、`Esc`/`Ctrl+C` 取消并退出 | `DashboardScreen`（看板即根屏）：`[`/`]` 切页、`g` 回总览、`1-9` 直达、`←→` 选列、`s` 排序、`Ctrl+R` 刷新、`Ctrl+S` 设置、`Esc/Ctrl+C` 退出；缺配置先弹 `SetupScreen` |
| 主菜单 | `HomeScreen`：`↑↓`、`Enter`、`1-5` 直达、`Esc`/`Ctrl+C` 退出 | `HomeScreen`：`↑↓`、`Enter`、`1-4` 直达、`Esc`/`Ctrl+C` 退出（切换端点走菜单项 `4`） | `HomeScreen`：`↑↓`、`Enter`、`1-4` 直达、`Esc`/`Ctrl+C` 退出 | ➖ 无独立主菜单（看板即根屏） |
| 列表页（带搜索） | `DomainListScreen` / `RecordListScreen`：`↑↓`、`Enter`/单击、`/` 搜索、`Ctrl+N/E/D`、`Ctrl+R`、`Esc` 返回 | `ConfigScreen`：同左但无搜索框故无 `/` | `ModelListScreen` / `RoutingListScreen`：`↑↓`、`Enter`/单击、`/` 搜索、`Ctrl+N`、`Ctrl+R`、`Esc` 返回；`DefaultEditorScreen`：`Ctrl+N`＋[保存/重置]按钮 | ➖ 无通用搜索列表页 |
| 监控 / 查看 | `TrafficScreen` / `SummaryScreen`：`◀▶` 切月、`Ctrl+R`、`Esc` 返回、滚轮浏览 | `OverviewScreen`：`↑↓/PgUp/PgDn` 滚动、`Ctrl+R`、`Esc` 返回（无账期故无 `◀▶`） | `BuildScreen`：`Ctrl+R` 重新构建、[导出 JSON] 按钮、`Esc` 返回 | 同首启/根屏（看板总览与模型 tab） |
| 设置 | `SettingsScreen`：点击条目/`Enter` 开 FormModal 保存、`Esc` 返回 | `SettingsScreen`：`Tab` 轮切、`Enter` 操作控件即时生效、`Ctrl+R`（无保存动作） | `SettingsScreen`：单击/`Ctrl+E` 编辑 Upstream、`Ctrl+N/D`、`Esc` 返回；`ScriptsScreen`：`/` 搜索、`Ctrl+N` 新建、单击 开脚本设置 | `SettingsScreen`：Tabbed（常规/场景/对比组），单击选择，`[✎ 编辑/重命名]` 弹模态，`[🗑 删除]` 弹 ConfirmModal，`[💾 保存]` / `Esc` 放弃（有改动先确认） |
| 日志 | ➖ 无独立日志页 | `LogScreen`：`↑↓/PgUp/PgDn` 滚动、`Ctrl+R` 重载、`Esc` 返回 | ➖ 无独立日志页 | ➖ 无独立日志页（进度/状态走底部状态栏） |
| 模态 | `Enter` 提交/确认、`Esc`/`Ctrl+C` 取消关闭、`Tab` 轮切字段 | 同左 | 同左；另有 `PickModal`（输入筛选 + 回车）与 sheet 式大表单（`ModelFormScreen` 等，按钮提交，无隐式回车） | 同左（SetupScreen、InputModal 重命名、ModelFormModal 动态定价、ConfirmModal 删除） |
| 文本编辑（Input/TextArea） | 控件原生编辑键优先；`Ctrl+R` 刷新禁用；底部提示栏切 `EDIT_HINT` | 同左 | 同左 | 同左 |

- 单字母键（`1-9`/`/`）只在**无输入框**页面保留；有 Input 的页面一律用 `Ctrl` 组合键或方向键。
- `1-9` 的位数按各项目菜单/列表实际条目上限确定（aliyun 1-5、clash 首页 1-4 / 端点页 1-9、litellm 首页 1-4 / 参数主页 1-3）。
- litellm 有搜索框的列表页（`ScriptsScreen`/`DefaultEditorScreen`）只用 `Ctrl+N` 与容器内按钮，不再占用会被 Input 抢占的 `Ctrl+E`/`Ctrl+D`（§7.2 约束）。

### 7.2 文本编辑模式（焦点在 Input / TextArea）

- 焦点进入 `Input` / `TextArea` 即视为**文本编辑模式**：控件原生编辑键位优先于页面 / App 的普通绑定（Textual 绑定链按「焦点控件 → 祖先 → Screen → App」查找），无需额外代码即生效。
- Textual 内置编辑键（勿重复实现）：`←→`/`Ctrl+←→`、`Home`/`Ctrl+A` 行首、`End`/`Ctrl+E` 行尾、`Ctrl+Shift+A` 全选、`Shift+方向` 选择、`Backspace`、`Delete`/`Ctrl+D`、`Ctrl+W/U/K` 删词 / 清左 / 清右、`Ctrl+X/C/V` 剪切 / 复制 / 粘贴；`TextArea` 另有 `↑↓`、`PgUp/PgDn`、`Ctrl+Z/Y` 撤销 / 重做、`Ctrl+Shift+K` 删行。
- 冲突规则（统一约定）：
  - **编辑态禁用页面刷新 `Ctrl+R`**：`PageScreen.check_action` 在焦点为 `Input`/`TextArea` 时对 `refresh_page` 返回 `False`。
  - `Ctrl+C`：有选中 → 复制；无选中 → `Input.action_copy` 抛 `SkipAction` 冒泡为「返回 / 取消」（无需额外代码）。
  - `PgUp/PgDn`：保留控件原生行为（`Input` 未绑则冒泡页面滚动，`TextArea` 为光标翻页）。
  - `Tab`/`Shift+Tab`：保留焦点轮切（`TextArea` 保持默认 `tab_behavior="focus"`；改 `"indent"` 会吞 `Tab`，不建议）。
  - `Ctrl+Q`：不受编辑模式影响，任意界面退出。
  - 终端限制：`Ctrl+V` 走 Textual 剪贴板（OSC52），不保证系统剪贴板；`Ctrl+A` 是**行首**（全选是 `Ctrl+Shift+A`）。
- 底部提示栏联动：焦点进出输入框时，页面 `#page-hint` 在 `HINT` 与 `EDIT_HINT` 间切换（`ui.PageScreen._refresh_hint`）；模态（`FormModal`/`InputModal`）在 `#frm-hint`/`#im-hint` 按焦点类型显示 `HINT_FORM`（非输入）/ `HINT_FORM_EDIT`（Input）/ `HINT_FORM_TA`（TextArea）。常量定义在 `widgets.py`。
- **约束**：有搜索框（Input）的列表页不要用 `Ctrl+E`/`Ctrl+D` 做条目操作（会被 Input 的「行尾 / 右删」抢占），改用 `Ctrl+N` 与容器内按钮或 `Enter`。

## 8. 鼠标交互

- **所有可操作行一律单击执行**：数据表用 `widgets.ClickTable`（`make_table()` 默认返回）。单击数据格 = 移光标 + 立即发 `RowSelected`；表头点击仍是 `HeaderSelected`。
- 按钮/选项/入口同样单击触发；滚轮天然作用于光标下滚动容器。
- 行点击判定、浮层外点击判定一律用 `event.screen_x / screen_y`（冒泡到 Screen 的 `event.x/y` 是相对坐标）。
- 单击即执行的高危操作必须仍有 ConfirmModal 把关。

## 9. 表格规范

- 数据展示一律 `DataTable` + `make_table()` / `load_rows()`；禁止手写空格对齐字符串伪表格。
- 内容列 `shorten(text, cap)` 截断（cap 按列典型宽度定）；右对齐列（数字/状态）用 `rcell(text, width)` 前导空格补齐，**表头同样 rcell**。
- 列宽：`fit_table_columns(table, weights, rows=即将装载的行数)` 按权重瓜分容器宽（返回值含每列左右 2 空格 padding）。
- **列宽/表头/单元格必须同一帧同源生成**：垂直滚动条用行数确定性预判（`rows > region.height - 3` 预留 2 列），不要依赖 `max_scroll_y`（装载前后会变）；布局稳定后整表重建一次（`call_after_refresh`），勿只改列宽不重建单元格。
- 列宽在装载函数与 `on_resize` 里重算（`on_resize` 直接定义即可，`Screen` 没有可 `super()` 的默认实现）。
- `.tbl` 加 `overflow-x: hidden` 兜底防横向滚动条；`:focus` 态边框也必须保持圆角（`.tbl:focus { border: round $primary }`），否则聚焦时出现直角，与 `.panel` 风格割裂。

## 10. 浮层（页内弹层）三要素

- 自定义 `Message` 类要能被 `@on(..., "#id")` 匹配必须提供 `control` 属性（返回 `self._sender`）。
- 浮层父容器必须声明 `layers: base overlay`，否则鼠标命中下层组件。
- 浮层本体：`position: absolute; overlay: screen; layer: overlay; display` 切换；定位用 `styles.offset`；右缘控件的浮层右对齐展开并防越界。
- Button 内容宽 = 区域宽 − padding(2) − `line-pad`(1×2)；`line-pad: 0` **非法**（须 ≥1），紧凑网格按钮按 `文本宽 + 4` 定 `width`/`min-width` 并加宽容器。

## 11. 取数与并发逻辑

- 阻塞调用（云 SDK / requests / paramiko / subprocess）**一律** `asyncio.to_thread`，包在 `@work(exclusive=True)` worker 里，`on_mount` 触发。
- 实时流：`@work(thread=True)` + `call_from_thread` 回 UI 线程；`on_unmount` 置停止位并 close response，防线程泄漏。
- 轮询：`set_interval` + busy 标志去重；`on_unmount` 停 timer。
- 展示刷新函数与列宽计算解耦：`_rebuild/_load`（数据 → 单元格 + fit）与 worker（取数）分开。

## 11.5 加载指示器与忙碌遮罩规范

- **设计原则**：对耗时 >300ms 的网络 / IO 操作必须有可见的加载状态，处理期间需阻断对底层（如旧数据行、提交按钮）的重复操作。
- **四种基础形态与适用场景**：
  1. **控件级 indeterminate 覆盖层（`ProgressCover`）**：
     - 场景：主要数据列表加载（Billing / Traffic / Domain / Record / Models / Routing 等）与列表型容器（如 upstream 模型列表、路由组成员列表）。
     - 机制：在 `App` 覆写 `get_loading_widget() -> ProgressCover`。取数时设 `widget.loading = True`，控件被覆盖且从命中测试中排除（**天然阻断对旧数据行的点击**）；完成后 `widget.loading = False` 并 reassert 焦点。
     - **关键约束**：`ProgressCover` 必须是**单个自渲染 widget**：`render()` 返回一条**固定 40 格、居中**的不定进度条 `Text`（`auto_refresh` 逐帧移动高亮，宽度与全屏 `BusyOverlay` 一致）。**绝不能是容器 + 子件**——Textual 的 `Widget._cover()` 只把 cover 交给合成器替换原控件区域，并不把它挂进 DOM 参与布局，容器的子件 `region` 恒为 0 而完全不可见（`ProgressBar` 自身 compose 出 `Bar` 子件，因此也不能直接用）。
     - 约束：定时轮询刷新（如 connections）仅在**首载 / 空表**时加覆盖，后续轮询不闪遮罩；`_rebuild` 完成后需显式重新 `focus()` 列表。
  2. **全屏 dots 忙碌遮罩（`BusyOverlay` mode="dots"）**：
     - 场景：表单提交、批量导入、模型参数构建 / 导出。
     - 机制：`async with busy(self.app, "正在保存…", mode="dots"): await asyncio.to_thread(...)`。`ModalScreen` 铺满，吞掉一切键盘鼠标输入。
  3. **全屏 indeterminate / percent 忙碌遮罩（`BusyOverlay` mode="bar"/"percent"）**：
     - 场景："bar" 适合阶段明显的远程拉取（如 clash 部署订阅、DNS 提交），可调 `ov.set_message("阶段…")` 换词；"percent" 适合模型总数固定、分批并行的拉取（如 lpc 一次性抓取）。
     - 机制：percent 模式开启时传入 `total`，每个模型完成时经 `self.call_from_thread(ov.advance)` 推进并自动刷新计数行。
     - 布局约束：`.busy-box` 必须**定宽**（`width: 46`）且标题 `text-wrap: nowrap` + `text-overflow: ellipsis; overflow: hidden`，内部固定为「标题 / 进度条 / 计数行」三行结构；否则文案一变容器就会因 auto 宽度重算而抖动，宽字符 Emoji（📡）或超长 URL 还会顶破边框或意外换行。
  4. **状态栏点阵 spinner**：
     - 场景：轻量、即时下发的单条请求（如 clash 调整开关、重载设置）。
     - 机制：调用 `self.app.spinner(True, "正在切换…")` 开启 status 栏 dots braille 轮转（`⠋⠙⠹…` @80ms），下发完成或 report 时自动复位。

## 12. Textual CSS / 8.2.8 通用陷阱

- 无 `:not()`、无 `z-index`、无 `top`/`left`（用 `offset` 样式属性）、无相邻兄弟选择器 `+`（解析直接报错，行距用显式类如 `.filter-row.gap-top`）。
- `max-height` 不接受 `none`，不限制就删声明。
- 8.2.8 无 `Spacer`（横向撑开用 `Static(classes="fill")` + `width: 1fr`）；`LoadingIndicator` 组件只能作为**普通挂载的子件**使用，**不可用作 `_cover` 覆盖层**（见 §11.5）；无 `.instant` 类。需要自渲染动画时，在 widget 的 `render()` 返回 `rich.spinner.Spinner` 并设 `auto_refresh`（如 1/12）。
- `cell_len` 在 `rich.cells`（复数模块名）。
- 自定义 `DataTable` 子类重写 `_on_click`：Textual 沿 MRO 逐类派发，接管与回落两条路径都要 `event.prevent_default()`，否则消息双发/双执行。
- 屏幕方法不要命名 `_render`（覆盖 `Widget._render` 渲染崩溃）。
- **级联优先级**：app.tcss（含 Screen CSS）对同一属性**始终压过** widget 自身 `DEFAULT_CSS`，与选择器特异度无关——给通用控件写全局规则前，先 grep 各控件 DEFAULT_CSS 里对该控件的 width/padding 定制（历史事故：全局 `Button{padding:0 1}` 掀翻 MonthPicker 3 格小按钮，rich `chop_cells` 除零崩溃）。
- `#topbar Button { margin }` 这类**后代选择器**会命中挂在顶栏里的组件内部按钮（MonthPicker 弹层等），且 id 前缀特异度压过 widget 类规则；顶栏间距规则必须限定到具体 id（`#topbar #top-back`）。
- `OptionList` 的 `DEFAULT_CSS` 自带 `border: tall $border-blurred`（直角框）。放进 `.panel` 圆角容器时必须显式 `border: none; background: transparent`（如 `#mh-list`），否则容器内套一个直角方框。
- 首页 Logo 每行**不要保留尾随空格**：`logo_text()` 对每行 `rstrip()`、`LOGO_WIDTH` 用 `cell_len(line.rstrip())`；否则 `text-align: center` 会按各行裁剪后的宽度独立居中，出现「某一行错位」。
- `textual.widgets` 各版本导出位置不同，`Option` 用 try/except import。
- `Select` 内部 `#label` 是 `width: 1fr`：放进 `Horizontal` 行且不给显式宽度时，auto 宽度会把整行剩余空间全吃掉，`▼` 箭头溢出容器被裁剪——行内 Select 必须显式定宽（如设置页模式 `width: 12`）。

## 13. 验证规范（四项目同一模板）

- `App.run_test(size=(120, 40))` 宽屏 + `(LOGO_WIDTH+6 以下, 28)` 窄屏各跑一遍。
- 配置目录指向 `tempfile.mkdtemp()`（写最小配置），服务层用 Fake 对象整体屏蔽网络。
- 必测清单：各页挂载无异常；`#page.virtual_size.height <= container_size.height`（单滚动条）；表格列宽和 ≈ `region.width - 2` 且无横向溢出；单击行执行且**不重复压栈**；`Ctrl+N/E/D/R`；模态紧凑度（min-height/单行输入/行距/Tab 轮切/validator 拦截）；折叠菜单浮层开合与外部点击；Esc 层级（模态 > 菜单 > 返回）；窄终端 logo `-sm` 降级与列宽重算。
- 断言 API 坑：DOMQuery 计数用 `len(query)`（无 `.count()`）；滚动上限 `max_scroll_y`（无 `scroll_max`）；Pilot 无 `shift_tab()`，用 `pilot.press("shift+tab")`；Fake 服务要**带状态**（setter 改 getter 返回值）。

## 14. 跨项目组件对照

| 组件 | aliyun-controller | clash-controller | litellm-controller | llm-price-compare |
|---|---|---|---|---|
| `ui.PageScreen` / `ui.LOGO_*` | ✅ | ✅ | ✅ | ✅（PageScreen 骨架；看板根屏无 LOGO） |
| `ui.MonthPicker` / `ui.QuotaBar` | ✅（账期/额度场景） | ➖ 无场景未搬运 | ➖ 无场景未搬运 | ➖ 无场景未搬运 |
| `widgets.ClickTable` / `HintBar` / `MenuMarquee` / `shorten` / `rcell` / `fit_table_columns` | ✅ | ✅ | ✅ | ✅（全套辅助；看板表自适应列宽） |
| `widgets` 四模态 | ✅（FormModal 无 textarea） | ✅（FormModal 多 `textarea` kind） | ✅（FormModal 多 `textarea` + `browse` 字段） | ✅（FormModal 无 textarea；设置页派生动态 pricing） |
| `PickModal` / `MultiPickModal` 选择弹窗 | ➖ | ➖ | ✅（litellm 特有：项目选择 / 模糊多选） | ➖ |
| sheet 式大表单（ModalScreen） | ➖ | ➖（用 FormModal 足够） | ✅（ModelFormScreen / GroupFormScreen / ModelMetaFormScreen） | ➖（用 FormModal 足够） |
| 模糊筛选 `filter_fuzzy` | ✅ | ✅ | ✅ | ✅ |

---

# 第二部分 · 本项目（llm-price-compare）

> 本项目是 Textual 实验的**首个**项目，且**不是 controller**：它是「自动抓取官方 + OpenRouter 定价、按场景测算成本」的**多维比价看板**。
> 因此**有意保留**不同于 controller 的地方（见「本项目差异登记」），但外框、键位、模态、样式、分层与文档规范仍对齐第一部分。

## 项目概览

- 基于 Textual 的终端 TUI：抓取各官方定价页 + OpenRouter（headline / endpoints），计算默认路由**期望价**，按自定义场景（缓存读/写/输入/输出占比）测算真实成本并横向对比。
- 包名 `llm_price_compare`，命令 `llm-price`。
- 分层与另三项目一致：**服务层** `core.py` / `config.py` / `pricing_scrapers/`（零 Textual、零 print，进度走 `log` 回调，失败降级不崩溃）；**展示层** `app.py` / `ui.py` / `widgets.py` / `screens/` / `app.tcss`。

## 开发命令

```bash
python -m venv venv && source venv/bin/activate
./venv/bin/pip install -e ".[dev]"

./venv/bin/llm-price                 # 启动看板（自动定位配置）
./venv/bin/llm-price path/config.yaml# 显式指定配置文件
./venv/bin/llm-price -D /path/dir    # 指定配置目录（写 LLM_PRICE_COMPARE_CONFIG_DIR）
./venv/bin/llm-price --version

ruff check llm_price_compare         # 改动后必须零告警
```

## 架构

```
llm_price_compare/
  main.py      CLI：argparse(config 位置参数, -D/--dir, --version) + 写环境变量 + App().run()
  app.py       PriceCompareApp：无 Header/Footer、只 yield #status、两段式 load_data、状态栏/notify、Ctrl+Q/Ctrl+S
  ui.py        界面骨架：PageScreen（顶栏 / #page / HintBar 提示栏 / 折叠菜单）。本项目无 LOGO/月份/额度组件
  widgets.py   模态与表格辅助（与三项目同一份实现）：Confirm/Input/Form/OutputModal + ClickTable/HintBar/MenuMarquee + shorten/rcell/mask_secret/fit_table_columns/filter_fuzzy
  app.tcss     全局样式：单行 Button、模态三段式、.tbl(focus round)、.panel、.page-hint、状态栏语义色
  config.py    配置目录/加载保存/默模板 + 定价策略标准暴露入口（pricing_strategies_for/default_pricing/label）
  core.py      数据层：抓取、路由加权期望价、场景成本、表格装配（返回 {headers, rows} 单元格 {text,dir,value}）
  pricing_scrapers/  各官方定价抓取器 + base（统一接口 + 降级快照 + PRICING_STRATEGIES）+ html_table（纯标准库解析）
  screens/
    dashboard.py  根屏：DashboardScreen(PageScreen) 承载 TabbedContent（总览 + 每组一 tab）+ SortTable（cell 光标 / s 排序）+ 两段式 rebuild
    settings.py   设置页：SettingsScreen(PageScreen)，Tabbed(常规/场景/对比组)；InputModal 重命名、ModelFormModal(FormModal 子类) 编辑、ConfirmModal 删除
    setup.py      首启向导：SetupScreen(ModalScreen[str]) 三段式，返回 default/blank/cancel
```

## 本项目差异登记（对第一部分规范的有意偏离）

- **根屏 = 看板，无首页菜单**：启动直接进入 `DashboardScreen` 看数据（`config.py` 缺失时才进 `SetupScreen` 向导）。因此**不使用** `ui.LOGO_LINES` / 首页居中版式 / `MenuMarquee`（这些是 controller 首页菜单专用）。
- **TabbedContent 是允许的**：看板用 `TabbedContent`（总览 + 每模型 tab）做多视图横向/纵向对比，属本项目核心交互，不作强制拆除。设置页内部同样用 Tabbed 分「常规/场景/对比组」。
- **表格纵向堆叠、高度 auto**：看板每张表 `.tbl` 为 `height: auto` 依次堆叠在 `.pane`（`VerticalScroll`）里，滚动条在 `.pane`；**不套用** controller 的「单表 1fr + 全页仅一个滚动条」。`fit_table_columns` 在此不强制（列宽自适应）。
- **单元格光标排序**：看板表格 `cursor_type="cell"`，`←→` 选列、`s`（或点表头）就地排序（`SortTable`，排序键随 `as_cell` 携带）。这是 controller 没有的交互，保留。
- **切页键位**：`[` `]` 上一个/下一个 tab、`g` 回总览、`1-9` 直达第 N 个 tab（overview 为第 1 个）——均 `priority=True`，覆盖表格焦点。

## 统一后的键位总表（本项目实际）

| 键 | 行为 |
|---|---|
| `Ctrl+Q` | 任意界面退出（App priority 绑定） |
| `Esc` / `Ctrl+C` | 层级回退：浮层 > 模态 > 返回；看板根屏 = **退出程序**；设置页 = 放弃返回（有改动先确认） |
| `Ctrl+R` | 看板/设置页刷新（看板重新抓取） |
| `Ctrl+S` | 打开设置页（App priority，任意界面可用；已在设置页则忽略） |
| `[` `]` / `g` / `1-9` | 看板切 tab / 回总览 / 直达 |
| `↑↓←→` | 表格单元格光标移动（`←→` 选列） |
| `s` | 按光标列排序（等价点表头，再按反向） |
| 单击表头 | 按该列排序，再点反向 |

- **无 `q` 绑定**（退出统一 `Ctrl+Q` / `Esc`）、**无 `r`**（刷新统一 `Ctrl+R`）。
- 看板根屏 `HINT`：`[ ] 切页 · g 总览 · 1-9 直达 · ←→ 选列 · s 排序 · Ctrl+R 刷新 · Ctrl+S 设置 · Esc/Ctrl+C 退出`。

## 状态栏 / 取数并发

- `app.status(msg, kind)` / `notify_ok/err/warn`（`kind ∈ ""|ok|warn|err` → 主题 `$success/$warning/$error`）。看板副标题（模型数 · OR 版本数 · 汇率 · 时间）走 `PageScreen.set_subtitle()`，非状态栏。
- **两段式加载**：`load_data` 先并发拉 headline + 官方价秒出图（`pending_expected` 时状态栏 ⏳ 提示），再并发拉全部端点重算期望价并 `rebuild(final=True)`。阻塞抓取一律 `asyncio.to_thread`，进度 `log` 经 `call_from_thread` 投回 UI。
- **看板重建竞态规避（8.2.8 陷阱）**：两段式若与 `DashboardScreen.on_mount` 的自动重建并发，会对同一批 pane id 双重挂载 `ContentTabs`，触发 `validate_active` 抛 `No Tab with id '--content-tab-…'`。已改为：看板挂载后才由 `on_mount` 触发首次 `load_data`（保证 `_dashboard` 已回填），并给 `rebuild` 加 `_rebuilding` 互斥。

## 配置与文件

- 配置查找：位置参数 `config` > 当前目录 `config.yaml` > `<配置目录>/config.yaml`；目录优先级 `-D/--dir` > 环境变量 `LLM_PRICE_COMPARE_CONFIG_DIR` > `~/.config/llm-price-compare`。`main.py` 在导入 `app` 前写环境变量。
- `config.yaml`：`exchange_rate.usd_to_cny` + `scenarios[]`（`name`/`tokens{cache_read,cache_write,input,output}`，占比和须为 1.0）+ `groups[]`（`display_name` + `models[{name,id,type,pricing}]`）。`type` 决定取价来源，`pricing` 策略由各来源标准暴露（openrouter: lowest/expected；deepseek: peak/valley/auto；其余 official）。

## 验证（本项目脚本）

- `/tmp/opencode/lpc_ui_check.py`（32 断言）：假 `core.build_snapshot`/`fetch_*` 屏蔽网络，覆盖 外框无 Header/Footer、topbar/status/page-hint、两段式渲染与副标题、cell 光标、单行按钮、`.tbl:focus` round、切页(2/g/])、`s` 排序、Ctrl+S 进设置、新建组、`ModelFormModal`(切换 type 动态刷新定价策略)、`InputModal` 重命名、`ConfirmModal`(危险项 error 变体/默认不放行)、未保存返回确认、Ctrl+Q；另跑 90×28 窄屏冒烟。
- 做法：`LLM_PRICE_COMPARE_CONFIG_DIR` 指向 `tempfile.mkdtemp()` 并写 `config.yaml`；monkeypatch `core.fetch_openrouter_models/fetch_endpoints_many` 返回 `{}`、`core.build_snapshot` 返回伪造 `Snapshot`（第一次 `pending_expected=True`，之后 False）。

## 提交

- 不要执行 `git commit` 等写操作，由用户自行提交。
