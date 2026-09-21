#!/usr/bin/env python3
"""
core.py — 模型价格比较的数据层

职责：抓取 OpenRouter 数据 + 计算价格，产出结构化 Snapshot。
本模块 **不做任何 print / UI 渲染**，进度信息通过 log 回调外派，
界面层 (main.py) 只消费这里产出的结构化结果。

同时保留了原脚本的两种定价策略：
  - lowest   : headline 价（全体供应商中的最低价）
  - expected : 默认路由加权期望价
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

try:
    from .config import get_default_config_path, load_config
    from .pricing_scrapers import get_scraper
except ImportError:
    from config import get_default_config_path, load_config
    from pricing_scrapers import get_scraper

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model_id}/endpoints"

# 价格维度（顺序即表格行顺序，与原脚本一致）
PRICE_TYPES: list[tuple[str, str]] = [
    ("input", "输入"),
    ("output", "输出"),
    ("cache_read", "缓存读取"),
    ("cache_write", "缓存写入"),
]

STRATEGY_LABELS = {"lowest": "最低", "expected": "期望", "official": "官方"}

# endpoints_mode 取值
ENDPOINTS_EXPECTED_ONLY = "expected_only"   # 仅对 pricing=expected 的模型拉端点（原脚本行为）
ENDPOINTS_ALL = "all"                       # 对所有模型拉端点（TUI 需要明细）
ENDPOINTS_NONE = "none"                     # 不拉端点（两段式加载的第一阶段，或外部已预取）

def NoopLog(_msg: str) -> None:
    return None


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #

@dataclass
class ModelPrice:
    """一个可比价的条目：官方版或某个 OpenRouter 版本"""

    name: str                      # 显示名（"官方" / "V4F 0423"）
    model_id: str                  # OpenRouter id，官方版为官方模型名
    strategy: str                  # official | lowest | expected
    prices_cny: dict = field(default_factory=dict)   # 生效价格（场景计算用）
    prices_usd: dict = field(default_factory=dict)
    headline_cny: dict | None = None              # 最低价（如有）
    expected_cny: dict | None = None              # 期望价（如有）
    source: str = ""               # headline | expected | fallback_headline | config
    note: str = ""                 # 人类可读备注（例如端点数据缺失已回退）

    @property
    def label(self) -> str:
        """带策略标记的名称，'*' 表示基于期望价"""
        return f"{self.name}*" if self.strategy == "expected" else self.name


@dataclass
class EndpointRow:
    """单个供应商端点的明细"""

    provider: str
    endpoint_name: str
    quantization: str
    context_length: int
    prices_cny: dict
    weight_pct: float          # 在路由中的权重百分比（0 表示未被纳入）
    uptime_30m: float | None
    status: int
    healthy: bool
    included: bool             # 是否参与了期望价计算
    discount: float


@dataclass
class ScenarioRanking:
    """某个场景下，该模型所有版本按成本升序排名"""

    scenario: dict
    rows: list[tuple[ModelPrice, float]] = field(default_factory=list)
    skipped_reason: str = ""   # 比例总和不为 1 时的提示


@dataclass
class PairSnapshot:
    """一个同步对（一个模型家族）的完整结果"""

    display_name: str
    official_modelname: str
    reference_cny: dict
    official: ModelPrice | None
    versions: list[ModelPrice] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)      # (name, id)
    endpoints: dict[str, list[EndpointRow]] = field(default_factory=dict)  # key=model_id
    endpoints_fetched: dict[str, bool] = field(default_factory=dict)
    scenarios: list[ScenarioRanking] = field(default_factory=list)

    @property
    def entries(self) -> list[ModelPrice]:
        """官方 + 各版本，按原价顺序"""
        out: list[ModelPrice] = []
        if self.official is not None:
            out.append(self.official)
        out.extend(self.versions)
        return out


@dataclass
class Snapshot:
    """一次完整运行的全部结果"""

    exchange_rate: float
    scenarios: list[dict]
    pairs: list[PairSnapshot]
    headline_count: int
    fetched_at: datetime
    config_path: str
    pending_expected: bool = False   # True 表示期望价尚未计算（仅 headline 价）


# --------------------------------------------------------------------------- #
# 抓取
# --------------------------------------------------------------------------- #

def _build_session() -> requests.Session:
    """共用一个带连接池的 Session。

    不复用连接时，每个请求都要重新走代理做 TLS 握手，实测单个可耗 13~26s；
    复用后同一批请求降到秒级。
    """
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=16)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "llm-price-compare/1.0"})
    return session


_SESSION = _build_session()


def _request_json(url: str, *, timeout: int = 20, retries: int = 3):
    """GET 并解析 JSON。

    返回完整响应信封 dict / None(404) / raise 最后一次异常。
    对网络抖动做指数退避重试——这台机器走 mihomo 代理时容易超时。
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            response = _SESSION.get(url, timeout=timeout)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception as exc:                      # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(0.6 * (2 ** attempt))
    raise last_exc  # type: ignore[misc]


