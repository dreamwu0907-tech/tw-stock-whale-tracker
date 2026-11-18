#!/usr/bin/env python3
"""Build weekly TDCC large-holder deltas joined to the existing daily market model.

TDCC source: https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5
The script stores one immutable snapshot per published date and publishes a compact
current comparison. It does not identify beneficial owners or individual institutions.
"""
import csv, io, json, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HISTORY = DATA / "tdcc_history"
SOURCE_URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
TZ = timezone(timedelta(hours=8))

def fetch_csv():
    req = Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; TWStockWhaleTracker/1.0)"})
    with urlopen(req, timeout=45) as response:
        raw = response.read()
    for encoding in ("utf-8-sig", "cp950", "big5"):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(encoding))))
        except UnicodeDecodeError:
            continue
    raise RuntimeError("無法解碼 TDCC CSV")

def keyval(row, candidates):
    for key, value in row.items():
        k = str(key or "").replace(" ", "").replace("\ufeff", "")
        if any(c in k for c in candidates):
            return value
    return None

def number(value):
    s = str(value or "").replace(",", "").replace("%", "").strip()
    try: return float(s)
    except (ValueError, TypeError): return None

def tier_lower(label):
    s = str(label or "").replace(",", "").replace("股", "").replace(" ", "")
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None

def normalize(rows):
    stocks = {}
    dates = []
    for row in rows:
        code = str(keyval(row, ["證券代號", "股票代號"]) or "").strip()
        if not re.fullmatch(r"\d{4,6}", code): continue
        date = str(keyval(row, ["資料日期", "日期"]) or "").strip()
        if date: dates.append(date)
        tier = str(keyval(row, ["持股分級", "持股級距"]) or "").strip()
        pct = number(keyval(row, ["占集保庫存數比例", "佔集保庫存數比例", "比例"]))
        holders = number(keyval(row, ["人數", "股東人數"]))
        shares = number(keyval(row, ["股數", "持有股數"]))
        if pct is None: continue
        item = stocks.setdefault(code, {"code": code, "name": "", "holder_400": 0.0,
                                        "holder_1000": 0.0, "retail_under_10": 0.0,
                                        "tiers_seen": 0})
        item["tiers_seen"] += 1
        low = tier_lower(tier)
        if low is not None and low >= 400001:
            item["holder_400"] += pct
        if low is not None and low >= 1000001:
            item["holder_1000"] += pct
        if low is not None and low < 10000:
            item["retail_under_10"] += pct
    if not stocks: raise RuntimeError("TDCC CSV 未解析到有效股票級距資料，停止發布")
    return (max(dates) if dates else None), stocks

def load_previous(current_date):
    files = sorted(HISTORY.glob("*.json"), reverse=True)
    for path in files:
        if path.stem >= str(current_date): continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            return obj.get("stocks", {}), obj.get("tdcc_date")
        except Exception:
            continue
    return {}, None

