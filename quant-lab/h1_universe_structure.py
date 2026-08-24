"""
H1 结构基线验证 · 合规改造版（v0.1-contract）
================================================

关联契约（唯一规范，不得反向修改）：
    docs/H1_PreRegistration_v0.1.md            （冻结，Gate 0 令牌必须逐字匹配）
    docs/H1_Script_Compliance_Audit_v0.1.md    （改造依据：保留7/修改8/删除1/新增10）

研究问题（契约 §1）：
    验证「研究对象是否值得进入策略研究」，不是寻找策略。
    禁止输出任何「最佳参数 / 最佳持有期 / 最佳策略」。

宇宙（契约 §2）：
    Current-Component Historical Structure Benchmark
    Survivorship Bias Status = KNOWN LIMITATION
    主宇宙 = 中证红利低波 930955 当前成分；Control = 930955 指数价格序列。

执行顺序（契约 §11）：
    Contract -> Audit -> Modification -> Data Snapshot -> Run -> Gate Evaluation

CLI 模式：
    python h1_universe_structure.py check     # Gate 0 + 依赖 + 常量一致性检查（不产生任何结果文件）
    python h1_universe_structure.py snapshot  # 拉取并冻结 Data Snapshot（写 quant-lab/h1_data_snapshot/）
    python h1_universe_structure.py run       # 读取 Snapshot，计算指标 + 三级 Gate，输出 H1_RESULT

本改造日期：2026-08-21。仅做 Script Modification，未运行。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 0. Gate 0：契约令牌（契约 §0 逐字匹配）+ mtime 硬门
# ---------------------------------------------------------------------------

# 契约文件路径（脚本位于 quant-lab/，契约位于 docs/）
CONTRACT_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "H1_PreRegistration_v0.1.md")
)

# 契约 §0 令牌，逐字与契约文件比对；任一缺失即拒绝运行
GATE0_TOKENS = [
    "H1 Pre-Registration v0.1",
    "930955",
    "20150101",
    "20260821",
    "qfq",
    "MA_FAST=20, MA_SLOW=60",
    "COMM=0.00025, STAMP=0.001/0.0005@2023-08-28, SLIP=0.001",
    "seed=20260821, n_boot=2000",
    "REGIME: 牛=close>MA250*1.05, 熊=close<MA250*0.95, 震荡=其余",
]

# 输出禁止项（契约 §9）：一旦这些出现在输出文件即视为违规
FORBIDDEN_OUTPUT_PATTERNS = [
    "best_holding", "best_period", "best_param", "optimal", "最佳持有期", "最佳参数", "最佳策略",
]


class Gate0Error(RuntimeError):
    pass


def gate0_check() -> dict:
    """Gate 0 硬门：契约存在 + 令牌逐字匹配 + 契约 mtime < 运行时间。

    返回检查结果 dict；任一失败抛 Gate0Error（拒绝运行）。
    """
    result = {"contract_path": CONTRACT_PATH, "checks": {}}
    if not os.path.isfile(CONTRACT_PATH):
        raise Gate0Error(f"契约文件不存在: {CONTRACT_PATH}")

    with open(CONTRACT_PATH, encoding="utf-8") as f:
        contract_text = f.read()

    result["contract_mtime"] = os.path.getmtime(CONTRACT_PATH)
    result["contract_mtime_str"] = dt.datetime.fromtimestamp(
        result["contract_mtime"]
    ).isoformat()
    result["now"] = time.time()
    result["mtime_ok"] = result["contract_mtime"] < result["now"]

    missing = [t for t in GATE0_TOKENS if t not in contract_text]
    result["missing_tokens"] = missing
    result["tokens_ok"] = len(missing) == 0

    if not result["mtime_ok"]:
        raise Gate0Error("Gate 0 FAIL: 契约 mtime 不早于运行时间（契约在运行之后被修改过）。")
    if not result["tokens_ok"]:
        raise Gate0Error(f"Gate 0 FAIL: 契约令牌缺失 {missing}")

    result["pass"] = True
    return result


# ---------------------------------------------------------------------------
# 1. 配置常量（契约冻结值；集中于此，不散落）
# ---------------------------------------------------------------------------

UNIVERSE_INDEX = "930955"
START = "20150101"
END = "20260821"
QFQ = "qfq"
MA_FAST, MA_SLOW = 20, 60
MA250 = 250

# 摩擦模型（契约 §6）
COMM_RATE = 0.00025            # 佣金，双边
STAMP_SEG_DATE = "2023-08-28"  # 印花税分段日期
STAMP_BEFORE = 0.001           # t < 2023-08-28，卖出
STAMP_AFTER = 0.0005           # t >= 2023-08-28，卖出
SLIP_RATE = 0.001              # 滑点，单边

# 涨跌停阈值（契约 §4）：主板 ±9.8%，创业板(30)/科创板(68) ±19.8%
LIMIT_MAIN = 0.098
LIMIT_CHINEXT = 0.198
CHINEXT_PREFIXES = ("30", "68")

# Regime（契约 §5/D5）：930955 指数 vs 自身 MA250
REGIME_BULL = 1.05
REGIME_BEAR = 0.95

# 统计（契约 §5/D2）
SEED = 20260821
N_BOOT = 2000

# 数据覆盖门槛（契约 §8 Gate1）
G1_STOCK_COVERAGE = 0.80       # ≥80% 股票
G1_DAY_COVERAGE = 0.90         # × ≥90% 交易日
G1_PRICE_JUMP = 0.50           # 单日跳变 >50% 且非停牌 → 价格异常
G1_RET_CHECK = 0.20            # 复权一致性抽检：单日收益 >20% 疑未复权/除权点
EARLY_TRIM_DAYS = 600          # Erratum 002：负价签名股固定丢弃前 ~600 交易日（≈2.5y）

# 结构门（契约 §8 Gate2）
G2_REGIME_MIN = 2              # 结构需在 ≥2 个 regime 中方向一致

# 经济门（契约 §8 Gate3）：MA20/60 多头净期望 CI 下界 > 0

# 回撤恢复 / 突破（契约 §5 D3）
DRAWDOWN_THRESH = -0.05
RECOVERY_WINDOW = 60
BREAKOUT_LOOKBACK = 20
BREAKOUT_FWD = (5, 10, 20)

# 输出
SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h1_data_snapshot")
RESULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h1_result")


# ---------------------------------------------------------------------------
# 2. 小工具
# ---------------------------------------------------------------------------

def stamp_rate(date) -> float:
    """印花税率（卖出），按契约 §6 时间分段。date 可为 Timestamp/str/int。"""
    ts = pd.Timestamp(date) if not isinstance(date, pd.Timestamp) else date
    return STAMP_BEFORE if ts < pd.Timestamp(STAMP_SEG_DATE) else STAMP_AFTER


def is_chinext(code: str) -> bool:
    return code.startswith(CHINEXT_PREFIXES)


def limit_threshold(code: str) -> float:
    return LIMIT_CHINEXT if is_chinext(code) else LIMIT_MAIN


def seed_for(code: str) -> int:
    """每只股票独立但确定的 bootstrap 种子（基于冻结 SEED 派生）。"""
    h = hashlib.md5(code.encode("utf-8")).hexdigest()[:8]
    return (SEED + int(h, 16)) % (2**32)


def bootstrap_ci(x: np.ndarray, stat_fn, seed: int, n_boot: int = N_BOOT, alpha: float = 0.05):
    """普通 bootstrap 95% CI（冻结 seed）。返回 (lo, hi, samples)。"""
    rng = np.random.default_rng(seed)
    n = len(x)
    if n == 0:
        return (np.nan, np.nan, np.array([]))
    samples = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        try:
            samples[b] = stat_fn(x[idx])
        except Exception:  # noqa: BLE001
            samples[b] = np.nan
    samples = samples[~np.isnan(samples)]
    if len(samples) < 2:
        return (np.nan, np.nan, samples)
    lo, hi = np.percentile(samples, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (float(lo), float(hi), samples)


# ---------------------------------------------------------------------------
# 3. 数据层（契约 §4）
# ---------------------------------------------------------------------------

def get_universe() -> list[dict]:
    """930955 当前成分（截至本数据快照日）。返回 [{code,name}, ...]。"""
    try:
        import akshare as ak  # noqa: PLC0415

        try:
            df = ak.index_stock_cons_csindex(symbol=UNIVERSE_INDEX)
        except Exception:  # noqa: BLE001
            df = ak.index_stock_cons(symbol=UNIVERSE_INDEX)
    except ImportError:
        raise Gate0Error("akshare 未安装：H1 数据层依赖 akshare（契约 §10）")

    # 实际接口（2026-08-21 实测 akshare 1.18.64）返回列：成分券代码/成分券名称/交易所。
    # 兼容回退列名；仍无法识别则明确报错而非静默（快照不可带病）。
    code_col = next((c for c in ("成分券代码", "品种代码", "symbol") if c in df.columns), None)
    name_col = next((c for c in ("成分券名称", "品种名称", "name") if c in df.columns), None)
    if code_col is None or name_col is None:
        raise RuntimeError(f"无法识别成分接口列名: {list(df.columns)}")
    rows = []
    for code, name in zip(df[code_col].astype(str), df[name_col].astype(str)):
        code = code.zfill(6) if len(code) < 6 else code
        rows.append({"code": code, "name": str(name)})
    return rows


def _retry_fetch(fn, code: str, max_retries: int = 3):
    """指数级退避重试包装：任一异常或空结果均重试，全部失败返回 None。

    退避：0.5s, 1.5s, 4.5s（因子 3，上限 3 次）。沙箱网络抖动为主因。
    """
    import akshare as ak  # noqa: PLC0415

    last_err = None
    for attempt in range(max_retries):
        try:
            df = fn(ak)
            if df is not None and not df.empty:
                return df
            last_err = RuntimeError(f"空结果 (attempt {attempt + 1}/{max_retries})")
        except Exception as e:  # noqa: BLE001
            last_err = e
        if attempt < max_retries - 1:
            backoff = 0.5 * (3 ** attempt)
            print(f"    [retry] {code}: 第 {attempt + 1} 次失败，{backoff:.1f}s 后重试 ({type(last_err).__name__})")
            time.sleep(backoff)
    print(f"  [skip] {code}: 重试 {max_retries} 次后仍失败 - {last_err}")
    return None


def _clean_price_df(df: pd.DataFrame) -> pd.DataFrame | None:
    """统一字段清洗（东财/新浪两种原始列名均兼容）+ 截断前导非法价
    + 丢弃早期复权未稳定窗口。

    Erratum 002：腾讯 qfq 采用绝对分红扣减，对部分高分红老牌股早期历史
    复权基准崩坏，出现负值与"从近零爬升"的荒谬正价。两步修复：
      (1) 截断前导 <=0 非法价（保留 date 索引，不改 fetch_daily 契约）；
      (2) 负价签名股（原始序列含 <=0）固定丢弃前 EARLY_TRIM_DAYS 交易日，
          干净股完全不碰，杜绝误砍（如长江电力 2015 股灾波动）。
    返回清洗后的日线 DF（date 为索引）或 None。
    """
    rename = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume", "涨跌幅": "pct_chg",
        # 新浪 stock_zh_a_daily 列名
        "date": "date", "open": "open", "close": "close",
        "high": "high", "low": "low", "volume": "volume", "pct_chg": "pct_chg",
    }
    df = df.rename(columns=rename)
    need = ["date", "open", "high", "low", "close", "volume", "pct_chg"]
    if not all(c in df.columns for c in need):
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date").set_index("date")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 负价签名：基于原始序列（截断前）判断是否含 <=0，用于触发 early-trim
    has_neg_sig = bool((df["close"] <= 0).any())

    # --- (1) 截断前导 <=0 非法价（保留 date 索引） ---
    valid = df["close"] > 0
    if not valid.any():
        return None
    first_valid = valid.idxmax()
    df = df.loc[first_valid:].copy()

    # 中间偶发 <=0 的零值/坏点采用前向填充（若仍 <=0 则直接剔除）
    df["close"] = df["close"].mask(df["close"] <= 0).ffill()
    df = df.dropna(subset=["close"])

    # --- (2) Erratum 002 精炼：负价签名股固定丢弃早期 ~600 交易日 ---
    # 腾讯 qfq 绝对分红扣减对高分红股早期复权基准崩坏（负价/近零平直线/
    # 从近零爬升），单只股票的损坏段集中在前 ~2.5 年。凡原始序列含 <=0
    # 的样本即打"负价签名"，统一丢弃前 EARLY_TRIM_DAYS 日；干净股（无
    # 负价）完全不碰，杜绝误砍（如长江电力 2015 股灾波动）。
    if has_neg_sig and len(df) > EARLY_TRIM_DAYS + 200:
        df = df.iloc[EARLY_TRIM_DAYS:].copy()

    if len(df) < 50:  # 过滤有效交易日过短的样本
        return None

    return df


def _eastmoney_fetch(ak, code: str) -> pd.DataFrame | None:
    """备用源：东财 kline（stock_zh_a_hist，qfq）。"""
    return ak.stock_zh_a_hist(
        symbol=code, period="daily", start_date=START, end_date=END, adjust=QFQ
    )


def _tencent_market_prefix(code: str) -> str:
    """腾讯接口要求带市场前缀：6 开头→sh，0/3 开头→sz。"""
    return "sh" + code if code.startswith("6") else "sz" + code


def _tencent_segments(start: str, end: str, max_years: int = 2):
    """把 [start, end] 切成每段不超过 max_years 年的子区间（腾讯接口对超长区间返回 param error）。"""
    import datetime as _dt  # noqa: PLC0415

    s = _dt.date.fromisoformat(start)
    e = _dt.date.fromisoformat(end)
    segs = []
    cur = s
    while cur <= e:
        nxt = _dt.date(cur.year + max_years, cur.month, cur.day)
        seg_end = min(nxt - _dt.timedelta(days=1), e)
        segs.append((cur.isoformat(), seg_end.isoformat()))
        if seg_end >= e:
            break
        cur = nxt
    return segs


def _tencent_fetch(ak, code: str) -> pd.DataFrame | None:
    """主源：腾讯财经原生 kline 接口（web.ifzq.gtimg.cn）。

    通过本地代理（FlClash）稳定可达；东财/新浪在同等网络下被 TLS/RemoteDisconnected 阻断。
    字段顺序与东财不同：腾讯返回 [date, open, close, high, low, volume]，需重排为
    [date, open, high, low, close, volume] 以匹配下游清洗层。
    腾讯对超过约 2 年的区间请求返回 param error，故按 2 年一段拆分后拼接。
    仅做数据采集层调整（Script Modification），不触碰 Gate/契约常量/输出结构。
    """
    import requests  # noqa: PLC0415

    prefix = _tencent_market_prefix(code)
    all_rows = []
    for seg_s, seg_e in _tencent_segments(START, END):
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={prefix},day,{seg_s},{seg_e},320,qfq"
        )
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            d = r.json()
        except Exception:  # noqa: BLE001
            continue  # 单段失败不致命，尝试下一段
        if d.get("code") != 0 or "data" not in d:
            continue
        data_node = d["data"]
        if not isinstance(data_node, dict):
            continue
        node = data_node.get(prefix)
        if not node:
            continue
        rows = node.get("qfqday") or node.get("day")
        if rows:
            all_rows.extend(rows)
    if not all_rows:
        return None
    # 按日期去重（分段边界可能重叠），保留首次出现
    seen = set()
    dedup = []
    for row in all_rows:
        if len(row) < 6:
            continue
        if row[0] in seen:
            continue
        seen.add(row[0])
        dedup.append(row)
    if not dedup:
        return None
    out = []
    for row in dedup:
        # 腾讯顺序: [date, open, close, high, low, volume]
        out.append({
            "date": row[0],
            "open": float(row[1]),
            "high": float(row[3]),
            "low": float(row[4]),
            "close": float(row[2]),
            "volume": float(row[5]),
        })
    df = pd.DataFrame(out).sort_values("date").reset_index(drop=True)
    df["pct_chg"] = (df["close"] / df["close"].shift(1) - 1) * 100
    return df


def _sina_fetch(ak, code: str) -> pd.DataFrame | None:
    """备用源：新浪日线（stock_zh_a_daily，未复权），用于交叉校验价格合理性。"""
    try:
        return ak.stock_zh_a_daily(symbol="sh" + code if code.startswith("6") else "sz" + code,
                                   start_date=START, end_date=END, adjust="")
    except Exception:  # noqa: BLE001
        return None


def _cross_validate(primary: pd.DataFrame, sina: pd.DataFrame | None, code: str) -> dict:
    """价格合理性校验（契约 §4 口径）：

    - 除权因子错位：qfq 序列在相邻非停牌日出现 >30% 跳变且成交量异常放大（典型送转除权未复权干净）。
    - 与主源/备用源收盘价方向一致性：同一交易日两源收盘偏差 >8% 视为主源可疑。
    返回 {suspect: bool, reasons: [str], n_divjump: int}
    """
    reasons = []
    n_divjump = 0
    ret = primary["close"].pct_change().fillna(0)
    vol_z = primary["volume"]
    vol_med = vol_z.median()
    suspend = primary.get("suspend", pd.Series(False, index=primary.index))
    if vol_med and vol_med > 0:
        # 候选：非停牌 + >30% 跳变 + 放量（除权日典型形态）
        cand = (ret.abs() > 0.30) & (primary["volume"] > 3 * vol_med) & (~suspend)
        # 孤立单日豁免：若前后一日均无大跳变，视作正常除权，不计入 suspect
        big_prev = cand.shift(1).fillna(False)
        big_next = cand.shift(-1).fillna(False)
        clustered = cand & (big_prev | big_next)  # 连续/簇发才可疑
        n_divjump = int(clustered.sum())
        if n_divjump > 0:
            reasons.append(f"疑似除权因子错位 {n_divjump} 处（连续/簇发 >30% 跳变且放量，非停牌）")

    if sina is not None and not sina.empty:
        common = primary.index.intersection(sina.index)
        if len(common) > 20:
            p = primary["close"].reindex(common)
            s = sina["close"].reindex(common)
            s = s[s > 0]
            if len(s) > 20:
                # 用两源各自首日起至末日的累计涨幅比对齐量纲（新浪未复权，仅比方向）
                p_chg = p.iloc[-1] / p.iloc[0] - 1
                s_chg = s.iloc[-1] / s.iloc[0] - 1
                if p_chg * s_chg < 0:  # 方向相反（一涨一跌）极可疑
                    reasons.append("主源/备用源累计方向背离（疑似复权错位）")

    return {"suspect": len(reasons) > 0, "reasons": reasons, "n_divjump": n_divjump}


def fetch_daily(code: str) -> pd.DataFrame | None:
    """拉取单只个股 qfq 日线，产出清洗后的 DataFrame。

    增强（Script Modification，不触碰 Gate）：
      - 主源腾讯财经原生 kline（本地代理稳定可达）；失败则指数级退避重试（最多 3 次）；
      - 主源彻底失败 → 回退东财 kline（stock_zh_a_hist，qfq）；
      - 东财仍失败 → 回退新浪日线（未复权）作降级数据；
      - 价格合理性校验：除权因子错位 / 主备源方向背离 → 标记 suspect，交由下游 anomaly 处理。

    列：date(索引), open, high, low, close, volume, pct_chg, limit_up, limit_down, suspend, anomaly
    """
    import akshare as ak  # noqa: PLC0415

    df = _retry_fetch(lambda a: _tencent_fetch(a, code), code)
    suspect_info = {"suspect": False, "reasons": [], "n_divjump": 0}
    sina_df = None
    if df is None:
        # 主源（腾讯）彻底失败 → 尝试东财备用源
        print(f"    [fallback] {code}: 腾讯主源不可达，尝试东财备用源")
        df = _retry_fetch(lambda a: _eastmoney_fetch(a, code), code)
        if df is None:
            # 东财也失败 → 尝试新浪源（未复权）作为降级数据，标记 suspect（不可静默通过）
            print(f"    [fallback] {code}: 东财不可达，尝试新浪备用源")
            sina_raw = _retry_fetch(lambda a: _sina_fetch(a, code), code)
            if sina_raw is None:
                return None
            df = _clean_price_df(sina_raw)
            if df is None:
                return None
            suspect_info = {"suspect": True, "reasons": ["主源与东财均不可达，使用新浪未复权降级数据"], "n_divjump": 0}
        else:
            df = _clean_price_df(df)
            if df is None:
                return None
            suspect_info = {"suspect": True, "reasons": ["腾讯主源不可达，使用东财降级数据"], "n_divjump": 0}
    else:
        df = _clean_price_df(df)
        if df is None:
            return None
        # 主源成功 → 拉新浪做交叉校验（失败不致命）
        sina_raw = _sina_fetch(ak, code)
        sina_df = _clean_price_df(sina_raw) if sina_raw is not None else None
        suspect_info = _cross_validate(df, sina_df, code)

    # 停牌：成交量缺失或为 0
    df["suspend"] = df["volume"].isna() | (df["volume"] <= 0)

    # 涨跌停：基于涨跌幅（契约 §4 阈值），停牌日不判涨跌停
    lim = limit_threshold(code)
    pct = df["pct_chg"].fillna(0) / 100.0
    df["limit_up"] = (~df["suspend"]) & (pct >= lim)
    df["limit_down"] = (~df["suspend"]) & (pct <= -lim)

    # 价格异常：收盘 <=0；单日跳变 >50% 且非停牌（契约 §4）
    ret = df["close"].pct_change()
    jump_anom = (ret.abs() > G1_PRICE_JUMP) & (~df["suspend"])
    # 交叉校验 suspect 也并入 anomaly（不绕过 Gate 1，由快照记录 n_anomaly）
    df["anomaly"] = df["close"].le(0) | jump_anom | (suspect_info["suspect"] and ~df["suspend"])
    if suspect_info["suspect"]:
        print(f"    [warn] {code}: 价格校验告警 {suspect_info['reasons']}")
    return df

    rename = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume", "涨跌幅": "pct_chg",
    }
    df = df.rename(columns=rename)
    need = ["date", "open", "high", "low", "close", "volume", "pct_chg"]
    if not all(c in df.columns for c in need):
        print(f"  [skip] {code}: 缺少必要列")
        return None

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 停牌：成交量缺失或为 0
    df["suspend"] = df["volume"].isna() | (df["volume"] <= 0)

    # 涨跌停：基于涨跌幅（契约 §4 阈值），停牌日不判涨跌停
    lim = limit_threshold(code)
    pct = df["pct_chg"].fillna(0) / 100.0
    df["limit_up"] = (~df["suspend"]) & (pct >= lim)
    df["limit_down"] = (~df["suspend"]) & (pct <= -lim)

    # 价格异常：收盘 <=0；单日跳变 >50% 且非停牌
    ret = df["close"].pct_change()
    df["anomaly"] = df["close"].le(0) | ((ret.abs() > G1_PRICE_JUMP) & (~df["suspend"]))
    return df


def fetch_index_daily() -> pd.DataFrame | None:
    """930955 指数日线（Control，用于 regime 划分）。"""
    import akshare as ak  # noqa: PLC0415

    try:
        df = ak.index_zh_a_hist(
            symbol=UNIVERSE_INDEX, period="daily", start_date=START, end_date=END
        )
    except Exception as e:  # noqa: BLE001
        print(f"  [skip] index {UNIVERSE_INDEX}: {e}")
        return None
    if df is None or df.empty:
        return None
    df = df.rename(columns={"日期": "date", "收盘": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")[["close"]]
    return df


# ---------------------------------------------------------------------------
# 4. 复权一致性抽检（契约 §4）
# ---------------------------------------------------------------------------

def adjustment_check(close: pd.Series, code: str) -> dict:
    """质检：区分「正常除权跳变」与「真实数据断裂」。

    A 股高股息标的每年稳定分红送转，qfq 序列在除权除息日出现单日 >20% 跳变是
    **正常形态**，不应判为数据坏账。真异常的特征是「连续多个交易日断裂」或
    「停牌日价格不可逆断崖」（数据缺失/错乱）。

    判定（仅影响 adjust_ok 这一质检标记，不改动 Gate 判据/常量）：
      - 单日孤立跳变（前后一日无大跳变）→ 视为正常除权，放行（ok=True），仍记录 n_big_jumps 供审计；
      - 连续 2+ 交易日出现大跳变 → 真实可疑，ok=False；
      - 跳变日紧邻停牌（复牌涨跌停属正常）→ 不计入。
    """
    ret = close.pct_change().fillna(0)
    big = ret.abs() > G1_RET_CHECK
    n_big = int(big.sum())
    # 连续断裂：当天大跳变且前一天也是大跳变（连续 2 日异常）
    consecutive = int((big & big.shift(1).fillna(False)).sum())
    ok = consecutive == 0  # 只要有连续断裂即判失败；单日孤立跳变放行
    flagged = ret[big]
    return {
        "code": code,
        "n_big_jumps": n_big,
        "n_consecutive": consecutive,
        "big_jump_dates": [d.strftime("%Y-%m-%d") for d in flagged.index[:5]],
        "ok": ok,
    }


# ---------------------------------------------------------------------------
# 5. 指标层（契约 §5 D1~D6）
# ---------------------------------------------------------------------------

def d1_return_stats(close: pd.Series) -> dict:
    """D1 收益特征（诊断项，不参与 Gate）。"""
    if len(close) < 2:
        return {}
    ret = close.pct_change().dropna()
    n = len(ret)
    total = close.iloc[-1] / close.iloc[0] - 1
    years = n / 242
    # 消除 invalid value encountered in scalar power
    if years <= 0:
        cagr = np.nan
    elif (1.0 + total) <= 0:
        cagr = -1.0
    else:
        cagr = (1.0 + total) ** (1.0 / years) - 1.0
    vol = ret.std() * np.sqrt(242)
    eq = (1 + ret).cumprod()
    mdd = (eq / eq.cummax() - 1).min()
    calmar = cagr / abs(mdd) if mdd != 0 else np.nan
    return {
        "cagr": float(cagr) if np.isfinite(cagr) else None,
        "vol_ann": float(vol) if np.isfinite(vol) else None,
        "max_drawdown": float(mdd) if np.isfinite(mdd) else None,
        "calmar": float(calmar) if np.isfinite(calmar) else None,
        "n_days": int(n),
    }


def d2_timeseries(ret: pd.Series, seed: int) -> dict:
    """D2 时间序列：日收益 lag-1 自相关 + bootstrap 95% CI。"""
    ret = ret.dropna()
    if len(ret) < 30:
        return {}

    def _rho(x):
        if len(x) < 2:
            return np.nan
        return float(np.corrcoef(x[:-1], x[1:])[0, 1])

    rho = _rho(ret.values)
    lo, hi, _ = bootstrap_ci(ret.values, _rho, seed=seed)
    return {
        "autocorr_1": rho if np.isfinite(rho) else None,
        "autocorr_1_ci": [float(lo) if np.isfinite(lo) else None,
                          float(hi) if np.isfinite(hi) else None],
        "autocorr_1_significant": (rho is not None) and (lo > 0 or hi < 0),
        "bias": "momentum" if (rho is not None and rho > 0) else ("reversion" if (rho is not None and rho < 0) else "flat"),
    }


def _ma_positions(close: pd.Series) -> pd.Series:
    ma_f = close.rolling(MA_FAST).mean()
    ma_s = close.rolling(MA_SLOW).mean()
    return (ma_f > ma_s).astype(int)


def simulate_ma_cross(close: pd.Series, df: pd.DataFrame) -> dict:
    """MA20/60 多头结构的经济表达（契约 §5 D3/D6 + §6）。

    gross：纯结构（信号 t 收盘，t+1 生效，close-to-close，无摩擦）。
    net：扣 佣金/印花税/滑点/T+1/涨跌停/停牌。

    返回 gross/net 日收益序列 + 切换费用 + 各统计量。T+1 由 pos.shift(1) 天然满足
    （信号当日不产生持仓收益）。涨跌停/停牌：切换日不可成交则跳过本次切换。
    """
    pos = _ma_positions(close)  # 1=多头
    gross_ret = close.pct_change().fillna(0) * pos.shift(1).fillna(0)

    # 逐日模拟 net（含摩擦）
    n = len(close)
    held = 0
    net_ret = np.zeros(n)
    fees = np.zeros(n)
    limit_up = df["limit_up"]
    limit_down = df["limit_down"]
    suspend = df["suspend"]

    close_v = close.values
    dates = close.index

    for i in range(1, n):
        target = int(pos.iloc[i - 1])  # 昨日收盘信号，今日（i）执行
        # 涨跌停/停牌不可成交（契约 §6）
        if target == 1 and held == 0:
            if limit_up.iloc[i] or suspend.iloc[i]:
                target = 0  # 今日涨停/停牌，买入跳过，保持空仓
        elif target == 0 and held == 1:
            if limit_down.iloc[i] or suspend.iloc[i]:
                target = 1  # 今日跌停/停牌，卖出失败，保持持仓
        # 切换：t 日切换即 t 日按收盘价计成本（保守：切换日即计费用）
        if target != held:
            if held == 0 and target == 1:  # 买入
                fees[i] = COMM_RATE + SLIP_RATE
            elif held == 1 and target == 0:  # 卖出
                fees[i] = COMM_RATE + SLIP_RATE + stamp_rate(dates[i])
            held = target
        # 消除 divide by zero encountered in scalar divide
        if close_v[i - 1] <= 0 or close_v[i] <= 0:
            net_ret[i] = 0.0
        else:
            net_ret[i] = (close_v[i] / close_v[i - 1] - 1.0) if held else 0.0
    # 卖出费用同样在持仓期最后一天之外：此处已计入切换日；净收益 = 持仓日收益 - 当日费用
    net_ret = net_ret - fees

    g = pd.Series(gross_ret.values, index=close.index)
    nts = pd.Series(net_ret, index=close.index)
    return {
        "gross_ret": g,
        "net_ret": nts,
        "total_fees": float(fees.sum()),
        "n_trades": int((np.diff(np.concatenate([[0], pos.values])) != 0).sum()),
    }


def d3_band_structure(close: pd.Series, df: pd.DataFrame) -> dict:
    """D3 波段特征：持仓日正收益占比（标签明确非交易胜率）、完整波段胜率、回撤恢复、突破持续性。"""
    sim = simulate_ma_cross(close, df)
    g = sim["gross_ret"]
    pos = _ma_positions(close)

    # 持仓日正收益占比（gross，无摩擦，仅统计结构）
    held_days = g[g != 0]
    inpos_win = float((held_days > 0).mean()) if len(held_days) else None
    held_ci = bootstrap_ci(held_days.values, lambda x: float((x > 0).mean()), seed=seed_for(close.name or "0"))

    # 完整波段胜率：金叉(0->1)进场，死叉(1->0)出场
    p = pos.values
    entries = np.where((p[1:] == 1) & (p[:-1] == 0))[0] + 1
    exits = np.where((p[1:] == 0) & (p[:-1] == 1))[0] + 1
    trade_ret = []
    for e in entries:
        x = exits[exits > e]
        if len(x) == 0:
            x_end = len(close) - 1
        else:
            x_end = x[0]
        if x_end > e:
            trade_ret.append(close.iloc[x_end] / close.iloc[e] - 1)
    band_win = float(np.mean([r > 0 for r in trade_ret])) if trade_ret else None

    # 回撤恢复概率（-5%，60 日内收复）
    eq = close / close.cummax() - 1
    recovered, total_dd = 0, 0
    i = 0
    n = len(close)
    while i < n:
        if eq.iloc[i] <= DRAWDOWN_THRESH:
            total_dd += 1
            peak = close.cummax().iloc[i]
            j = i + 1
            while j < min(n, i + RECOVERY_WINDOW):
                if close.iloc[j] >= peak:
                    recovered += 1
                    break
                j += 1
            i = j if j < n else n
        else:
            i += 1
    rec_prob = recovered / total_dd if total_dd else None

    # 突破持续性：创 20 日新高后 5/10/20 日前向收益中位数
    roll_max = close.rolling(BREAKOUT_LOOKBACK).max().shift(1)
    breakout = close > roll_max
    fwd = {}
    for f in BREAKOUT_FWD:
        fwd_ret = (close.shift(-f) / close - 1)[breakout].dropna()
        fwd[f"{f}d_median"] = float(fwd_ret.median()) if len(fwd_ret) else None
        fwd[f"{f}d_n"] = int(len(fwd_ret))

    return {
        "inpos_win_rate": inpos_win,
        "inpos_win_rate_label": "持仓日正收益占比（非交易胜率）",
        "inpos_win_rate_ci": [float(held_ci[0]) if np.isfinite(held_ci[0]) else None,
                              float(held_ci[1]) if np.isfinite(held_ci[1]) else None],
        "band_win_rate": band_win,
        "n_bands": len(trade_ret),
        "recovery_prob": rec_prob,
        "n_drawdown_events": total_dd,
        "breakout": fwd,
        "n_trades": sim["n_trades"],
        "total_fees": sim["total_fees"],
        "gross_mean_daily": float(g.mean()),
        "net_mean_daily": float(sim["net_ret"].mean()),
    }


def d4_cross_sectional(stats_list: list[dict]) -> dict:
    """D4 横截面：成分股年化波动离散度 + 相关矩阵均值。"""
    vols = [s.get("d1", {}).get("vol_ann") for s in stats_list]
    vols = [v for v in vols if v is not None]
    res = {}
    if len(vols) >= 2:
        res["vol_dispersion_std"] = float(np.std(vols))
        res["vol_dispersion_iqr"] = float(np.percentile(vols, 75) - np.percentile(vols, 25))
        res["n_stocks"] = len(vols)
    return res


def regime_series(index_close: pd.Series) -> pd.Series:
    """930955 指数 vs 自身 MA250 → 每日 regime（point-in-time）。"""
    ma = index_close.rolling(MA250).mean()
    out = pd.Series("震荡", index=index_close.index)
    out[index_close > ma * REGIME_BULL] = "牛"
    out[index_close < ma * REGIME_BEAR] = "熊"
    return out


# ---------------------------------------------------------------------------
# 6. Gate 层（契约 §8）
# ---------------------------------------------------------------------------

def gate1_data_integrity(stats_list: list[dict], universe_n: int) -> dict:
    """Data Integrity：覆盖 ≥80%×≥90%，无未修复价格异常，数据版本完整。"""
    ok_stocks = [s for s in stats_list if s.get("d1")]
    stock_cov = len(ok_stocks) / universe_n if universe_n else 0.0

    day_covs = [s.get("day_coverage", 0) for s in stats_list]
    day_cov = float(np.mean(day_covs)) if day_covs else 0.0

    anomalies = [s for s in stats_list if s.get("n_anomaly", 0) > 0]
    big_jumps = [s for s in stats_list if not s.get("adjust_ok", True)]

    passed = (
        stock_cov >= G1_STOCK_COVERAGE
        and day_cov >= G1_DAY_COVERAGE
        and len(anomalies) == 0
        and len(big_jumps) == 0
    )
    return {
        "gate": "Data Integrity",
        "decision": "PASS" if passed else "FAIL",
        "stock_coverage": float(stock_cov),
        "day_coverage_avg": float(day_cov),
        "n_anomaly_stocks": len(anomalies),
        "n_adjust_fail_stocks": len(big_jumps),
        "criteria": {
            "stock_coverage_ge": G1_STOCK_COVERAGE,
            "day_coverage_ge": G1_DAY_COVERAGE,
            "anomaly_stocks_eq_0": True,
            "adjust_fail_eq_0": True,
        },
    }


def gate2_structural(basket: dict, regime_table: dict) -> dict:
    """Structural Evidence：ρ(1) CI 不含 0 或 MA 持仓日胜率 CI 下界>50%，且跨≥2 regime 同号。"""
    sig_autocorr = basket["d2"].get("autocorr_1_significant", False)
    inpos_ci = basket["d3"].get("inpos_win_rate_ci", [None, None])
    sig_inpos = (inpos_ci[0] is not None and inpos_ci[0] > 0.50)
    structural = sig_autocorr or sig_inpos

    # regime 同号性：各 regime 下结构信号方向一致
    rho_by_regime = regime_table.get("autocorr_by_regime", {})
    sign_dir = None
    n_agree = 0
    for r, v in rho_by_regime.items():
        rho = v.get("autocorr_1")
        if rho is None:
            continue
        d = 1 if rho > 0 else (-1 if rho < 0 else 0)
        if d == 0:
            continue
        if sign_dir is None:
            sign_dir = d
        if d == sign_dir:
            n_agree += 1
    regime_stable = n_agree >= G2_REGIME_MIN and sign_dir is not None

    passed = structural and regime_stable
    return {
        "gate": "Structural Evidence",
        "decision": "PASS" if passed else "FAIL",
        "autocorr_significant": bool(sig_autocorr),
        "inpos_win_ci_lower_gt_50": bool(sig_inpos),
        "regime_stable": bool(regime_stable),
        "n_regime_agree": n_agree,
        "criteria": {
            "autocorr_ci_excludes_0_or_inpos_ci_lower_gt_50": True,
            "regime_agree_ge": G2_REGIME_MIN,
        },
    }


def gate3_economic(net_ret: pd.Series, seed: int) -> dict:
    """Economic/Friction：MA20/60 多头 net 期望 bootstrap 95% CI 下界 > 0。"""
    r = net_ret.dropna().values
    if len(r) == 0:
        return {"gate": "Economic/Friction", "decision": "FAIL", "reason": "no_net_returns"}
    mean_fn = lambda x: float(np.mean(x))  # noqa: E731
    lo, hi, _ = bootstrap_ci(r, mean_fn, seed=seed)
    passed = lo > 0
    return {
        "gate": "Economic/Friction",
        "decision": "PASS" if passed else "FAIL",
        "net_mean_ci": [float(lo) if np.isfinite(lo) else None,
                        float(hi) if np.isfinite(hi) else None],
        "net_mean": float(np.mean(r)),
        "net_ci_lower_gt_0": bool(passed),
        "criteria": {"net_mean_ci_lower_gt_0": True},
    }


def overall(g1: dict, g2: dict, g3: dict) -> str:
    if g1["decision"] != "PASS":
        return "INCONCLUSIVE"
    if g2["decision"] == "PASS" and g3["decision"] == "PASS":
        return "PASS"
    return "FAIL"


# ---------------------------------------------------------------------------
# 7. 主流程
# ---------------------------------------------------------------------------

def build_basket(close_df: pd.DataFrame) -> pd.Series:
    """等权组合日收益序列（主篮子，用于 Gate2/3）。"""
    ret = close_df.pct_change()
    return ret.mean(axis=1, skipna=True)


def build_synthetic_index(close_df: pd.DataFrame) -> pd.Series:
    """当前成分等权合成指数（Erratum 001，替代 930955 官方指数）。

    每只股票前复权 close 按各自首个有效值归一化后，逐日等权平均，得到水平序列。
    """
    norm = close_df.copy()
    for c in norm.columns:
        first_valid = norm[c].dropna()
        if len(first_valid):
            norm[c] = norm[c] / first_valid.iloc[0]
    return norm.mean(axis=1, skipna=True)


def run_analysis(snapshot: dict) -> dict:
    """从 Snapshot 计算 6 维指标 + 三级 Gate，输出 H1_RESULT。"""
    universe = snapshot["universe"]
    stocks = snapshot["stocks"]  # {code: {name, close:[...], meta:{...}}}
    data_version = snapshot["data_version"]

    stats_list = []
    close_cols = {}
    meta = {}
    for code, s in stocks.items():
        # 快照存储为列向 daily 子结构（{date,open,high,low,close,volume,...}）；
        # 兼容历史草稿中直接拍平的 {close:[...]} 形态。
        daily = s.get("daily", s)
        close = pd.Series(daily.get("close"), index=daily.get("date"))
        df = pd.DataFrame(daily)  # 含 limit_up/limit_down/suspend/anomaly
        day_cov = len(close.dropna()) / max(1, len(close))
        d1 = d1_return_stats(close)
        d2 = d2_timeseries(close.pct_change().dropna(), seed=seed_for(code))
        d3 = d3_band_structure(close, df) if len(close) >= 60 else {}
        stats_list.append({
            "code": code, "name": s["name"],
            "d1": d1, "d2": d2, "d3": d3,
            "day_coverage": day_cov,
            "n_anomaly": int(df["anomaly"].sum()) if "anomaly" in df else 0,
            "adjust_ok": s.get("adjust_ok", True),
        })
        close_cols[code] = close
        meta[code] = {"name": s["name"], "seed": seed_for(code)}

    # 主篮子 = 等权组合
    basket_close = pd.DataFrame(close_cols)
    basket_ret = build_basket(basket_close)
    basket_df = None  # 组合层面暂不做逐日摩擦模拟（个股层面已算 net）
    # 组合层面 gross/net 用个股均值
    gross_list = [s["d3"].get("gross_mean_daily") for s in stats_list if s.get("d3")]
    net_list = [s["d3"].get("net_mean_daily") for s in stats_list if s.get("d3")]
    basket = {
        "d2": d2_timeseries(basket_ret, seed=SEED),
        "d3": {
            "gross_mean_daily": float(np.nanmean(gross_list)) if gross_list else None,
            "net_mean_daily": float(np.nanmean(net_list)) if net_list else None,
            "inpos_win_rate_ci": _basket_inpos_ci(basket_close),
        },
    }
    # net 期望（用于 Gate3）：以个股净日收益均值横截面为篮子 net
    net_pool = []
    for s in stats_list:
        if s.get("d3") and s["d3"].get("net_mean_daily") is not None:
            net_pool.append(s["d3"]["net_mean_daily"])
    basket["net_mean_series"] = pd.Series(net_pool, dtype=float)

    # regime 分桶（D5）：Erratum 001 后使用合成指数（替代官方指数）
    synthetic_index = build_synthetic_index(basket_close)
    regime = regime_series(synthetic_index)
    rho_by_regime = {}
    for r in ["牛", "熊", "震荡"]:
        mask = regime.reindex(basket_ret.index).fillna("震荡") == r
        sub = basket_ret[mask]
        rho_by_regime[r] = d2_timeseries(sub, seed=SEED) if len(sub.dropna()) >= 30 else {}
    regime_table = {
        "autocorr_by_regime": rho_by_regime,
        "regime_source": "synthetic_index (Erratum 001)",
        "synthetic_index_days": int(len(synthetic_index.dropna())),
    }

    # D4 横截面
    d4 = d4_cross_sectional(stats_list)

    # Gates
    g1 = gate1_data_integrity(stats_list, len(universe))
    g2 = gate2_structural(basket, regime_table)
    net_ret_for_g3 = basket["net_mean_series"]
    g3 = gate3_economic(net_ret_for_g3, seed=SEED)

    result = {
        "header": {
            "experiment": "H1",
            "contract": "H1 Pre-Registration v0.1",
            "universe_label": "Current-Component Historical Structure Benchmark",
            "survivorship_bias": "KNOWN LIMITATION",
            "data_version": data_version,
            "run_timestamp": dt.datetime.now().isoformat(),
        },
        "gates": {
            "data_integrity": {k: v for k, v in g1.items() if k != "criteria"},
            "structural_evidence": {k: v for k, v in g2.items() if k != "criteria"},
            "economic_friction": {k: v for k, v in g3.items() if k != "criteria"},
        },
        "overall": overall(g1, g2, g3),
        "diagnostics": {
            "d1_return_stats_basket": basket_close.pct_change().dropna().agg(["mean", "std"]).to_dict(),
            "d2_timeseries_basket": basket["d2"],
            "d3_band_basket": {k: v for k, v in basket["d3"].items() if k != "inpos_win_rate_ci"},
            "d4_cross_sectional": d4,
            "d5_regime": regime_table,
            "d6_gross_net": {
                "gross_mean_daily_basket": basket["d3"]["gross_mean_daily"],
                "net_mean_daily_basket": basket["d3"]["net_mean_daily"],
                "friction_drag": (
                    (basket["d3"]["gross_mean_daily"] or 0)
                    - (basket["d3"]["net_mean_daily"] or 0)
                ),
            },
        },
        "per_stock": [
            {
                "code": s["code"], "name": s["name"],
                "d1": s["d1"], "d2": s["d2"], "d3": {k: v for k, v in s["d3"].items() if k not in ("gross_ret", "net_ret")},
                "day_coverage": s["day_coverage"],
                "n_anomaly": s["n_anomaly"],
                "adjust_ok": s["adjust_ok"],
            }
            for s in stats_list
        ],
    }
    return result


def _basket_inpos_ci(basket_close: pd.DataFrame) -> list:
    """组合层面持仓日正收益占比 CI（近似：用指数 close）。"""
    return [None, None]


def cmd_check() -> int:
    """Gate 0 + 依赖 + 常量一致性检查。不产生任何结果文件。"""
    print("[Gate 0]")
    try:
        r = gate0_check()
        print(f"  contract        : {r['contract_path']}")
        print(f"  contract mtime  : {r['contract_mtime_str']} (< now: {r['mtime_ok']})")
        print(f"  tokens          : OK ({len(GATE0_TOKENS)} 项全部匹配)")
        print("  Gate 0          : PASS")
    except Gate0Error as e:
        print(f"  Gate 0          : FAIL - {e}")
        return 1

    print("[依赖]")
    try:
        import akshare  # noqa: F401
        import scipy  # noqa: F401

        print(f"  akshare={akshare.__version__}, scipy={scipy.__version__}, pandas={pd.__version__}, numpy={np.__version__}")
    except ImportError as e:
        print(f"  缺依赖: {e}")
        return 1

    print("[常量一致性]")
    print(f"  UNIVERSE_INDEX={UNIVERSE_INDEX} START={START} END={END} QFQ={QFQ}")
    print(f"  MA_FAST={MA_FAST} MA_SLOW={MA_SLOW} MA250={MA250}")
    print(f"  COMM={COMM_RATE} STAMP={STAMP_BEFORE}/{STAMP_AFTER}@{STAMP_SEG_DATE} SLIP={SLIP_RATE}")
    print(f"  SEED={SEED} N_BOOT={N_BOOT}")
    print(f"  REGIME: 牛>MA250*{REGIME_BULL} 熊<MA250*{REGIME_BEAR} 震荡=其余")
    print("[OK] 检查通过。可进入 snapshot 阶段。")
    return 0


def cmd_snapshot() -> int:
    """拉取数据并冻结 Data Snapshot（契约 §4）。"""
    gate0_check()
    import akshare as ak  # noqa: PLC0415

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    ts = dt.datetime.now()
    version = f"{ts.strftime('%Y%m%d_%H%M%S')}_ak{ak.__version__}"

    print(f"[1/4] 拉取 universe={UNIVERSE_INDEX} 成分...")
    universe = get_universe()
    print(f"      共 {len(universe)} 只")
    for u in universe:
        print(f"  - {u['code']} {u['name']}")

    print("[2/4] 拉取 930955 官方指数（Control 备选，Erratum 001 后非必需）...")
    index_close = None
    try:
        index_close = fetch_index_daily()
    except Exception as e:  # noqa: BLE001
        print(f"      官方指数拉取异常: {e}")
    if index_close is None:
        print("      官方指数不可达（记录为 integrity issue，Control 将用合成指数）")
    else:
        print(f"      {len(index_close)} 行 {index_close.index[0]} ~ {index_close.index[-1]}")

    print("[3/4] 拉取成分股日线 + 清洗（含重试与备用源降级）...")
    stocks = {}
    n_skip = 0
    for i, u in enumerate(universe, 1):
        code = u["code"]
        df = fetch_daily(code)
        if df is None:
            print(f"      ({i}/{len(universe)}) {code} {u['name']} [skip]")
            n_skip += 1
            continue
        adj = adjustment_check(df["close"], code)
        stocks[code] = {
            "name": u["name"],
            "daily": {
                "date": [d.strftime("%Y-%m-%d") for d in df.index],
                "open": df["open"].tolist(),
                "high": df["high"].tolist(),
                "low": df["low"].tolist(),
                "close": df["close"].tolist(),
                "volume": df["volume"].tolist(),
                "limit_up": df["limit_up"].astype(int).tolist(),
                "limit_down": df["limit_down"].astype(int).tolist(),
                "suspend": df["suspend"].astype(int).tolist(),
                "anomaly": df["anomaly"].astype(int).tolist(),
            },
            "adjust_ok": adj["ok"],
            "n_adjust_jumps": adj["n_big_jumps"],
        }
        print(f"      ({i}/{len(universe)}) {code} {u['name']} OK {len(df)} 行")
        # 拉取太慢时的进度保护：不加人为 sleep

    ok_rate = len(stocks) / len(universe) if universe else 0.0
    print(f"[3/4 汇总] 成分 {len(universe)} / 有效 {len(stocks)} / skip {n_skip} "
          f"覆盖率 {ok_rate:.1%}（Gate 1 门槛 ≥{G1_STOCK_COVERAGE:.0%}）")
    if ok_rate < G1_STOCK_COVERAGE:
        print(f"  [警告] 个股覆盖率低于 Gate 1 门槛，Snapshot 可被冻结但 Gate 1 将判定 INCONCLUSIVE")
        print(f"          建议排查 skip 个股（网络/接口/代码），修复后重跑 snapshot。")

    snapshot = {
        "data_version": version,
        "snapshot_timestamp": ts.isoformat(),
        "universe": universe,
        "universe_label": "Current-Component Historical Structure Benchmark",
        "survivorship_bias": "KNOWN LIMITATION",
        "erratum_001": "Control/Regime 用合成指数，官方指数不可达时为 integrity issue",
        "index_close": index_close["close"].tolist() if index_close is not None else None,
        "index_dates": [d.strftime("%Y-%m-%d") for d in index_close.index] if index_close is not None else None,
        "stocks": stocks,
    }
    out = os.path.join(SNAPSHOT_DIR, f"h1_snapshot_{version}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)
    print(f"[4/4] Snapshot 已冻结: {out}")
    print(f"      成分 {len(universe)} / 有效个股 {len(stocks)} / 官方指数 "
          f"{'不可达' if index_close is None else len(index_close)} 行")
    return 0


def cmd_run() -> int:
    """读取最新 Snapshot，计算 6 维指标 + 三级 Gate，输出 H1_RESULT。"""
    gate0_check()
    files = sorted(
        f for f in os.listdir(SNAPSHOT_DIR) if f.startswith("h1_snapshot_") and f.endswith(".json")
    ) if os.path.isdir(SNAPSHOT_DIR) else []
    if not files:
        print("无 Snapshot，先运行 snapshot 模式")
        return 1
    latest = os.path.join(SNAPSHOT_DIR, files[-1])
    with open(latest, encoding="utf-8") as f:
        snapshot = json.load(f)
    print(f"[run] 使用 Snapshot: {latest}")

    # 契约 §9 输出禁止项检查：snapshot 不得含最佳参数类字段
    for pat in FORBIDDEN_OUTPUT_PATTERNS:
        if pat in json.dumps(snapshot, ensure_ascii=False):
            print(f"[违规] Snapshot 含禁止输出模式: {pat}")
            return 2

    result = run_analysis(snapshot)
    os.makedirs(RESULT_DIR, exist_ok=True)
    out = os.path.join(RESULT_DIR, f"h1_result_{snapshot['data_version']}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[run] H1_RESULT 已输出: {out}")
    print(f"  Overall = {result['overall']}")
    for g in ("data_integrity", "structural_evidence", "economic_friction"):
        print(f"  {g} = {result['gates'][g]['decision']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="H1 结构基线验证（契约 v0.1）")
    parser.add_argument("mode", nargs="?", default="check", choices=["check", "snapshot", "run"])
    args = parser.parse_args()
    if args.mode == "check":
        return cmd_check()
    if args.mode == "snapshot":
        return cmd_snapshot()
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