def fetch_openrouter_models(*, log: Callable[[str], None] = NoopLog) -> dict:
    """获取所有模型 headline 信息，返回 {model_id: model_data}"""
    try:
        envelope = _request_json(OPENROUTER_MODELS_URL) or {}
        return {m["id"]: m for m in envelope.get("data", [])}
    except Exception as e:                            # noqa: BLE001
        log(f"❌ 获取 OpenRouter 模型列表失败: {e}")
        return {}


def fetch_model_endpoints(model_id: str, *, retries: int = 3, timeout: int = 12) -> dict | None:
    """获取某个模型的全部供应商端点（返回响应中的 data 层，与原脚本一致）"""
    try:
        envelope = _request_json(
            OPENROUTER_ENDPOINTS_URL.format(model_id=model_id),
            retries=retries,
            timeout=timeout,
        )
    except Exception:                                 # noqa: BLE001
        return None
    if envelope is None:                              # 404
        return None
    return envelope.get("data")


# --------------------------------------------------------------------------- #
# 价格解析与计算（数学逻辑与原脚本完全一致）
# --------------------------------------------------------------------------- #

def to_per_million(price_str) -> float:
    """美元/token 字符串 → 美元/百万 token"""
    if price_str is None:
        return 0.0
    try:
        return float(price_str) * 1_000_000
    except (ValueError, TypeError):
        return 0.0


def extract_headline_prices(model_data: dict) -> dict:
    """headline 价（美元/百万 token）。cache_* 缺省时等于 input 价。"""
    pricing = model_data.get("pricing", {})

    input_price = to_per_million(pricing.get("prompt"))
    output_price = to_per_million(pricing.get("completion"))

    if pricing.get("input_cache_read") is not None:
        cache_read = to_per_million(pricing.get("input_cache_read"))
    else:
        cache_read = input_price

    if pricing.get("input_cache_write") is not None:
        cache_write = to_per_million(pricing.get("input_cache_write"))
    else:
        cache_write = input_price

    return {
        "input": input_price,
        "output": output_price,
        "cache_read": cache_read,
        "cache_write": cache_write,
    }


# API 字段 ↔ 内部价格维度
API_PRICE_FIELDS = {
    "input": "prompt",
    "output": "completion",
    "cache_read": "input_cache_read",
    "cache_write": "input_cache_write",
}


def route_endpoints(endpoints_data: dict):
    """复刻 OpenRouter 默认路由权重，返回 (healthy_endpoints, weights, skipped)

    权重公式: weight_i = (1 / effective_input_price_i^2) * uptime_ratio_i
    """
    endpoints = endpoints_data.get("endpoints", [])
    if not endpoints:
        return [], [], []

    healthy: list[dict] = []
    weights: list[float] = []
    skipped: list[tuple[dict, str]] = []

    for ep in endpoints:
        if ep.get("status", 0) != 0:
            skipped.append((ep, "unhealthy"))
            continue

        pricing = ep.get("pricing", {})
        raw_input_price = pricing.get("prompt")
        if raw_input_price is None:
            skipped.append((ep, "no_price"))
            continue

        input_price = to_per_million(raw_input_price)
        if input_price <= 0:
            skipped.append((ep, "zero_price"))
            continue

        discount = pricing.get("discount", 0) or 0
        effective_input = input_price * (1 - discount)
        if effective_input <= 0:
            skipped.append((ep, "zero_after_discount"))
            continue

        uptime = ep.get("uptime_last_30m")
        if uptime is None:
            uptime = 100
        uptime_ratio = uptime / 100.0

        healthy.append(ep)
        weights.append((1.0 / (effective_input ** 2)) * uptime_ratio)

    return healthy, weights, skipped


def endpoint_expected_price(ep: dict, price_key: str) -> float | None:
    """某端点在指定维度的有效美元价（含折扣，cache_* 缺省回落到 prompt）"""
    pricing = ep.get("pricing", {})
    raw = pricing.get(API_PRICE_FIELDS[price_key])
    if raw is None:
        raw = pricing.get("prompt")
    if raw is None:
        return None
    base = to_per_million(raw)
    if base <= 0:
        return None
    discount = pricing.get("discount", 0) or 0
    effective = base * (1 - discount)
    return effective if effective > 0 else None