def score_row(market, now, old):
    h400 = now["holder_400"]
    h1000 = now["holder_1000"]
    d400 = h400 - old["holder_400"] if old else None
    d1000 = h1000 - old["holder_1000"] if old else None
    f5, t5 = market.get("foreign_5d"), market.get("trust_5d")
    inst_available = f5 is not None and t5 is not None
    inst_positive = bool(inst_available and (f5 > 0 or t5 > 0))
    both_positive = bool(inst_available and f5 > 0 and t5 > 0)
    holder_score = (20 if d1000 is not None and d1000 > 0 else 0) + (10 if d400 is not None and d400 > 0 else 0)
    institutional_score = 20 if both_positive else 10 if inst_positive else 0
    dmi = bool(market.get("dmi_near_cross") or market.get("dmi_early_warning"))
    dmi_confirm = bool(market.get("dmi_cross_valid"))
    dmi_score = 20 if dmi else 15 if dmi_confirm else 0
    r5, r20, dev = market.get("return_5d_pct"), market.get("return_20d_pct"), market.get("ma20_deviation_pct")
    price_score = 0
    if r5 is not None and r5 <= 5: price_score += 10
    if r20 is not None and r20 <= 10: price_score += 5
    if dev is not None and -3 <= dev <= 8: price_score += 5
    vr = market.get("volume_ratio")
    volume_score = 10 if vr is not None and 1.0 <= vr <= 1.8 else 5 if vr is not None and 0.8 <= vr < 1.0 else 0
    components_known = sum(x is not None for x in (d400, d1000, f5, t5, market.get("plus_di"), r5, r20, vr))
    score = holder_score + institutional_score + dmi_score + price_score + volume_score
    early = bool((d400 is not None and d400 > 0) and (d1000 is not None and d1000 > 0)
                 and inst_positive and r5 is not None and r5 <= 5)
    labels = []
    if d400 is not None: labels.append("大額持股增加" if d400 > 0 else "大額持股減少" if d400 < 0 else "大額持股持平")
    else: labels.append("集保比較樣本累積中")
    if both_positive: labels.append("外資與投信同步買超")
    elif inst_positive: labels.append("單一法人近5日買超")
    else: labels.append("法人未同步買超或資料不足")
    if dmi: labels.append("DMI提前收斂")
    elif dmi_confirm: labels.append("DMI交叉確認")
    if r5 is not None and r5 <= 5: labels.append("股價尚未急漲")
    return {
        "code": market["code"], "name": market.get("name", ""),
        "holder_400_pct": round(h400, 3), "holder_1000_pct": round(h1000, 3),
        "retail_under_10_pct": round(now["retail_under_10"], 3),
        "holder_change": round(d400, 3) if d400 is not None else None,
        "holder_1000_change": round(d1000, 3) if d1000 is not None else None,
        "foreign_5d": f5, "trust_5d": t5,
        "institutional_score": institutional_score, "dmi_score": dmi_score,
        "price_score": price_score, "volume_score": volume_score,
        "holder_score": holder_score, "score": score,
        "return_5d_pct": r5, "return_20d_pct": r20,
        "volume_ratio": vr, "plus_di": market.get("plus_di"),
        "minus_di": market.get("minus_di"), "adx": market.get("adx"),
        "dmi_label": market.get("dmi_signal_label", "資料不足"),
        "early_candidate": early, "data_complete": components_known >= 7,
        "signal": "；".join(labels)
    }

def main():
    DATA.mkdir(exist_ok=True); HISTORY.mkdir(exist_ok=True)
    raw = fetch_csv()
    tdcc_date, stocks = normalize(raw)
    if not tdcc_date: raise RuntimeError("TDCC CSV 缺少資料日期，停止發布")
    previous, previous_date = load_previous(tdcc_date)
    snapshot = {"tdcc_date": tdcc_date, "source": SOURCE_URL, "downloaded_at":
                datetime.now(TZ).strftime("%Y-%m-%d %H:%M Taipei"), "stocks": stocks}
    snapshot_path = HISTORY / (re.sub(r"[^0-9]", "", tdcc_date) + ".json")
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    ranking = json.loads((DATA / "ranking.json").read_text(encoding="utf-8"))
    market_rows = ranking.get("rows", [])
    market = {str(x["code"]): x for x in market_rows}
    rows = []
    for code, current in stocks.items():
        if code in market:
            rows.append(score_row(market[code], current, previous.get(code)))
    rows.sort(key=lambda x: (x["early_candidate"], x["score"], x["holder_change"] or -999,
                             x["institutional_score"]), reverse=True)
    matched = len(rows)
    payload = {
        "version": "whale-flow-v1.0", "tdcc_date": tdcc_date,
        "previous_tdcc_date": previous_date, "market_date": ranking.get("data_date"),
        "updated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M Taipei"),
        "source": SOURCE_URL, "total_tdcc_stocks": len(stocks),
        "market_universe": ranking.get("market_scope", "現有排行資料範圍"),
        "matched_stocks": matched,
        "coverage_pct": round(matched / len(stocks) * 100, 1) if stocks else 0,
        "note": "目前與既有每日排行交集；既有排行範圍為 TWSE 上市股票，TPEx 上櫃股票尚未完整接入，因此不能視為上市櫃全市場掃描。集保比較從本次快照起逐週累積，首次沒有前期比較值。",
        "rows": rows
    }
    (DATA / "whale_flow.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TDCC date={tdcc_date}, source stocks={len(stocks)}, matched={matched}, prior={previous_date}, candidates={sum(x['early_candidate'] for x in rows)}")

if __name__ == "__main__":
    main()
