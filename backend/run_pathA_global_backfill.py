# -*- coding: utf-8 -*-
"""
run_pathA_global_backfill.py —— 全球数据解墙「路径 A」一键脚本

背景：cio_agent 的全球市场看板有 8 项在本沙箱因东财/Yahoo 被封而显示「未接入」：
    纳指 NDX / SOXX 半导体 / 恒生科技 HSTECH / 美元 DXY / 美债2Y US2Y /
    美债10Y US10Y / TIPS 通胀债 / 比特币 BTC。
路径 A（本机联网）：清掉死的代理 127.0.0.1:7890 → 把上述 8 个符号的日线历史
    回填进 global_history（直接打 Yahoo chart REST 取数 + Binance 填加密 + akshare 填美债），看板随即全部点亮。

本脚本「一键」完成：
  1) 若当前不是 venv 解释器，自动 re-exec 进 managed venv（akshare 已装好）；
  2) 清空所有代理环境变量（http_proxy/https_proxy/...），让请求直连；
  3) 多源顺序回填：akshare(美债) → Binance(加密) → Yahoo(chart REST,带cookie+crumb抗429) → Stooq(兜底)；
  4) 回填 8 个符号（5 年日线，约 1~3 分钟）；
  5) 校验每张表落地行数并报告。

用法（任选其一）：
  · 双击本 .py 文件（会弹出黑窗，跑完按回车关闭）
  · 终端执行：python run_pathA_global_backfill.py
  · 只补单个：python run_pathA_global_backfill.py --symbol BTC
  · 受限网络：python run_pathA_global_backfill.py --local-only  （仅 akshare + Binance）

注意：本机运行即可（住宅/正常 IP）。Yahoo chart REST 比 yfinance 库更抗 429（单请求+间隔+退避）；
      Stooq 当前对程序化 CSV 请求返回 HTML 拦截页，故退为最后兜底；若 Yahoo 偶发不可达会自动回退。
"""
from __future__ import annotations

import os
import sys
import subprocess
import importlib.util

# 给所有 requests（含 yfinance/akshare/直连 Yahoo）注入默认超时，防止回填挂起
import requests
_ORIG_REQUEST = requests.Session.request
def _request_with_timeout(self, method, url, **kwargs):
    kwargs.setdefault("timeout", 20)
    return _ORIG_REQUEST(self, method, url, **kwargs)
requests.Session.request = _request_with_timeout

# ── 路径与符号配置 ──────────────────────────────────────────────
VENV_PY = r"C:\Users\JOY\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
BACKFILL = os.path.join(HERE, "global_history_backfill.py")
DB = os.path.join(HERE, "database", "vibe_research.db")

# 看板里「未接入」的 8 个符号（全部走 yfinance 兜底，键名与 cio_agent._GLOBAL_BOARD_SPEC 一致）
TARGET_SYMBOLS = ["NDX", "SOXX", "HSTECH", "DXY", "US2Y", "US10Y", "TIPS", "BTC"]


def _clear_proxy():
    """清掉所有代理环境变量，让 yfinance/requests 直连（绕过沙箱里死的 127.0.0.1:7890）。"""
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY", "ftp_proxy", "FTP_PROXY"):
        os.environ.pop(k, None)


def _same_venv() -> bool:
    return os.path.abspath(sys.executable).replace("\\", "/").lower() == \
           os.path.abspath(VENV_PY).replace("\\", "/").lower()


def _bootstrap_into_venv():
    """若当前不是 venv，re-exec 进去（保留命令行参数）。清代理后再 re-exec 才干净。"""
    if _same_venv():
        return
    _clear_proxy()
    cmd = [VENV_PY, __file__, *sys.argv[1:]]
    try:
        rc = subprocess.call(cmd, timeout=1800)
    except subprocess.TimeoutExpired:
        print(f"[错误] 回填超时（1800s），可能存在网络阻断，请检查联网后重试。")
        rc = 1
    except FileNotFoundError:
        print(f"[错误] 找不到 venv 解释器：{VENV_PY}\n请先确认 managed python 已安装。")
        rc = 1
    sys.exit(rc)


def _ensure_pkg(name: str):
    """若包未装，pip install（安静模式）。已装则秒过。"""
    try:
        if importlib.util.find_spec(name) is not None:
            return
    except Exception:
        pass
    print(f"[安装] pip install {name} ...（首次约数十秒，需联网）")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", name])


def _verify(symbols):
    """回填后验收：每张表落了多少行。"""
    import sqlite3
    if not os.path.exists(DB):
        print(f"[警告] 未找到数据库：{DB}")
        return
    con = sqlite3.connect(DB)
    print("\n── 回填落地校验（global_history 行数）──")
    for sym in symbols:
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM global_history WHERE symbol=?", (sym,)).fetchone()[0]
            flag = "✅ 已点亮" if n > 50 else ("⚠️ 行数偏少" if n > 0 else "❌ 仍为空")
            print(f"  {sym:8s}: {n:5d} 行  {flag}")
        except Exception as e:
            print(f"  {sym:8s}: 查询失败 {e}")
    con.close()


def _rows_of(mod, sym):
    import sqlite3
    if not os.path.exists(DB):
        return 0
    con = sqlite3.connect(DB)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM global_history WHERE symbol=?", (sym,)).fetchone()[0]
    finally:
        con.close()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", help="只回填单个符号，如 BTC（默认补全部 8 个）")
    ap.add_argument("--local-only", action="store_true",
                    help="受限网络(如本沙箱)：只用 akshare/Sina 可达源，不撞 Yahoo/Stooq")
    args = ap.parse_args()

    _clear_proxy()
    # 直连 Yahoo chart REST 依赖 requests（akshare 已带，这里确保存在）；不再依赖 yfinance 库
    _ensure_pkg("requests")

    import importlib.util
    spec = importlib.util.spec_from_file_location("ghb", BACKFILL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    syms = [args.symbol] if args.symbol else TARGET_SYMBOLS
    print(f"\n[开始] 全球历史回填，目标符号：{', '.join(syms)}")
    if args.local_only:
        print("[模式] --local-only：跳过会被限流的 Yahoo/Stooq，仅用 akshare + Binance 可达源。")
        print("       能填的美债(US2Y/US10Y)等会点亮；若 Binance 也不可达则需放开网络。\n")
    else:
        print("[提示] 多源顺序：akshare → Binance(加密) → Yahoo(chart REST,抗429) → Stooq(兜底)，请稍候…\n")

    summary = mod.run(syms, local_only=args.local_only)
    print("── 回填结果 ──")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    _verify(syms)

    lit = [s for s in syms if _rows_of(mod, s) > 50]
    print(f"\n[完成] 本次点亮 {len(lit)}/{len(syms)} 项：{', '.join(lit) or '无'}")
    if not args.local_only:
        print("         下一步：本机跑 run_daily.py（或交易日 8:30 自动流水线）重新生成 memo，")
        print("         即可在「🌏 全球看板」看到真实数据。")
    else:
        print("         受限网络下其余项请在可联网机器上双击本脚本运行（默认模式走 Yahoo/Binance）。")


if __name__ == "__main__":
    _bootstrap_into_venv()
    main()
    try:
        input("\n按回车退出…")
    except (EOFError, KeyboardInterrupt):
        pass