def calc_expected_with_detail(
    endpoints_data: dict, *, exchange_rate: float = 1.0
) -> tuple[dict | None, list[EndpointRow]]:
    """计算期望价，同时返回端点明细（供 TUI 展示路由构成）

    数学与原 calc_expected_prices 完全一致：
      expected[k] = Σ(effective_price_ik * w_i) / Σ(w_i)
    """
    healthy, weights, skipped = route_endpoints(endpoints_data)
    if not weights:
        return None, []

    total_weight = sum(weights)
    if total_weight <= 0:
        return None, []

    expected: dict[str, float] = {}
    for price_key in API_PRICE_FIELDS:
        weighted_sum = 0.0
        for ep, weight in zip(healthy, weights):
            effective = endpoint_expected_price(ep, price_key)
            if effective is None:
                continue
            weighted_sum += effective * weight
        expected[price_key] = weighted_sum / total_weight

    if not any(v > 0 for v in expected.values()):
        return None, []

    rows: list[EndpointRow] = []
    for ep, weight in zip(healthy, weights):
        per_price = {}
        for key in API_PRICE_FIELDS:
            effective = endpoint_expected_price(ep, key)
            if effective is None:
                effective = to_per_million(ep.get("pricing", {}).get("prompt"))
            per_price[key] = effective * exchange_rate
        rows.append(
            EndpointRow(
                provider=ep.get("provider_name", "?"),
                endpoint_name=ep.get("name", ""),
                quantization=ep.get("quantization", "") or "-",
                context_length=ep.get("context_length") or 0,
                prices_cny=per_price,
                weight_pct=weight / total_weight * 100.0,
                uptime_30m=ep.get("uptime_last_30m"),
                status=ep.get("status", 0),
                healthy=True,
                included=True,
                discount=ep.get("pricing", {}).get("discount", 0) or 0,
            )
        )
    for ep, _reason in skipped:
        pricing = ep.get("pricing", {})
        rows.append(
            EndpointRow(
                provider=ep.get("provider_name", "?"),
                endpoint_name=ep.get("name", ""),
                quantization=ep.get("quantization", "") or "-",
                context_length=ep.get("context_length") or 0,
                prices_cny={
                    k: to_per_million(pricing.get(API_PRICE_FIELDS[k])) * exchange_rate
                    for k in API_PRICE_FIELDS
                },
                weight_pct=0.0,
                uptime_30m=ep.get("uptime_last_30m"),
                status=ep.get("status", 0),
                healthy=False,
                included=False,
                discount=pricing.get("discount", 0) or 0,
            )
        )

    rows.sort(key=lambda r: (-r.weight_pct, r.provider))
    return expected, rows


def calc_expected_prices(endpoints_data: dict) -> dict | None:
    """期望价（美元/百万 token）——保持与原脚本同名的公开入口"""
    expected, _ = calc_expected_with_detail(endpoints_data)
    return expected


def fetch_endpoints_many(
    model_ids: list[str],
    *,
    log: Callable[[str], None] = NoopLog,
    max_workers: int = 8,
) -> dict:
    """并发拉取多个模型的端点数据。

    输出顺序仍按传入顺序（即 config 顺序）打印，保证与串行版本文本一致，
    但总耗时从“累加”变为“取最慢一个”。
    """
    if not model_ids:
        return {}
    if len(model_ids) == 1:
        data = fetch_model_endpoints(model_ids[0])
        log(f"   {'✅' if data else '❌'} {model_ids[0]}")
        return {model_ids[0]: data}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(model_ids))) as pool:
        futures = [pool.submit(fetch_model_endpoints, mid) for mid in model_ids]
        results: dict[str, dict | None] = {}
        for mid, future in zip(model_ids, futures):
            data = future.result()
            results[mid] = data
            log(f"   {'✅' if data else '❌'} {mid}")
    return results


def normalize_prices(prices: dict) -> dict:
    """cache_* 未设置 → 等于 input 价；显式为 0 → 保持 0（免费）"""
    p = dict(prices)
    input_price = p.get("input", 0)
    if p.get("cache_write") is None:
        p["cache_write"] = input_price
    if p.get("cache_read") is None:
        p["cache_read"] = input_price
    return p


def get_model_prices(
    model_id: str, strategy: str, or_models: dict, endpoints_cache: dict
) -> dict | None:
    """按策略取价（美元/百万 token），保留以兼容原调用方"""
    detail = resolve_model_price(model_id, strategy, or_models, endpoints_cache)
    return detail["usd"] if detail else None


