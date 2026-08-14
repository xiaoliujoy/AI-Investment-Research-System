"""
fetch_market_sheets.py - 每日自动获取 TheMarketMemo / tradecat 公开 Google Sheet（整本 xlsx 导出）

====================================================================
为什么用 /export?format=xlsx（整本工作簿）而不是单 tab CSV？
====================================================================
- 用户最初给的两个 Google Sheet 链接，其默认 gid 指向「控制/索引」tab，而非数据 tab。
  单 tab CSV 抓取会下到控制表（项目/值/说明），动量子模块读不到「综合排名」直接空跑。
- 改用整本工作簿导出：https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx
  一次把全部 tab（如 资产/市场结构/行业）下成一个 xlsx，与用户手动导出的文件结构一致。
- market_momentum.py / microstructure_lab.py 本来就读多 tab xlsx，无需改解析逻辑，全宇宙覆盖自动恢复。
- 该端点不需要 JS、不需要 cookie（与 CSV 同理，依赖表已「发布到网络」或链接可查看）。

====================================================================
前置条件（一次性确认）
====================================================================
- 这两个表需已「发布到网络」（File > Share > Publish to web）或链接 Anyone-with-link 可查看。
- 运行环境需有外网出口（本机有网即可；WorkBuddy 沙箱不一定有，属正常）。
- 若网络走代理，确保 Python urllib 能出网（或设置 HTTPS_PROXY 环境变量）。

====================================================================
用法
====================================================================
  python fetch_market_sheets.py
  下载到 backend/imports/ 下（.xlsx），并打印每个表成功/失败。
  成功后：
    python market_momentum.py        # 自动识别 imports/market_momentum_latest.xlsx（多 tab，全宇宙）
    （P3）python microstructure_lab.py imports/tradecat_sheet2_latest.xlsx

====================================================================
配置
====================================================================
SHEETS 列表：name / sheet_id / out(落盘文件名) / process(后续处理模块)
"""

import os
import sys
import hashlib
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
IMPORTS_DIR = os.path.abspath(os.path.join(HERE, "..", "imports"))
os.makedirs(IMPORTS_DIR, exist_ok=True)

# 用户提供的两个工作簿（整本导出，不依赖具体 tab gid）
SHEETS = [
    {
        "name": "全市场动量观察表",
        "sheet_id": "1WJQdanwSZ6dyClYh5swZMfrhXVhpta27FRb8tT6Ekus",
        "out": "market_momentum_latest.xlsx",
        "process": "momentum",   # 由 market_momentum.py 处理（多 tab 全宇宙）
    },
    {
        "name": "市场数据终端（加密微观结构 / tradecat）",
        "sheet_id": "1k16nGFCE7oBXrEqvTpHSA2Z5530GM_kou-wiWklTsfY",
        "out": "tradecat_sheet2_latest.xlsx",
        "process": "microstructure",  # 对应 microstructure_lab.py（P3 实验室，待接）
    },
]

UA = "Mozilla/5.0 (compatible; WorkBuddy-MomentumFetch/1.0)"
TIMEOUT = 40


def build_url(sheet_id):
    # 整本工作簿导出为 xlsx（含全部 tab）
    return "https://docs.google.com/spreadsheets/d/%s/export?format=xlsx" % sheet_id


def _is_xlsx(data):
    return data[:4] == b"PK\x03\x04"  # zip 签名 = xlsx 实质是 zip


def _looks_like_html(data):
    head = data[:1024].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        return True
    txt = data[:4096].decode("utf-8", "ignore").lower()
    if "google accounts" in txt or "sign in" in txt or "google 账号" in txt or "登录" in txt:
        return True
    return False


def fetch_one(cfg):
    url = build_url(cfg["sheet_id"])
    out_path = os.path.join(IMPORTS_DIR, cfg["out"])
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        return {"name": cfg["name"], "ok": False,
                "msg": "HTTP %d（多为该表未开启发布到网络 / 链接失效）" % e.code}
    except urllib.error.URLError as e:
        return {"name": cfg["name"], "ok": False,
                "msg": "网络不可达：%s（确认本机有外网出口 / 代理设置）" % e.reason}

    if _looks_like_html(data):
        return {"name": cfg["name"], "ok": False,
                "msg": "返回的是 HTML（登录页/错误页），说明该表未对匿名开放 /export。需开启「发布到网络」"}
    if not _is_xlsx(data):
        return {"name": cfg["name"], "ok": False,
                "msg": "返回内容不是 xlsx（前4字节=%r），导出端点可能需不同权限" % data[:4]}

    # 内容未变化则跳过写入（xlsx 是 zip，每次导出元数据可能变，故仅作提示）
    new_hash = hashlib.md5(data).hexdigest()
    old_hash = None
    if os.path.exists(out_path):
        with open(out_path, "rb") as f:
            old_hash = hashlib.md5(f.read()).hexdigest()
    changed = (old_hash != new_hash)
    if changed:
        with open(out_path, "wb") as f:
            f.write(data)
    return {"name": cfg["name"], "ok": True, "path": out_path,
            "bytes": len(data), "changed": changed,
            "process": cfg["process"]}


def main():
    print("[fetch] 开始获取 %d 个 Google Sheet（整本 xlsx 导出，免登录）" % len(SHEETS))
    results = []
    for cfg in SHEETS:
        print("  -> " + cfg["name"] + "  (" + cfg["sheet_id"] + ")")
        r = fetch_one(cfg)
        results.append(r)
        if r["ok"]:
            print("     成功：%s ｜ %d 字节 ｜ 变更=%s" % (r["path"], r["bytes"], r["changed"]))
        else:
            print("     失败：" + r["msg"])

    ok = sum(1 for r in results if r["ok"])
    print("\n完成：%d/%d 成功。" % (ok, len(results)))
    if ok < len(results):
        print("提示：失败的表通常是「未开启发布到网络」。在 Google Sheet 里 File>Share>Publish to web 开启后重试。")
    else:
        print("后续：python market_momentum.py  （自动识别 imports/market_momentum_latest.xlsx，多 tab 全宇宙）")
    return results


if __name__ == "__main__":
    res = main()
    sys.exit(0 if all(r["ok"] for r in res) else 1)
