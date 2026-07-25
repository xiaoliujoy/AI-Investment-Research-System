# -*- coding: utf-8 -*-
"""
panqian_auto.py —— 盘前纪要 7:30 自动抓取管道（Phase 2）

每天 7:30 由 automation 触发：扫描队列目录，把微信公众号「盘前纪要」文章
（.txt 全文 或 .url 链接）结构化灌入系统，并可选刷新盘前备忘录。

设计要点：
  - 队列目录 output/panqian_queue/：用户放入 panqian_YYYYMMDD.txt（已复制正文）
    或 panqian_YYYYMMDD.url（一行微信文章链接）。
  - .url 自动用 requests 抓取（连网机器可用；沙箱网络受限时失败并留待重试/告警）。
  - 清洗：删 WebFetch 包装行 + 折叠中文间空格 + 全角Ａ→半角A（否则个股名对不上）。
  - 解析：panqian_parser.parse_article → panqian_ingest.derive_feed（写 panqian_feed.json）。
  - 校验：per skill 校验清单；失败写告警。
  - 处理完移入 output/panqian_archive/，写 output/panqian_auto_status.json + 日志。
  - 成功且 --memo-only：刷新 memo HTML（run_daily --skip-step1 --memo-only，盘前版）。
  - 失败告警：企微/Server酱（若已配置 webhook）。

用法：
  python panqian_auto.py                  # 处理队列，日期=今天
  python panqian_auto.py --date 2026-07-16
  python panqian_auto.py --memo-only      # 成功后刷新盘前备忘录
  python panqian_auto.py --queue DIR --archive DIR
"""
from __future__ import annotations

import os
import re
import sys
import json
import glob
import shutil
import datetime
import argparse
import urllib.request
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

OUT = os.path.join(BASE, "output")
QUEUE = os.path.join(OUT, "panqian_queue")
ARCHIVE = os.path.join(OUT, "panqian_archive")
STATUS_FILE = os.path.join(OUT, "panqian_auto_status.json")
LOG_FILE = os.path.join(OUT, "panqian_auto.log")
ALERT_LOG = os.path.join(OUT, "panqian_alerts.log")

_VENV_PY = "C:/Users/JOY/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
PY = _VENV_PY if os.path.exists(_VENV_PY) else sys.executable

SECTION_KEYS = ("hotspot", "announce", "global", "limit_up",
                "institution", "new_high", "new_stock", "hot_list")

# 清洗：删 WebFetch / 模型摘要包装行
_WRAP_PAT = re.compile(
    r"WebFetch|以下是文章正文|根据您提供的|已为您提取|微信文章|公众号|正文纯文本",
    re.I)
# 折叠中文之间的字间空格（修复 天 智 航→天智航）
_CJK_SPACE = re.compile(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])")


def _log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def clean_text(t: str) -> str:
    lines = [ln for ln in t.splitlines() if not _WRAP_PAT.search(ln)]
    t = "\n".join(lines)
    t = _CJK_SPACE.sub("", t)
    t = t.replace("Ａ", "A")
    return t.strip() + "\n"


def guess_date_from_name(name: str) -> str:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4})(\d{2})(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def validate_feed(feed: dict):
    """返回 (ok, issues)。"""
    issues = []
    if not feed.get("has_data"):
        issues.append("feed.has_data=False")
    ad = feed.get("article_date")
    if not ad:
        issues.append("article_date 为空")
    if not feed.get("cro_feed", {}).get("hot_list_top"):
        issues.append("cro_feed.hot_list_top 为空（热榜 top5 缺失）")
    sec = feed.get("stats", {})
    n_seg = sum(1 for k in SECTION_KEYS if sec.get(k))
    if n_seg < 4:
        issues.append(f"分段过少（仅 {n_seg} 段，期望≥4）")
    if not feed.get("narrative_feed") and not feed.get("catalyst_feed"):
        issues.append("narrative_feed 与 catalyst_feed 均空")
    rl = feed.get("risk_landmines") or []
    if not isinstance(rl, list):
        issues.append("risk_landmines 格式异常")
    return (len(issues) == 0), issues


# ── 告警（企微 markdown / Server酱 text）──
def _webhook(name: str):
    v = os.environ.get(name)
    if v:
        return v
    envf = os.path.join(BASE, ".env")
    if os.path.exists(envf):
        try:
            for line in open(envf, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, vv = line.split("=", 1)
                if k.strip() == name:
                    return vv.strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def _post_json(url, payload, timeout=15):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def send_alert(title: str, lines: list):
    sent = []
    wh = _webhook("WECHAT_WEBHOOK_URL")
    if wh:
        md = f"# ⚠️ {title}\n" + "\n".join(lines)
        try:
            _post_json(wh, {"msgtype": "markdown",
                            "markdown": {"content": md}})
            sent.append("wecom")
        except Exception as e:  # noqa
            _log(f"企微告警发送失败：{e}")
    sc = _webhook("SERVERCHAN_SENDKEY")
    if sc:
        try:
            _post_json(f"https://sctapi.ftqq.com/{sc}.send",
                       {"title": title, "desp": "\n".join(lines)})
            sent.append("serverchan")
        except Exception as e:  # noqa
            _log(f"Server酱告警发送失败：{e}")
    try:
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] "
                    f"{title} :: {';'.join(lines)}\n")
    except Exception:
        pass
    return sent