def resolve_model_price(
    model_id: str, strategy: str, or_models: dict, endpoints_cache: dict, *, allow_fetch: bool = True
) -> dict | None:
    """返回 {usd, source, note} —— 含与原脚本一致的回退链

    allow_fetch=False 用于外部已预取端点的场景（两段式加载），
    此时缓存未命中不触发网络请求，而是回退到 headline 价并标注 pending。
    """
    model_data = or_models.get(model_id)
    headline = extract_headline_prices(model_data) if model_data is not None else None

    if strategy == "expected":
        if model_id not in endpoints_cache:
            if not allow_fetch:
                if headline is None:
                    return None
                return {
                    "usd": headline,
                    "source": "pending_headline",
                    "note": "端点数据尚未加载，暂以最低价估算",
                }
            endpoints_cache[model_id] = fetch_model_endpoints(model_id)
        endpoints_data = endpoints_cache[model_id]
        if endpoints_data is not None:
            expected = calc_expected_prices(endpoints_data)
            if expected is not None:
                return {"usd": expected, "source": "expected", "note": ""}
        if headline is None:
            return None
        note = "无端点数据，已回退最低价" if endpoints_data is None else "端点无可用价格，已回退最低价"
        return {"usd": headline, "source": "fallback_headline", "note": note}

    # lowest / 未知策略 → headline
    if headline is None:
        return None
    return {"usd": headline, "source": "headline", "note": ""}


def calc_scenario_cost(prices_cny: dict, scenario_tokens: dict) -> float:
    cost = 0.0
    for token_type, ratio in scenario_tokens.items():
        cost += prices_cny.get(token_type, 0) * ratio
    return cost


# --------------------------------------------------------------------------- #
# 展示辅助（纯格式化，无副作用；CLI 与 TUI 共用）
# --------------------------------------------------------------------------- #

def format_price(price: float) -> str:
    if price == 0:
        return "免费"
    if price < 0.001:
        return f"{price:.5f}"
    if price < 0.01:
        return f"{price:.4f}"
    if price < 1:
        return f"{price:.3f}"
    return f"{price:.2f}"


def format_strategy(s: str) -> str:
    return STRATEGY_LABELS.get(s, s)


def compare_cell(price: float, ref_price: float) -> tuple[str, int]:
    """相对参考价的单元格文本 + 方向（-1 降价 / 0 持平或不可比 / 1 涨价）

    与原脚本 print_comparison 的分支逻辑逐字对齐。
    """
    if price == 0:
        return "免费", 0
    if ref_price == 0:
        return f"¥{format_price(price)}", 0
    diff = price - ref_price
    if diff > 0:
        return f"¥{format_price(price)} ↑{abs(diff) / ref_price * 100:.0f}%", 1
    if diff < 0:
        return f"¥{format_price(price)} ↓{abs(diff) / ref_price * 100:.0f}%", -1
    return f"¥{format_price(price)}", 0


def official_cell(price: float) -> str:
    return "免费" if price == 0 else f"¥{format_price(price)}"


def saving_label(cost: float, max_cost: float, is_first: bool) -> str:
    """场景排名表中成本后的括注，与原脚本一致"""
    if max_cost <= 0:
        return ""
    savings = (1 - cost / max_cost) * 100
    if is_first:
        return f" (最便宜，省 {savings:.0f}%)" if savings > 5 else " (最便宜)"
    return f" (省 {savings:.0f}%)" if savings > 5 else ""


def scenario_ratio_str(tokens: dict) -> str:
    return (
        f"缓存读取 {tokens.get('cache_read', 0) * 100:.0f}% | "
        f"缓存写入 {tokens.get('cache_write', 0) * 100:.0f}% | "
        f"输入 {tokens.get('input', 0) * 100:.0f}% | "
        f"输出 {tokens.get('output', 0) * 100:.0f}%"
    )


# --------------------------------------------------------------------------- #
# 快照构建
# --------------------------------------------------------------------------- #

def fetch_all_official_pricing(providers: set[str], log: Callable[[str], None] = NoopLog) -> dict[str, dict]:
    """并发抓取所有需要的官方提供商的定价数据"""
    if not providers:
        return {}

    log(f"📡 抓取官方提供商定价: {', '.join(providers)}")
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, len(providers))) as pool:
        def fetch_one(p):
            try:
                scraper = get_scraper(p)
                res = scraper.fetch_pricing()
                return p, res
            except Exception as e:
                return p, {"models": [], "success": False, "error": str(e)}

        futures = [pool.submit(fetch_one, p) for p in providers]
        for f in futures:
            p, res = f.result()
            results[p] = res
            status = "✅" if res.get("success") else "⚠️ (使用降级数据)"
            log(f"   {status} {p.upper()}")
    return results


