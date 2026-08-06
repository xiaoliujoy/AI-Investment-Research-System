"""一句话交易计划解析器。

输入示例:
    多 AU2508 760 745
    空 600519 38.5 36.2
    long XAUUSD 2350 2330
    多 黄金 760 745 亏200     # 亏200 = 风险金额(元)

输出 dict:
    direction     LONG / SHORT / None
    symbol        品种代码(原样)
    market        MT5 / FUTURES / ASTOCK / OTHER
    entry         入场价(float) 或 None
    stop          止损价(float) 或 None
    amount        风险金额(float) 或 None
    invalid       自动推导的失效条件(跌破/突破 X 即失效)
    planned_exit  退出计划文本(入场 X 止损 Y)
    risk          风险金额文本
    reason        留空(一句话不含逻辑)

落库映射见 parse_plan_cli.py。
"""
import re

DIR_MAP = {
    "多单": "LONG", "做多": "LONG", "多": "LONG", "买": "LONG",
    "long": "LONG", "buy": "LONG", "l": "LONG",
    "空单": "SHORT", "做空": "SHORT", "空": "SHORT", "卖": "SHORT",
    "short": "SHORT", "sell": "SHORT", "s": "SHORT",
}

# 期货品种常见代码前缀（大写）
FUTURES_PREFIX = (
    "AU", "AG", "CU", "SI", "FG", "PK", "JM", "RB", "HC", "I", "J", "TA", "MA",
    "ZN", "PB", "NI", "SN", "AL", "RU", "PP", "L", "V", "C", "M", "Y", "A", "CF",
    "SR", "OI", "RM", "P", "JD", "CS", "WH", "RI", "RR", "AP", "CJ", "LU", "SC",
    "FU", "BU", "PG", "EB", "EG", "SA", "UR", "SP", "PS",
)
MT5_PREFIX = (
    "XAU", "XAG", "XPT", "XPD", "BTCUSD", "EURUSD", "GBPUSD",
    "USDJPY", "AUDUSD", "USDCAD",
)


def infer_market(symbol: str) -> str:
    s = (symbol or "").upper().strip()
    for p in MT5_PREFIX:
        if s.startswith(p):
            return "MT5"
    for p in FUTURES_PREFIX:
        if s.startswith(p):
            return "FUTURES"
    if re.match(r"^\d{6}$", s):
        return "ASTOCK"
    return "OTHER"


def parse_plan(text: str) -> dict:
    t = (text or "").strip()
    result = {
        "direction": None, "symbol": None, "market": "OTHER",
        "entry": None, "stop": None, "amount": None,
        "invalid": "", "planned_exit": "", "risk": "", "reason": "",
    }
    if not t:
        return result

    # 1) 方向（首个匹配的方向词）
    for k, v in DIR_MAP.items():
        if k in t:
            result["direction"] = v
            break

    # 2) 品种：先识别，供后续从文本剔除其数字（避免 AU2508/600519 被当价格）
    sym_text = t
    for k in DIR_MAP:
        sym_text = sym_text.replace(k, " ")
    tokens = [x for x in re.split(r"[\s,，、]+", sym_text) if x]
    for tok in tokens:
        if re.search(r"[A-Za-z]", tok) or re.match(r"^\d{6}$", tok):
            result["symbol"] = tok
            break
    if not result["symbol"] and tokens:
        result["symbol"] = tokens[0]
    if result["symbol"]:
        result["market"] = infer_market(result["symbol"])

    # 3) 剔除品种代码后取金额与价格数字
    text_prices = t.replace(result["symbol"], " ") if result["symbol"] else t
    m_amt = re.search(r"(?:亏|损|risk|金额|元)\s*(\d+(?:\.\d+)?)", text_prices, re.I)
    if m_amt:
        result["amount"] = float(m_amt.group(1))
    nums = re.findall(r"-?\d+(?:\.\d+)?", text_prices)
    price_nums = [n for n in nums if not (m_amt and n == m_amt.group(1))]

    # 4) 入场 / 止损（前两个价格数字）
    if len(price_nums) >= 1:
        result["entry"] = float(price_nums[0])
    if len(price_nums) >= 2:
        result["stop"] = float(price_nums[1])

    # 7) 推导失效条件 + 退出计划
    parts = []
    if result["entry"] is not None:
        parts.append(f"入场 {result['entry']}")
    if result["stop"] is not None:
        parts.append(f"止损 {result['stop']}")
    result["planned_exit"] = " ".join(parts)
    if result["stop"] is not None:
        if result["direction"] == "LONG":
            result["invalid"] = f"跌破 {result['stop']} 即失效"
        elif result["direction"] == "SHORT":
            result["invalid"] = f"突破 {result['stop']} 即失效"
    if result["amount"] is not None:
        result["risk"] = f"最大亏损 {result['amount']}"

    return result


if __name__ == "__main__":
    import sys, json
    sample = sys.argv[1] if len(sys.argv) > 1 else "多 AU2508 760 745"
    print(json.dumps(parse_plan(sample), ensure_ascii=False, indent=2))