def process_txt(path: str, adate: str):
    """处理一个 .txt 文章文件。返回结果 dict。"""
    name = os.path.basename(path)
    item = {"file": name, "status": "fail", "error": "",
            "headline": "", "hot_top": 0, "risk": 0}
    try:
        raw = open(path, encoding="utf-8", errors="ignore").read()
        text = clean_text(raw)
        if len(text.strip()) < 50:
            item["error"] = "清洗后正文过短（<50字），疑似空文件/纯包装"
            return item
        from panqian_parser import parse_article
        from panqian_ingest import derive_feed
        parsed = parse_article(text)
        parsed["article_date"] = adate
        parsed["source_url"] = ""
        feed_path = derive_feed(parsed)
        feed = json.load(open(feed_path, encoding="utf-8"))
        ok, issues = validate_feed(feed)
        item["headline"] = feed.get("headline", "")
        item["hot_top"] = len(feed.get("cro_feed", {}).get("hot_list_top", []) or [])
        item["risk"] = len(feed.get("risk_landmines", []) or [])
        if not ok:
            item["error"] = "校验未通过：" + "；".join(issues)
            item["status"] = "invalid"
            _log(f"  ✗ {name} 校验未过：{issues}")
        else:
            item["status"] = "ok"
            _log(f"  ✓ {name} 灌入成功：{item['headline']} "
                 f"（热榜{item['hot_top']} 地雷{item['risk']}）")
        return item
    except Exception as e:  # noqa
        item["error"] = f"异常：{repr(e)[:200]}"
        _log(f"  ✗ {name} 异常：{e}")
        return item