def collect_group_prices(
    group: dict,
    or_models: dict,
    official_pricing: dict[str, dict],
    exchange_rate: float,
    endpoints_cache: dict,
    *,
    allow_fetch: bool = True,
) -> tuple[list[ModelPrice], list[tuple[str, str]]]:
    """根据新的 groups 配置，收集组内所有模型的定价（含官方和 OpenRouter）"""
    all_models: list[ModelPrice] = []
    missing: list[tuple[str, str]] = []

    for m in group.get("models", []):
        model_id = m["id"]
        model_name = m["name"]
        mtype = m.get("type", "openrouter")

        if mtype == "openrouter":
            strategy = m.get("pricing", "lowest")
            resolved = resolve_model_price(
                model_id, strategy, or_models, endpoints_cache, allow_fetch=allow_fetch
            )
            if resolved is None:
                missing.append((model_name, model_id))
                continue

            prices_usd = resolved["usd"]
            model = ModelPrice(
                name=model_name,
                model_id=model_id,
                strategy=strategy,
                prices_usd=dict(prices_usd),
                prices_cny={k: v * exchange_rate for k, v in prices_usd.items()},
                source=resolved["source"],
                note=resolved["note"],
            )
            # 附带另一种定价
            model_data = or_models.get(model_id)
            if model_data is not None:
                hl = extract_headline_prices(model_data)
                model.headline_cny = {k: v * exchange_rate for k, v in hl.items()}
            if prices_usd and resolved["source"] == "expected":
                model.expected_cny = {k: v * exchange_rate for k, v in prices_usd.items()}
            all_models.append(model)
        else:
            # 官方提供商
            prov_data = official_pricing.get(mtype, {})
            model_pricing = None
            # 查找具体模型
            for model_item in prov_data.get("models", []):
                mid = model_item.get("model_id", "").lower().strip()
                mname = model_item.get("model_name", "").lower().strip()
                target = model_id.lower().strip()
                if target == mid or target == mname:
                    model_pricing = model_item
                    break
            if not model_pricing:
                # 模糊匹配
                for model_item in prov_data.get("models", []):
                    mid = model_item.get("model_id", "").lower().strip()
                    mname = model_item.get("model_name", "").lower().strip()
                    target = model_id.lower().strip()
                    if target in mid or mid in target or target in mname:
                        model_pricing = model_item
                        break

            if model_pricing:
                # 按该模型配置的取价策略（官方来源标准暴露，如 DeepSeek 峰/谷/自动）选价。
                variant = m.get("pricing")
                try:
                    prices_cny = get_scraper(mtype).select_prices(model_pricing, variant)
                except Exception:  # noqa: BLE001
                    prices_cny = {
                        "input": model_pricing.get("input_price", 0.0),
                        "output": model_pricing.get("output_price", 0.0),
                        "cache_read": model_pricing.get("cache_read_price", 0.0),
                        "cache_write": model_pricing.get("cache_write_price", 0.0),
                    }
                # cache_* 缺省回落：自动补全可能缺失的价格
                prices_cny = normalize_prices(prices_cny)


                model = ModelPrice(
                    name=model_name,
                    model_id=model_id,
                    strategy="official",
                    prices_cny=prices_cny,
                    prices_usd={k: v / exchange_rate for k, v in prices_cny.items()},
                    source=f"official_scraper_{mtype}",
                )
                all_models.append(model)
            else:
                missing.append((model_name, model_id))

    return all_models, missing


def collect_model_prices(
    sync_pair: dict,
    or_models: dict,
    exchange_rate: float,
    endpoints_cache: dict,
    *,
    allow_fetch: bool = True,
) -> tuple[list[ModelPrice], list[tuple[str, str]]]:
    """保留旧的接口，以便向下兼容"""
    # 模拟一个官方定价字典
    mock_official = {
        "deepseek": {"models": [{"model_id": sync_pair.get("official_modelname", ""), "model_name": "官方", "input_price": sync_pair.get("reference_price", {}).get("input", 0), "output_price": sync_pair.get("reference_price", {}).get("output", 0), "cache_read_price": sync_pair.get("reference_price", {}).get("cache_read", 0), "cache_write_price": sync_pair.get("reference_price", {}).get("cache_write", 0)}]}
    }
    group = {
        "models": [
            {"name": "官方", "id": sync_pair.get("official_modelname", ""), "type": "deepseek"},
        ]
    }
    for or_config in sync_pair.get("openrouter_models", []):
        group["models"].append({
            "name": or_config["name"],
            "id": or_config["id"],
            "type": "openrouter",
            "pricing": or_config.get("pricing", "lowest"),
        })

    return collect_group_prices(
        group, or_models, mock_official, exchange_rate, endpoints_cache, allow_fetch=allow_fetch
    )


