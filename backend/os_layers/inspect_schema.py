import sys, openpyxl

def dump(path, label, max_rows=3, max_cols=60):
    print("="*80)
    print(label, "->", path)
    print("="*80)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        print(f"\n### SHEET: {ws.title!r}  rows={ws.max_row} cols={ws.max_column}")
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        # find header row: first row that has multiple non-empty strings
        header = rows[0]
        print("HEADER:", [str(c)[:18] if c is not None else "" for c in header[:max_cols]])
        for r in rows[1:max_rows+1]:
            print("ROW1 :", [str(c)[:12] if c is not None else "" for c in r[:max_cols]])
    wb.close()

if __name__ == "__main__":
    dump(r"D:/Downloads/全市场动量观察表.xlsx", "MOMENTUM")
    dump(r"D:/Downloads/市场数据终端.xlsx", "CRYPTO_TERMINAL", max_rows=2, max_cols=170)
