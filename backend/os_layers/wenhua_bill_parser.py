# -*- coding: utf-8 -*-
"""
文华财经 WH6 本地结算单解析器（只读）
=====================================
文华把每日结算单以 GBK 文本存在:
  <WH6>/Users/<uid>/Data/Bill/D{YYYYMMDD}[o|n].txt
其中 o=日盘, n=夜盘(如有)。文件含「成交记录 Transaction Record」竖线表。

本脚本: 遍历所有账单, 抽取成交记录 + 资金状况 + 出入金, 输出归一化账本 CSV。
只读源文件, 不修改任何客户端数据。
"""
import argparse
import csv
import glob
import os
import re
import sqlite3
import sys
from datetime import date

DEFAULT_BILL_DIR = r"D:\wh6通用版\Users\0-1200-F201E306EF12FE5E833539BE7442E463\Data\Bill"
OUT_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "mt5_raw", "wenhua_futures_trades.csv")
OUT_DB = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "database", "vibe_research.db")


def _split_row(line):
    parts = [p.strip() for p in line.split("|")]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def parse_bill(path):
    """返回 dict: trade_rows(list), equity(float|None), deposit(float), withdrawal(float), bdate(str)"""
    with open(path, encoding="gbk", errors="replace") as f:
        lines = f.read().splitlines()

    out = {"trade_rows": [], "equity": None, "deposit": 0.0, "withdrawal": 0.0, "bdate": None}
    in_tx = False
    saw_header = False
    for ln in lines:
        s = ln.strip()
        if "成交记录" in s and "Transaction Record" in s:
            in_tx = True
            saw_header = False
            continue
        if in_tx:
            if s.startswith("|"):
                if not saw_header:
                    saw_header = True  # 表头行, 跳过
                    continue
                if s.startswith("|共"):  # 汇总行
                    in_tx = False
                    continue
                if set(s) <= set("-| "):  # 分隔线
                    continue
                cols = _split_row(s)
                # 期望 17 列: 日期,单元,交易所,编码,品种,合约,买卖,投保,价,手,额,开平,费,平盈,权利金,序号,账号
                if len(cols) >= 15 and re.match(r"^\d{8}$", cols[0] or ""):
                    out["trade_rows"].append(cols)
            else:
                if s.startswith("平仓明细") or s.startswith("资金状况") or s.startswith("出入金"):
                    in_tx = False
        # 资金状况: 客户权益 Client Equity
        m = re.search(r"客户权益\s*Client Equity[:：]?\s*([-\d.,]+)", s)
        if m and out["equity"] is None:
            try:
                out["equity"] = float(m.group(1).replace(",", ""))
            except ValueError:
                pass
        m2 = re.search(r"日期\s*Date[:：]?\s*(\d{8})", s)
        if m2 and out["bdate"] is None:
            out["bdate"] = m2.group(1)
    # 出入金汇总行: |共   N条| ... | Deposit | Withdrawal |
    for ln in lines:
        if ln.strip().startswith("|共") and "Deposit" not in ln:
            pass
    return out


def parse_all(bill_dir):
    files = sorted(glob.glob(os.path.join(bill_dir, "D*.txt")))
    all_rows = []
    equity_series = []
    stats = {"files": 0, "files_with_trades": 0, "empty_bills": 0,
             "trade_count": 0, "accounts": set(), "brokers": set(),
             "products": set(), "exchanges": set(), "date_min": None, "date_max": None,
             "realized_sum": 0.0, "premium_sum": 0.0, "fee_sum": 0.0,
             "deposit_sum": 0.0, "withdrawal_sum": 0.0}
    for fp in files:
        try:
            b = parse_bill(fp)
        except Exception as e:
            print("  [warn] parse %s failed: %s" % (os.path.basename(fp), e), file=sys.stderr)
            continue
        stats["files"] += 1
        if not b["trade_rows"]:
            stats["empty_bills"] += 1
            continue
        stats["files_with_trades"] += 1
        for cols in b["trade_rows"]:
            # cols index (1-based from split): 0日期 1单元 2交易所 3编码 4品种 5合约 6买卖 7投保 8价 9手 10额 11开平 12费 13平盈 14权利金 15序号 16账号
            tdate = cols[0]
            unit = cols[1]
            exch = cols[2]
            code = cols[3]
            product = cols[4]
            instr = cols[5]
            bs = cols[6]
            sh = cols[7]
            price = _f(cols[8])
            lots = _f(cols[9])
            turnover = _f(cols[10])
            oc = cols[11]
            fee = _f(cols[12])
            realized = _f(cols[13])
            premium = _f(cols[14])
            transno = cols[15]
            acct = cols[16] if len(cols) > 16 else unit
            pnl = (realized or 0) + (premium or 0)  # 期货看平仓盈亏, 期权看权利金净收支
            all_rows.append({
                "bill_date": b["bdate"] or tdate,
                "trade_date": tdate, "account": acct, "unit": unit,
                "exchange": exch, "trade_code": code, "product": product,
                "instrument": instr, "bs": bs, "sh": sh, "oc": oc,
                "price": price, "lots": lots, "turnover": turnover, "fee": fee,
                "realized_pnl": realized, "premium": premium, "net_pnl": pnl,
                "trans_no": transno, "source_file": os.path.basename(fp),
            })
            stats["trade_count"] += 1
            stats["accounts"].add(acct)
            stats["products"].add(product)
            stats["exchanges"].add(exch)
            stats["realized_sum"] += (realized or 0)
            stats["premium_sum"] += (premium or 0)
            stats["fee_sum"] += (fee or 0)
            if stats["date_min"] is None or tdate < stats["date_min"]:
                stats["date_min"] = tdate
            if stats["date_max"] is None or tdate > stats["date_max"]:
                stats["date_max"] = tdate
        if b["equity"] is not None:
            equity_series.append((b["bdate"] or "", b["equity"]))
    return all_rows, equity_series, stats