def config_or_model_ids(config: dict | str) -> list[str]:
    """按 config 顺序返回全部 OpenRouter 模型 id（去重），供外部预取端点"""
    if isinstance(config, str):
        config = load_config(config)
    ids: list[str] = []
    # 兼容新版的 groups 结构
    for group in config.get("groups", []):
        for m in group.get("models", []):
            if m.get("type") == "openrouter" and m.get("id"):
                if m["id"] not in ids:
                    ids.append(m["id"])
    # 兼容旧版的 sync_pairs 结构
    for pair in config.get("sync_pairs", []):
        for or_config in pair.get("openrouter_models", []):
            if or_config["id"] not in ids:
                ids.append(or_config["id"])
    return ids


def build_snapshot(
    config_path: str | Path | None = None,
    *,
    log: Callable[[str], None] = NoopLog,
    endpoints_mode: str = ENDPOINTS_EXPECTED_ONLY,
    include_scenarios: bool = True,
    endpoints_cache: dict | None = None,
    or_models: dict | None = None,
) -> Snapshot:
    """执行一次完整流程，返回结构化快照。

    endpoints_cache / or_models 可由外部注入（两段式加载）：注入后不再
    发起对应请求，缓存未命中的 expected 模型会回退 headline 价并标记 pending。
    """
    if config_path is None:
        config_path = get_default_config_path()
    else:
        config_path = Path(config_path)

    log(f"🔧 加载配置: {config_path}")
    config = load_config(config_path)
    config_path_str = str(config_path)

    exchange_rate = config.get("exchange_rate", {}).get("usd_to_cny", 6.71)
    scenarios = config.get("scenarios", [])

    # 支持 groups 结构，同时向下兼容 sync_pairs
    groups = config.get("groups", [])
    if not groups and "sync_pairs" in config:
        # 将旧的 sync_pairs 转换为 groups 格式
        for pair in config.get("sync_pairs", []):
            models = [
                {"name": "官方", "id": pair.get("official_modelname", ""), "type": "deepseek"}
            ]
            for om in pair.get("openrouter_models", []):
                models.append({
                    "name": om["name"],
                    "id": om["id"],
                    "type": "openrouter",
                    "pricing": om.get("pricing", "lowest"),
                })
            groups.append({
                "display_name": pair["display_name"],
                "models": models,
            })

    if not groups:
        log("⚠️  未找到任何对比组 (groups) 配置")
        return Snapshot(exchange_rate, scenarios, [], 0, datetime.now(), config_path_str)

    if include_scenarios and scenarios:
        log(f"📋 场景: {len(scenarios)} 个 ({', '.join(s['name'] for s in scenarios)})")

    # 1. 找出所有需要的 OpenRouter 模型 ID
    wanted_or_ids: list[str] = []
    # 2. 找出所有需要的官方提供商类型 (deepseek, zhipu, alibaba 等)
    needed_providers: set[str] = set()

    for group in groups:
        for m in group.get("models", []):
            mtype = m.get("type", "openrouter")
            if mtype == "openrouter":
                strategy = m.get("pricing", "lowest")
                if endpoints_mode == ENDPOINTS_ALL or strategy == "expected":
                    if m["id"] not in wanted_or_ids:
                        wanted_or_ids.append(m["id"])
            else:
                needed_providers.add(mtype)

    needs_expected = wanted_or_ids

    # 并发拉取官方定价
    official_pricing = fetch_all_official_pricing(needed_providers, log=log)

    # 并发拉取 OpenRouter Headline
    if or_models is None:
        if needs_expected:
            log("📡 获取 OpenRouter headline 数据...")
        else:
            log("📡 从 OpenRouter 获取模型数据...")
        or_models = fetch_openrouter_models(log=log)
    if not or_models:
        log("❌ 无法获取 OpenRouter 模型数据")
        return Snapshot(exchange_rate, scenarios, [], 0, datetime.now(), config_path_str)
    log(f"✅ 获取到 {len(or_models)} 个 OpenRouter 模型")

    prefetched = endpoints_cache is not None
    endpoints_cache = dict(endpoints_cache or {})
    if not prefetched and needs_expected and endpoints_mode != ENDPOINTS_NONE:
        suffix = "(端点明细)" if endpoints_mode == ENDPOINTS_ALL else "(用于期望价计算)"
        log(f"📡 获取 {len(needs_expected)} 个模型的供应商端点数据 {suffix}...")
        endpoints_cache.update(fetch_endpoints_many(needs_expected, log=log))

    log(f"💱 汇率: 1 USD = {exchange_rate} CNY")

    pairs: list[PairSnapshot] = []
    for group in groups:
        entries, missing = collect_group_prices(
            group, or_models, official_pricing, exchange_rate, endpoints_cache
        )
        # 寻找官方条目作为基准
        official = next((e for e in entries if e.strategy == "official"), None)
        # 如果没有官方，取第一个条目作为对比基准
        reference_model = official if official is not None else (entries[0] if entries else None)
        reference_cny = reference_model.prices_cny if reference_model else {}

        versions = [e for e in entries if e != official]

        ep_detail: dict[str, list[EndpointRow]] = {}
        ep_fetched: dict[str, bool] = {}
        for v in versions:
            if v.strategy != "official":
                data = endpoints_cache.get(v.model_id)
                ep_fetched[v.model_id] = data is not None
                if data is not None:
                    _, rows = calc_expected_with_detail(data, exchange_rate=exchange_rate)
                    ep_detail[v.model_id] = rows

        rankings: list[ScenarioRanking] = []
        if include_scenarios:
            for scenario in scenarios:
                tokens = scenario["tokens"]
                total = sum(tokens.values())
                if abs(total - 1.0) > 0.01:
                    rankings.append(
                        ScenarioRanking(
                            scenario=scenario,
                            skipped_reason=f"比例总和为 {total:.2f}，应为 1.0",
                        )
                    )
                    continue
                rows = [
                    (m, calc_scenario_cost(m.prices_cny, tokens))
                    for m in entries
                ]
                rows.sort(key=lambda x: x[1])
                rankings.append(ScenarioRanking(scenario=scenario, rows=rows))

        pairs.append(
            PairSnapshot(
                display_name=group["display_name"],
                official_modelname=official.model_id if official else "",
                reference_cny=reference_cny,
                official=official,
                versions=versions,
                missing=missing,
                endpoints=ep_detail,
                endpoints_fetched=ep_fetched,
                scenarios=rankings,
            )
        )

    return Snapshot(
        exchange_rate=exchange_rate,
        scenarios=scenarios,
        pairs=pairs,
        headline_count=len(or_models),
        fetched_at=datetime.now(),
        config_path=config_path_str,
        pending_expected=any(
            v.source == "pending_headline" for p in pairs for v in p.versions
        ),
    )