def process_url(path: str, adate: str):
    """处理一个 .url 链接文件（一行一个微信文章链接）。返回结果 dict。"""
    name = os.path.basename(path)
    item = {"file": name, "status": "fail", "error": "",
            "headline": "", "hot_top": 0, "risk": 0}
    try:
        lines = [l.strip() for l in
                 open(path, encoding="utf-8", errors="ignore").read().splitlines()
                 if l.strip()]
        url = lines[0] if lines else ""
        if not url.startswith("http"):
            item["error"] = "URL 文件首行非 http 链接"
            return item
        _log(f"  … 抓取 {url}")
        from panqian_parser import _fetch_url
        text = _fetch_url(url)
        # 落盘为同名 .txt，后续走 txt 流程
        txt_path = os.path.join(os.path.dirname(path),
                                os.path.splitext(name)[0] + ".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        item = process_txt(txt_path, adate)
        item["file"] = name  # 保留原 .url 名用于归档标记
        item["source_url"] = url
        # 清理中间 .txt（结构化结果已落盘 panqian_feed.json / panqian_YYYYMMDD.json），
        # 否则它会残留在队列，下一轮被当成新文章重复灌入。
        if item["status"] in ("ok", "invalid") and os.path.exists(txt_path):
            try:
                os.remove(txt_path)
            except Exception:
                pass
        return item
    except Exception as e:  # noqa
        item["error"] = f"URL 抓取失败（沙箱网络受限？）：{repr(e)[:200]}"
        _log(f"  ✗ {name} {item['error']}")
        return item


def run_memo_only():
    _log("刷新盘前备忘录（run_daily --skip-step1 --memo-only）…")
    try:
        proc = subprocess.run(
            [PY, "run_daily.py", "--skip-step1", "--memo-only"],
            cwd=BASE, capture_output=True, text=True, timeout=1200)
        ok = proc.returncode == 0
        _log(f"  备忘录刷新 rc={proc.returncode} "
             f"{'OK' if ok else 'FAIL'}: {proc.stderr[-300:]}")
        return ok
    except Exception as e:  # noqa
        _log(f"  备忘录刷新异常：{e}")
        return False


def ensure_queue():
    os.makedirs(QUEUE, exist_ok=True)
    os.makedirs(ARCHIVE, exist_ok=True)
    readme = os.path.join(QUEUE, "README.txt")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as f:
            f.write(
                "盘前纪要自动抓取队列目录\n"
                "================================\n"
                "把微信公众号「盘前纪要」文章放到本目录，每日 7:30 自动结构化灌入系统。\n\n"
                "放置方式（二选一）：\n"
                "1) 复制文章全文 → 存为  panqian_YYYY-MM-DD.txt\n"
                "   （推荐：不受沙箱网络限制，最稳妥）\n"
                "2) 把文章链接放入  panqian_YYYY-MM-DD.url（文件内第一行写 mp.weixin.qq.com 链接）\n"
                "   （需联网机器：脚本会用 requests 直接抓取；沙箱失败则留待重试并告警）\n\n"
                "处理成功后文件移入 ../panqian_archive/；状态见 ../panqian_auto_status.json。\n"
            )


def main():
    global QUEUE, ARCHIVE
    ap = argparse.ArgumentParser(description="盘前纪要 7:30 自动抓取")
    ap.add_argument("--date", help="文章日期 YYYY-MM-DD（缺省按文件名/今天）")
    ap.add_argument("--memo-only", action="store_true",
                    help="灌入成功后刷新盘前备忘录 HTML")
    ap.add_argument("--queue", default=QUEUE)
    ap.add_argument("--archive", default=ARCHIVE)
    args = ap.parse_args()

    QUEUE, ARCHIVE = args.queue, args.archive
    ensure_queue()

    today = datetime.date.today().isoformat()
    run_at = datetime.datetime.now().isoformat(timespec="seconds")
    _log(f"=== 盘前纪要自动抓取启动 date={args.date or 'auto'} ===")

    files = sorted(glob.glob(os.path.join(QUEUE, "*.txt")) +
                   glob.glob(os.path.join(QUEUE, "*.url")))
    # 排除 README
    files = [f for f in files if os.path.basename(f).upper() != "README.TXT"]
    results = []

    if not files:
        _log("队列为空：无待处理文章。")
        status = {"run_at": run_at, "date": args.date or today,
                  "queue": QUEUE, "items": [],
                  "summary": {"found": 0, "ok": 0, "invalid": 0, "failed": 0},
                  "memo_refreshed": None}
        json.dump(status, open(STATUS_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        _log("=== 结束（空队列）===")
        return 0

    for path in files:
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        adate = args.date or guess_date_from_name(name) or today
        if ext == ".url":
            item = process_url(path, adate)
        else:
            item = process_txt(path, adate)
        results.append(item)
        # 归档：成功的移走；invalid 移走（保留 feed 但标记）；failed 的 .url 留待重试
        if item["status"] in ("ok", "invalid"):
            try:
                shutil.move(path, os.path.join(ARCHIVE, name))
            except Exception:
                pass
        elif item["status"] == "fail" and ext == ".url":
            # 抓取失败：保留 .url 在队列，等下一日/人工处理
            _log(f"  保留 {name} 在队列（抓取失败，待重试）")

    ok = sum(1 for r in results if r["status"] == "ok")
    invalid = sum(1 for r in results if r["status"] == "invalid")
    failed = sum(1 for r in results if r["status"] == "fail")

    memo_ok = None
    if ok > 0 and args.memo_only:
        memo_ok = run_memo_only()

    status = {
        "run_at": run_at,
        "date": args.date or today,
        "queue": QUEUE,
        "items": results,
        "summary": {"found": len(results), "ok": ok,
                    "invalid": invalid, "failed": failed},
        "memo_refreshed": memo_ok,
    }
    json.dump(status, open(STATUS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # 失败告警
    if failed > 0 or invalid > 0:
        lines = [f"日期：{status['date']}", f"成功 {ok} 项 / 校验未过 {invalid} 项 / 失败 {failed} 项",
                 "明细："]
        for r in results:
            if r["status"] != "ok":
                lines.append(f"- {r['file']}：{r['error'][:120]}")
        lines.append("处理：将文章复制为 .txt 放入队列后重试，或检查联网/链接。")
        sent = send_alert("盘前纪要自动抓取异常", lines)
        _log(f"已发送告警 → {sent or '（未配置渠道，仅写日志）'}")

    _log(f"=== 结束：成功{ok} 校验未过{invalid} 失败{failed} "
         f"备忘录刷新={memo_ok} ===")
    # 退出码：有失败项则非零（便于 automation 感知）
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