def _f(x):
    if x is None:
        return None
    x = x.replace(",", "").replace(" ", "")
    if x == "":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bill-dir", default=DEFAULT_BILL_DIR)
    ap.add_argument("--out-csv", default=OUT_CSV)
    ap.add_argument("--no-db", action="store_true", help="不写库, 仅输出CSV")
    args = ap.parse_args()

    print("扫描账单目录: %s" % args.bill_dir)
    rows, equity, stats = parse_all(args.bill_dir)
    print("账单文件总数: %d | 含成交: %d | 空账单: %d" %
          (stats["files"], stats["files_with_trades"], stats["empty_bills"]))
    print("成交记录总笔数: %d" % stats["trade_count"])
    if stats["date_min"]:
        print("时间跨度: %s ~ %s" % (stats["date_min"], stats["date_max"]))
    print("账户: %s" % ", ".join(sorted(stats["accounts"])))
    print("期货公司/监控: %s" % ", ".join(sorted(stats["exchanges"])))
    print("品种: %s" % ", ".join(sorted(stats["products"])))
    print("平仓盈亏合计: %.2f | 权利金净收支: %.2f | 手续费合计: %.2f" %
          (stats["realized_sum"], stats["premium_sum"], stats["fee_sum"]))
    net = stats["realized_sum"] + stats["premium_sum"] - stats["fee_sum"]
    print("★ 净盈亏(平仓盈亏+权利金-手续费): %.2f" % net)

    os.makedirs(os.path.dirname(os.path.abspath(args.out_csv)), exist_ok=True)
    cols = ["bill_date", "trade_date", "account", "unit", "exchange", "trade_code",
            "product", "instrument", "bs", "sh", "oc", "price", "lots", "turnover",
            "fee", "realized_pnl", "premium", "net_pnl", "trans_no", "source_file"]
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print("\n✅ 账本已写出: %s (%d 行)" % (args.out_csv, len(rows)))

    if not args.no_db:
        try:
            import sqlite3 as _sq
            con = _sq.connect(OUT_DB)
            con.execute("""CREATE TABLE IF NOT EXISTS wenhua_futures_trade (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_date TEXT, trade_date TEXT, account TEXT, unit TEXT,
                exchange TEXT, trade_code TEXT, product TEXT, instrument TEXT,
                bs TEXT, sh TEXT, oc TEXT, price REAL, lots REAL, turnover REAL,
                fee REAL, realized_pnl REAL, premium REAL, net_pnl REAL,
                trans_no TEXT, source_file TEXT, ingested_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            con.execute("DELETE FROM wenhua_futures_trade")
            con.executemany(
                "INSERT INTO wenhua_futures_trade (bill_date,trade_date,account,unit,exchange,trade_code,product,instrument,bs,sh,oc,price,lots,turnover,fee,realized_pnl,premium,net_pnl,trans_no,source_file) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(r["bill_date"], r["trade_date"], r["account"], r["unit"], r["exchange"],
                  r["trade_code"], r["product"], r["instrument"], r["bs"], r["sh"], r["oc"],
                  r["price"], r["lots"], r["turnover"], r["fee"], r["realized_pnl"],
                  r["premium"], r["net_pnl"], r["trans_no"], r["source_file"]) for r in rows])
            con.commit()
            print("✅ 已写入数据库 wenhua_futures_trade: %d 行" % len(rows))
            con.close()
        except Exception as e:
            print("  [warn] 写库失败: %s" % e, file=sys.stderr)


if __name__ == "__main__":
    main()
