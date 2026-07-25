# -*- coding: utf-8 -*-
"""
Tushare 第 3 数据源 provider（latent：需 token + 沙箱出口可达）
==============================================================
设计目标：在 step1 与 L5/L7 中作为「新浪」之后的第 3 资金来源（板块 / 个股主力净流入），
          用于交叉验证与冗余容错。

当前沙箱现实（2026-07-11 实测）：
  - api.tushare.com / api.tushare.org 均 DNS 不可达（getaddrinfo failed）。
  - 未配置 token。
  故默认 is_available() == False，调用方优雅降级到 新浪 / 本地聚合，不阻断流水线。

激活条件（二选一即可让本模块接管）：
  1) 沙箱获得 api.tushare.com 出口（或把抓取脚本放到可联网机器运行）；
  2) 配置 token：环境变量 TUSHARE_TOKEN 优先，或本文件同目录 .tushare_token 文件写入 token。

数据口径：
  - 个股主力净流入：pro.moneyflow(trade_date=...) 全市场单日，net_mf_amount(元) → 亿元。
  - 板块净额：本地 industry_map 成员 x 个股净额 聚合（复用东财成分映射，避免再次拉取板块接口）。
"""
import os
import socket
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "database", "vibe_research.db")
TOKEN_FILE = os.path.join(BASE, ".tushare_token")


class ProviderUnavailable(Exception):
    """tushare 不可用（无 token 或出口不可达）时抛出，调用方据此降级。"""


def get_token():
    t = os.environ.get("TUSHARE_TOKEN")
    if t:
        return t.strip()
    if os.path.exists(TOKEN_FILE):
        v = open(TOKEN_FILE, encoding="utf-8").read().strip()
        if v:
            return v
    return None


def host_reachable(host="api.tushare.com", port=443, timeout=4):
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(host, port)
        return True
    except Exception:
        return False


def is_available():
    """token 存在 且 出口可达，才认为可用。"""
    return bool(get_token()) and host_reachable()


def _ts_code(code6):
    if code6.startswith("6"):
        return code6 + ".SH"
    if code6.startswith(("0", "3")):
        return code6 + ".SZ"
    if code6.startswith(("4", "8")):
        return code6 + ".BJ"
    return code6


def individual_fund_flow(trade_date):
    """返回 {code6: 主力净流入(亿元)}，来自 pro.moneyflow(trade_date=...)。

    全市场单日 moneyflow 一次性返回（tushare 单笔上限 5000 行，A股约 5000 只，一页足够）。
    """
    tok = get_token()
    if not tok:
        raise ProviderUnavailable("未配置 TUSHARE_TOKEN（环境变量或 .tushare_token 文件）")
    if not host_reachable():
        raise ProviderUnavailable("api.tushare.com 出口不可达")
    import tushare as ts
    pro = ts.pro_api(tok)
    df = pro.moneyflow(trade_date=trade_date, limit=5000, offset=0)
    out = {}
    if df is None or len(df) == 0:
        return out
    for r in df.itertuples(index=False):
        code = str(getattr(r, "ts_code", "")).split(".")[0].zfill(6)
        net = getattr(r, "net_mf_amount", None)  # 元
        if net is None:
            continue
        try:
            out[code] = round(float(net) / 1e8, 2)
        except Exception:
            pass
    return out


def sector_fund_flow(trade_date):
    """个股净额(来自 individual_fund_flow) 按 东财 industry_map 聚合为板块净额(亿元)。"""
    indiv = individual_fund_flow(trade_date)
    if not indiv:
        return {}
    c = sqlite3.connect(DB)
    rows = c.execute("SELECT stock_code, industry_code FROM industry_map").fetchall()
    c.close()
    sec = {}
    for code, ic in rows:
        if code in indiv:
            sec[ic] = sec.get(ic, 0.0) + indiv[code]
    return {k: round(v, 1) for k, v in sec.items()}


def sector_flow_as_records(trade_date, crosswalk):
    """返回与 新浪 stock_fund_flow_industry 同构的 records：
       [{sector, net_now, ...}]，sector 用同花顺名（经 crosswalk 反查）。
       仅做净额维度（tushare 免费版无板块涨跌/家数，那些仍由新浪补）。
    """
    sec_em = sector_fund_flow(trade_date)
    em2thx = {r[1]: r[0] for r in crosswalk}
    recs = []
    for em_code, net in sec_em.items():
        thx = em2thx.get(em_code)
        if thx:
            recs.append({"sector": thx, "net_now": net, "net_5d": None,
                         "net_3d": None, "net_10d": None})
    return recs


if __name__ == "__main__":
    print("tushare available:", is_available())
    print("token set:", bool(get_token()))
