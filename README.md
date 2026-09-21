# LLM Price Compare

自动抓取**官方定价**并与 **OpenRouter 各供应商版本**横向对比的终端 TUI 工具，按自定义使用场景测算真实成本。

配置里**只需填模型名，无需手填任何价格** —— 官方价与 OpenRouter 价全部在运行时当场抓取。

## 为什么需要它

- OpenRouter 上同一个模型往往有多家供应商，**价差可以到几倍**，但页面上只给你一个 headline 最低价。
- headline 价 ≠ 你实际会付的价：OpenRouter 默认路由按价格与可用率分流，真实单价是各供应商的**加权期望**。
- 单价高低也不等于总成本高低：对缓存命中率极高的 agent 场景（如 Claude Code，85% 的 token 是缓存读取），缓存价权重远大于输入输出价，排序结论可能整个翻过来。
- 官方价散落在各家文档页、还经常变动。本工具内置各家官方定价抓取器，启动即自动同步，免去手工维护 `reference_price`。

所以这个工具同时给你三张视图：**单价对比**、**期望价（按默认路由算）**、**场景成本排名**。

## 安装

作为标准 Python 包发布，推荐用 [pipx](https://pipx.pypa.io/) 隔离安装：

```bash
pipx install llm-price-compare       # 从 PyPI（发布后）
pipx install .                       # 从本地源码
```

或用 pip（建议在虚拟环境内）：

```bash
python -m venv venv
./venv/bin/pip install .
```

要求 Python ≥ 3.9，终端支持 256 色 / 真彩色。

## 运行

```bash
llm-price                       # 自动定位配置（见下）
llm-price path/to/config.yaml   # 显式指定配置文件
llm-price -D /path/dir          # 指定配置目录（写环境变量 LLM_PRICE_COMPARE_CONFIG_DIR）
llm-price --version
```

**首次运行**若目标配置文件不存在，会先进入**配置向导**（三段式模态）：选择「推荐内置对比组」或「空白」，设置汇率后写盘。选「空白」时会接着进入设置页并给出去噪引导，带你亲手添加第一个对比组。之后每次启动直接进入看板界面。

配置查找顺序：位置参数 `config` > 当前目录 `config.yaml` > 用户配置 `~/.config/llm-price-compare/config.yaml`。配置目录优先级：`-D/--dir` > 环境变量 `LLM_PRICE_COMPARE_CONFIG_DIR` > `~/.config/llm-price-compare`。

界面里随时按 `Ctrl+S` 打开**设置页**（Tabbed：常规 / 场景 / 对比组），可视化增删改汇率、场景、对比组与模型条目；保存后自动重新抓取并热刷新，无需退出或手改文件。设置页遵循统一交互：

- **对比组**：左侧列表**单击切换**当前组、`[✎ 重命名]` 按钮（InputModal）改名；右侧模型条目**单击选择** + `[✎ 编辑]` 按钮（或 `Enter`）进入编辑。
- **删除**：`[🗑 删除]`（组 / 模型）会弹 `ConfirmModal` 二次确认（危险项默认不回车放行）。**未保存**时 `Esc` / `[放弃]` 返回会先弹确认。
- **场景**：每个 token 占比带**可见字段名**并以**百分比**显示（如 `85%`，输入 `85` 或 `85%` 均可，存储仍是 `0.85`）。
- **模型**：定价策略下拉**随来源类型动态生成**（FormModal 内切换来源即刷新）——选 DeepSeek 给出「峰价 / 谷价 / 自动」，选其他官方来源给出其自身策略，选 OpenRouter 为「最低 / 期望」。


启动后立即开始拉取数据并计算，无需任何操作。

界面大概长这样（真实数据，↑↓ 在原界面中带红绿配色）：

```text
◀ 退出  LLM 价格对比  4 个模型 · 7 个 OR 版本 · 汇率 6.71 · 20:13:42            [🔄 刷新] [⚙️ 设置]
📊 总览 │ DeepSeek V4 Flash │ Xiaomi MiMo V2.5 │ Zhipu GLM 5.3 Flash │ Qwen3.8 Flash

╭─ 📊 基础价横向对比（输入 + 输出 直算口径）───────────────────────────────────────────╮
│ 模型                 版本数  官方价(输入/输出)   最优 OR(输入/输出)  节省   最优版本          │
│ DeepSeek V4 Flash    4      ¥2.00 / ¥8.00      ¥0.27 / ¥0.67      ↓89%  V4F Latest* (期望)  │
│ Xiaomi MiMo V2.5     1      ¥1.00 / ¥2.00      ¥0.89 / ¥1.78      ↓11%  MiMo V2.5* (期望)   │
│ Zhipu GLM 5.3 Flash  2      ¥0.80 / ¥2.80      ¥0.64 / ¥2.12      ↓26%  GLM 5.3F* (期望)    │
│ Qwen3.8 Flash        1      ¥0.80 / ¥2.70      ¥1.01 / ¥3.15      ↑22%  Qwen3.8 Flash*(期望) │
╰──────────────────────────────────────────────────────────────────────────────────────────╯
```

## 界面结构

| Tab | 内容 |
| --- | --- |
| **📊 总览** | ① 各模型基础价横向对比（官方价 vs 最优 OpenRouter 版本）<br>② 每个场景一张跨模型成本表 |
| **每个模型一个 tab** | ① 官方 + 各版本四个维度的价格对比<br>② 每个场景下的成本排名（🏆 标记最低）<br>③ 供应商端点明细：各家报价、路由权重、量化方式、30 分钟可用率 |

模型 tab 内可以用下拉框切换要查看哪个版本的端点明细。

### 快捷键

| 按键 | 作用 |
| --- | --- |
| `Ctrl+R` | 重新拉取并计算 |
| `Ctrl+S` | 打开设置页（增删改汇率 / 场景 / 对比组 / 模型） |
| `[` / `]` | 上一个 / 下一个 tab |
| `1` … `9` | 跳到第 N 个 tab（总览为第 1 个） |
| `g` | 回到总览 |
| `↑ ↓ ← →` | 表格内移动光标（cell 光标，可左右移到目标列） |
| `s` | 按当前光标列排序（等价于点击表头，再按反向） |
| 单击表头 | 按该列排序，再点一次反向 |
| `Esc` / `Ctrl+C` | 层级回退：关闭浮层 / 模态 / 返回；**看板根屏为退出**，设置页为放弃返回（有改动先确认） |
| `Ctrl+Q` | **任意界面**直接退出程序 |

- 遵循四项目统一键位：**无 `q`**（退出走 `Ctrl+Q` / `Esc`）、**无 `r`**（刷新走 `Ctrl+R`）。看板根屏 `Esc` 等同退出。

价格单元格相对**官方价**着色：绿 = 更便宜，红 = 更贵，并附 `↑/↓` 箭头（色盲友好，不依赖单色）。名称后的 `*` 表示该数字是期望价。排序有键盘路径（`←→` 选列、`s` 排序），不依赖鼠标，适配 SSH / tmux。

## 配置

模型价格全自动抓取，配置里只声明"比哪些模型、用哪家来源"：

```yaml
exchange_rate:
  usd_to_cny: 6.71          # OpenRouter 报价是美元，这里换成人民币

scenarios:                  # 场景 = 一次请求里各类 token 的占比，总和必须为 1.0
  - name: "Claude Code"
    description: "长上下文 agent，缓存命中极高"   # 可选
    tokens:
      cache_read: 0.85
      cache_write: 0.10
      input: 0.04
      output: 0.01

groups:                     # 每个 group = 一个对比 tab
  - display_name: "DeepSeek V4.1 Flash"
    models:
      - name: "DeepSeek 官方"           # 官方模型：只填 id + type，价格自动抓取
        id: "deepseek-flash"
        type: "deepseek"               # 定价来源：deepseek/zhipu/alibaba/xiaomi/kimi
        pricing: "auto"                # 可选：来源自带的取价策略（DeepSeek: peak/valley/auto，缺省 auto）
      - name: "OpenRouter"
        id: "deepseek/deepseek-4.1-flash"   # OpenRouter 模型 id（~ 前缀表示聚合 id）
        type: "openrouter"             # 定价来源为 openrouter
        pricing: "expected"            # openrouter: lowest | expected，缺省 lowest
```

组内**第一个官方模型**（`type` 非 `openrouter`）即作为该 tab 的参考基准价；若组内没有官方模型，则取第一个条目作基准。`pricing` 字段的可选值由对应来源**标准暴露**（见下）：OpenRouter 为 `lowest/expected`；DeepSeek 为 `peak/valley/auto`；其余官方来源目前只有一种「官方价」。


## 官方定价自动抓取

`type` 决定价格从哪来。非 `openrouter` 的来源由 `llm_price_compare/pricing_scrapers/` 内对应抓取器在启动时并发抓取：

| type | 来源 | 抓取方式 |
| --- | --- | --- |
| `deepseek` | api-docs.deepseek.com | 解析定价页 HTML 表格（含峰/谷双时段 → `peak/valley/auto`） |
| `zhipu` | docs.bigmodel.cn | 解析定价页 HTML 表格 |
| `alibaba` | bailian.console.aliyun.com | 解析百炼中国内地 Qwen 定价 |
| `xiaomi` | mimo.mi.com | 解析按量计费页表格（国内价） |
| `kimi` | platform.kimi.com | 解析 chat 定价页内嵌数据 |
| `openrouter` | openrouter.ai/api/v1 | 官方 REST API（headline / endpoints） |

**健壮性**：抓取器输出统一的结构化格式（`input/output/cache_read/cache_write`）。若某页面改版导致解析失败，会自动回退到该提供商内置的定价快照，并在状态栏提示「⚠️ 使用降级数据」，程序绝不因此崩溃。

## 定价策略（按来源标准暴露）

每个定价来源通过统一接口 `pricing_strategies()` 声明自己支持的取价策略，设置页下拉与 `pricing` 字段都据此动态生成，不再硬编码。

**OpenRouter**（`type: openrouter`）：

| 策略 | 含义 | 数据来源 |
| --- | --- | --- |
| `lowest` | 全体供应商中的最低价，即 OpenRouter 页面展示价 | `GET /api/v1/models` |
| `expected` | 按 OpenRouter 默认路由算法估算的期望单价 | `GET /api/v1/models/{id}/endpoints` |

期望价的算法：

$$w_i = \frac{1}{P_{input,i}^{\,2}} \times uptime_i \qquad\Longrightarrow\qquad E[P_k] = \frac{\sum_i w_i P_{k,i}}{\sum_i w_i}$$

即价格越低、可用性越高的供应商拿到越大的路由权重（价格的**平方**反比），再对输入 / 输出 / 缓存读 / 缓存写四个维度分别用同一组权重求加权平均。已下架或无报价的供应商不参与计算。若端点数据缺失或全部不可用，自动回退到 `lowest` 并标注 `⚠️ 端点无可用价格，已回退最低价`。

**官方来源**：目前 DeepSeek 定价页把每个价类拆成「高峰 / 空闲」两行，抓取器据此暴露三种策略：

| 策略 | 含义 |
| --- | --- |
| `peak` | 高峰时段价 |
| `valley` | 空闲时段价（官方恒为峰价一半） |
| `auto` | 按**当前北京时间(UTC+8)**自动取峰或谷：周一至周五 09:00–12:00、14:00–18:00 为峰，其余（含周末、夜间）为谷 |

其余官方来源（智谱 / 小米 / Kimi / 阿里）目前只有单一「官方价」，下拉里即那一项。峰谷价由抓取器**逐格解析两组真实价**（不靠峰价÷2 推算，防止官方未来改折扣规则；谷价缺失时才回落折半）。

## 加载行为

数据分两段加载，因为 OpenRouter 的端点接口较慢：

1. **第一阶段**（约 3s）：并发拉取 `/models` headline 价 + 各官方提供商定价，界面立刻可看；此时 `expected` 模型暂以最低价估算，总览顶部提示「期望价计算中」。
2. **第二阶段**：并发拉取全部端点数据，重算期望价并刷新界面。

底部状态栏实时显示进度。网络失败时保留已有视图并提示原因，不会白屏。

## 终端与主题

**终端真彩前置**（本项目常在 SSH + tmux 里跑，缺这些 Textual 会静默降级配色，误以为"主题坏了"）：

```bash
# ~/.tmux.conf
set -g default-terminal "tmux-256color"
set -ga terminal-overrides ",*:RGB"

export COLORTERM=truecolor
```

**颜色分两类，刻意区别对待**：

- **数据编码色**（表格涨跌的绿/红）：在 `screens/dashboard.py` 的 `DIR_COLOR` 里固定为具体色值，**不随主题变**——它编码"相对官方价更贵/更便宜"的数值语义，需在任意主题与截图下保持一致；且已配 `↑/↓` 箭头作非颜色冗余，不靠单色区分。
- **UI 状态色**（底部状态栏 `✅/⏳/❌`）：走主题的 `$success/$warning/$error`（见 `app.tcss` 的 `#status.ok/.warn/.err`），随主题切换。

Textual 自带主题切换：本项目已关闭命令面板（`ENABLE_COMMAND_PALETTE = False`，与三项目一致），换主题可在 `App()` 上用 `app.theme = "tokyo-night"` 等方式，或改代码验证观感。tab 标题刻意不放 emoji（CJK/emoji 双宽在不同终端实现不一，会影响 tab 宽度与下划线定位）。

## 项目结构

```text
llm_price_compare/
├── __init__.py            # 仅 __version__（轻量入口，避免 runpy 双导入告警）
├── main.py                # CLI：config 位置参数 + -D/--dir + --version，写环境变量后启动 App
├── app.py                 # PriceCompareApp：无 Header/Footer、#status、两段式 load_data、Ctrl+Q/Ctrl+S、notify
├── ui.py                  # 界面骨架 PageScreen（顶栏 / #page / HintBar / 折叠菜单）
├── widgets.py             # 共享模态与表格辅助（与三项目同一份：Confirm/Input/Form/OutputModal、ClickTable、HintBar、shorten…）
├── app.tcss               # 全局样式：单行按钮、模态三段式、.tbl(focus round)、.panel、状态栏（随包分发）
├── core.py                # 数据层：抓取、算价、装配表格（无 UI / print）
├── config.py              # 配置目录管理、加载/保存、默认模板、定价策略标准暴露入口
├── screens/
│   ├── dashboard.py       # 根屏看板：TabbedContent（总览 + 每组一 tab）+ SortTable（cell 光标 / s 排序）+ 两段式 rebuild
│   ├── settings.py        # 设置页（PageScreen）：常规/场景/对比组，InputModal 重命名 · FormModal 编辑 · ConfirmModal 删除
│   └── setup.py           # 首启向导（ModalScreen，三段式）
└── pricing_scrapers/       # 各官方提供商定价抓取器
    ├── base.py             # 统一接口 + 降级框架 + PRICING_STRATEGIES
    ├── html_table.py       # 纯标准库 HTML 表格解析器
    ├── deepseek.py / zhipu.py / alibaba.py / xiaomi.py / kimi.py
    └── __init__.py         # PROVIDER_SCRAPERS 注册表 + get_scraper() 工厂
```

`core.build_*_table()` 统一返回 `{headers, rows}`，每个单元格是：

```python
{"text": "¥0.27 ↓89%",   # 显示文本
 "dir": -1,              # 相对参考价方向：-1 更便宜 / 0 持平 / 1 更贵
 "value": 0.2742}        # 可排序的原始值
```

界面只负责按 `dir` 上色、按 `value` 排序，所有业务判断都在 `core.py` 里，便于单独测试或复用。

## 开发与打包

```bash
ruff check llm_price_compare/     # lint（规则见 pyproject.toml [tool.ruff]）
python -m build                   # 产出 dist/ 下的 wheel 与 sdist
```

推送 `v*` 标签时，`.github/workflows/release.yml` 会自动构建并发布到 PyPI、创建 GitHub Release。