# --------------------------------------------------------------------------- #
# 表格装配：返回 {headers, rows:[{text, dir}]}，CLI/TUI 各自上色
# --------------------------------------------------------------------------- #

def _cell(text: str, direction: int = 0, value=None) -> dict:
    """单元格：显示文本 + 相对参考价的方向 + 可排序原始值"""
    return {"text": text, "dir": direction, "value": text if value is None else value}


def build_comparison_table(pair: PairSnapshot) -> dict:
    """单模型内部：行=价格维度，列=官方 + 各版本"""
    headers = ["类型", "官方"] + [v.label for v in pair.versions]
    rows = []
    for key, label in PRICE_TYPES:
        ref = pair.reference_cny.get(key, 0)
        cells = [_cell(label), _cell(official_cell(ref))]
        for v in pair.versions:
            text, direction = compare_cell(v.prices_cny.get(key, 0), ref)
            cells.append(_cell(text, direction))
        rows.append(cells)
    return {"headers": headers, "rows": rows}


def build_scenario_table(ranking: ScenarioRanking, official_cost: float | None) -> dict:
    """单模型内部：某场景下的成本排名表"""
    headers = ["排名", "模型", "成本 (¥)"]
    rows = []
    if not ranking.rows:
        return {"headers": headers, "rows": rows}
    max_cost = ranking.rows[-1][1]
    for i, (model, cost) in enumerate(ranking.rows):
        rank = "🏆" if i == 0 else str(i + 1)
        cost_text = f"¥{format_price(cost)}" + saving_label(cost, max_cost, i == 0)
        direction = 0
        if official_cost is not None and model.strategy != "official":
            if cost < official_cost:
                direction = -1
            elif cost > official_cost:
                direction = 1
        rows.append([_cell(rank), _cell(model.label), _cell(cost_text, direction)])
    return {"headers": headers, "rows": rows}


def build_overview_table(snapshot: Snapshot) -> dict:
    """总览：每个模型一行，横向对比官方价 / 最优 OR 价 / 节省幅度"""
    headers = ["模型", "版本数", "官方价 (输入/输出)", "最优 OR (输入/输出)", "节省", "最优版本"]
    rows = []
    for pair in snapshot.pairs:
        ref_in = pair.reference_cny.get("input", 0)
        ref_out = pair.reference_cny.get("output", 0)
        ref_cost = ref_in + ref_out

        best = None
        best_cost = None
        for v in pair.versions:
            cost = v.prices_cny.get("input", 0) + v.prices_cny.get("output", 0)
            if best_cost is None or cost < best_cost:
                best_cost, best = cost, v

        official_txt = f"¥{format_price(ref_in)} / ¥{format_price(ref_out)}"
        if best is None:
            rows.append([
                _cell(pair.display_name), _cell("0"), _cell(official_txt),
                _cell("—"), _cell("—"), _cell("无可用版本"),
            ])
            continue

        or_txt = (
            f"¥{format_price(best.prices_cny.get('input', 0))} / "
            f"¥{format_price(best.prices_cny.get('output', 0))}"
        )
        save_pct = (
            (1 - best_cost / ref_cost) * 100 if (ref_cost > 0 and best_cost is not None) else 0.0
        )
        if ref_cost > 0 and best_cost is not None:
            if save_pct > 0:
                saving = _cell(f"↓{save_pct:.0f}%", -1, value=-save_pct)
            elif save_pct < 0:
                saving = _cell(f"↑{abs(save_pct):.0f}%", 1, value=-save_pct)
            else:
                saving = _cell("持平", value=0.0)
        else:
            saving = _cell("—", value=0.0)

        rows.append([
            _cell(pair.display_name),
            _cell(str(len(pair.versions)), value=len(pair.versions)),
            _cell(official_txt, value=ref_cost),
            _cell(or_txt, value=best_cost or 0.0),
            saving,
            _cell(f"{best.label} ({format_strategy(best.strategy)})"),
        ])
    return {"headers": headers, "rows": rows}


