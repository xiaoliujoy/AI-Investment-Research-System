#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_intraday_watch.py — 盘中 Watch List 数据装配器（westock 实时 -> runner 输入 JSON）

职责：把 westock `data_sector mode=ranking` 与 `data_quote`(指数) 的原始返回，
转换成 intraday_watch_runner.py 消费的 JSON 契约：
    {date, time_point, watch_sectors, sector_rank[], sector_net{}, plate_ranking, index_amount}

关键映射：
  - 资金（精确主力净流入，万元->亿）：data.fundflow.plate/concept.top|bottom[].zljlr
      共 12 个板块有实数；其余板块 runner 只能靠 plate_ranking 定符号。
  - 涨幅 + 领涨股：data.rank.plate/concept/area[].{bd_name,bd_code,bd_zdf,nzg_code,nzg_name,nzg_zdf}
      覆盖全部板块（实时）。
  - 半日成交额近似：data_quote 的 sh000001/sz399001/sz399006.amount（元）累加。

热点筛选（动态，不写死）：
  1) 资金热点 = fundflow.plate.top + concept.top（净流入为正）的板块名；
  2) 动量热点 = rank.plate+concept 中按 bd_zdf 降序取前 N 个（净流入榜未覆盖的强动量线）；
  合并去重后截断到 cap（默认 10）。

用法：
  python build_intraday_watch.py --rank <westock ranking json> --idx <index quote json> \
      --time 1430 --date 2026-08-06 --out backend/output/intraday_1430_2026-08-06.json

  --rank / --idx 接受 westock 工具返回的原始 JSON（可含 {"ok":true,"data":{...}} 包裹，
  自动剥壳）。转换器只读、不联网。
"""
import argparse
import json
import os
import re


def _unpack(raw):
    """剥掉 {"ok":true,"data":{...}} 包裹，返回 data dict。"""
    if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], dict):
        return raw["data"]
    return raw


def _norm(s):
    if not s:
        return ""
    for rep in ("概念", "Ⅱ", "Ⅲ", "II", "III", "（", "）", "(", ")", " "):
        s = s.replace(rep, "")
    return s.strip()


def load_raw(path):
    with open(path, encoding="utf-8") as f:
        return _unpack(json.load(f))


def build_sector_net(fundflow):
    """fundflow.plate/concept.top|bottom -> {板块名: 净流入(亿)}。"""
    net = {}
    for grp in ("plate", "concept"):
        g = fundflow.get(grp) or {}
        for key in ("top", "bottom"):
            for x in g.get(key) or []:
                name = x.get("name")
                zljlr = x.get("zljlr")
                if name and zljlr is not None:
                    try:
                        net[name] = float(zljlr) / 10000.0  # 万元 -> 亿
                    except (TypeError, ValueError):
                        pass
    return net


def build_plate_ranking(fundflow):
    top, bottom = [], []
    for grp in ("plate", "concept"):
        g = fundflow.get(grp) or {}
        for x in g.get("top") or []:
            if x.get("name"):
                top.append(x["name"])
        for x in g.get("bottom") or []:
            if x.get("name"):
                bottom.append(x["name"])
    return {"top": top, "bottom": bottom}


def build_sector_rank(rank):
    """rank.plate/concept/area 主列表 -> 按 bd_code 去重的 sector_rank[]。"""
    sr = {}
    for grp in ("plate", "concept", "area"):
        for r in rank.get(grp) or []:
            code = r.get("bd_code")
            if not code:
                continue
            sr[code] = {
                "bd_name": r.get("bd_name"),
                "bd_code": code,
                "bd_zdf": r.get("bd_zdf"),
                "nzg_code": r.get("nzg_code"),
                "nzg_name": r.get("nzg_name"),
                "nzg_zdf": r.get("nzg_zdf"),
            }
    return list(sr.values())


def select_hot(rank, fundflow, top_n_money=6, top_n_momentum=4, cap=10):
    """动态挑选今日热点板块：资金热点 ∪ 动量热点。"""
    money = []
    for grp in ("plate", "concept"):
        for x in (fundflow.get(grp) or {}).get("top") or []:
            if x.get("name"):
                money.append(x["name"])

    seen = set(money)
    cand = []
    for grp in ("plate", "concept"):
        for r in rank.get(grp) or []:
            cand.append(r)
    cand.sort(key=lambda r: float(r.get("bd_zdf") or 0), reverse=True)

    momentum = []
    for r in cand:
        n = r.get("bd_name")
        if n and n not in seen:
            momentum.append(n)
            seen.add(n)
        if len(momentum) >= top_n_momentum:
            break

    hot = money + momentum
    out, s = [], set()
    for n in hot:
        if n not in s:
            out.append(n)
            s.add(n)
    return out[:cap]


def build_index_amount(idx):
    out = {}
    for code, d in (idx or {}).items():
        if isinstance(d, dict) and "amount" in d:
            out[code] = d["amount"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", required=True, help="westock data_sector mode=ranking 原始 JSON")
    ap.add_argument("--idx", required=True, help="westock data_quote(指数) 原始 JSON")
    ap.add_argument("--time", required=True, help="4位 HHMM")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", required=True, help="输出 runner 输入 JSON 路径")
    ap.add_argument("--top-money", type=int, default=6)
    ap.add_argument("--top-momentum", type=int, default=4)
    ap.add_argument("--cap", type=int, default=10)
    args = ap.parse_args()

    rank_raw = load_raw(args.rank)
    idx_raw = load_raw(args.idx)

    fundflow = rank_raw.get("fundflow") or {}
    rank = rank_raw.get("rank") or {}

    sector_net = build_sector_net(fundflow)
    plate_ranking = build_plate_ranking(fundflow)
    sector_rank = build_sector_rank(rank)
    index_amount = build_index_amount(idx_raw)
    watch = select_hot(rank, fundflow, args.top_money, args.top_momentum, args.cap)

    out = {
        "date": args.date,
        "time_point": args.time,
        "watch_sectors": watch,
        "sector_rank": sector_rank,
        "sector_net": sector_net,
        "plate_ranking": plate_ranking,
        "index_amount": index_amount,
        "sector_quote": {},
        "sector_leader": {},
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 摘要
    print(f"[{args.time}] 装配完成 -> {args.out}")
    print(f"  热点板块({len(watch)}): {watch}")
    print(f"  精确净流入板块({len(sector_net)}): " + ", ".join(
        f"{k}{v:+.1f}亿" for k, v in sector_net.items()))
    amt = sum(v for v in index_amount.values() if isinstance(v, (int, float))) / 1e8
    print(f"  三大指数成交额≈{amt:.0f}亿")


if __name__ == "__main__":
    main()