def build_endpoint_table(rows: list[EndpointRow]) -> dict:
    """端点明细：谁在供这个模型、各占多少路由权重"""
    headers = ["供应商", "量化", "输入", "输出", "缓存读", "权重", "30m 可用", "状态"]
    table_rows = []
    for r in rows:
        table_rows.append([
            _cell(r.provider),
            _cell(r.quantization),
            _cell(f"¥{format_price(r.prices_cny.get('input', 0))}",
                  value=r.prices_cny.get("input", 0)),
            _cell(f"¥{format_price(r.prices_cny.get('output', 0))}",
                  value=r.prices_cny.get("output", 0)),
            _cell(f"¥{format_price(r.prices_cny.get('cache_read', 0))}",
                  value=r.prices_cny.get("cache_read", 0)),
            _cell("—" if not r.included else f"{r.weight_pct:.1f}%", value=r.weight_pct),
            _cell("—" if r.uptime_30m is None else f"{r.uptime_30m:.2f}%",
                  value=-1 if r.uptime_30m is None else r.uptime_30m),
            _cell("在架" if r.healthy else "下架", 0 if r.healthy else 1,
                  value=0 if r.healthy else 1),
        ])
    return {"headers": headers, "rows": table_rows}


def best_version_for_scenario(ranking: ScenarioRanking) -> tuple[ModelPrice | None, float | None]:
    """该场景下成本最低的 OpenRouter 版本（不含官方）"""
    best: ModelPrice | None = None
    best_cost: float | None = None
    for model, cost in ranking.rows:
        if model.strategy == "official":
            continue
        if best_cost is None or cost < best_cost:
            best, best_cost = model, cost
    return best, best_cost


def official_cost(ranking: ScenarioRanking) -> float | None:
    """该场景下官方版成本"""
    for model, cost in ranking.rows:
        if model.strategy == "official":
            return cost
    return None


def build_cross_model_table(snapshot: Snapshot, scenario_name: str) -> dict:
    """总览：指定场景下各模型的横向对比（官方 vs 最优 OpenRouter 版本）"""
    headers = ["模型", "官方成本", "最优 OR 成本", "节省", "最优版本", "版本数"]
    rows = []
    for pair in snapshot.pairs:
        ranking = next(
            (r for r in pair.scenarios if r.scenario.get("name") == scenario_name), None
        )
        if ranking is None or not ranking.rows or ranking.skipped_reason:
            rows.append([
                _cell(pair.display_name), _cell("—"), _cell("—"), _cell("—"),
                _cell("无可用场景数据"), _cell(str(len(pair.versions)), value=len(pair.versions)),
            ])
            continue

        ref = official_cost(ranking)
        best, best_cost = best_version_for_scenario(ranking)
        if ref is None or best is None or best_cost is None:
            rows.append([
                _cell(pair.display_name), _cell(official_cell(ref or 0)), _cell("—"),
                _cell("—"), _cell("无可用版本"), _cell(str(len(pair.versions)), value=len(pair.versions)),
            ])
            continue

        save = (1 - best_cost / ref) * 100 if ref > 0 else 0.0
        if save > 0:
            saving = _cell(f"↓{save:.0f}%", -1, value=-save)
        elif save < 0:
            saving = _cell(f"↑{abs(save):.0f}%", 1, value=-save)
        else:
            saving = _cell("持平", value=0.0)

        rows.append([
            _cell(pair.display_name),
            _cell(official_cell(ref), value=ref),
            _cell(official_cell(best_cost), value=best_cost),
            saving,
            _cell(f"{best.label} ({format_strategy(best.strategy)})"),
            _cell(str(len(pair.versions)), value=len(pair.versions)),
        ])
    return {"headers": headers, "rows": rows}
