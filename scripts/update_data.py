#!/usr/bin/env python3
"""Build a free, after-hours Taiwan listed-stock watchlist from public TWSE data.
This is a transparent proxy score, not a direct measurement of individual large holders.
"""
import json, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TWStockWatchlist/0.1)"}
BASE = "https://www.twse.com.tw/rwd/zh"

def get_json(url, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=25) as r:
                raw = r.read().decode("utf-8-sig")
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj.get("stat") in ("很抱歉，沒有符合條件的資料!", "查詢日期大於今日"):
                raise RuntimeError(obj.get("stat"))
            return obj
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"API request failed: {url} ({last})")

def num(v):
    if v is None: return None
    s = str(v).strip().replace(",", "").replace("+", "")
    if s in ("", "--", "---", "X", "除權息", "除息", "除權"): return None
    try: return float(s)
    except ValueError: return None

def date_candidates():
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    # Try today and recent calendar days to survive weekends/holidays.
    return [(now - timedelta(days=i)).strftime("%Y%m%d") for i in range(0, 11)]

def fetch_quotes():
    # Official TWSE OpenAPI provides the latest listed-stock daily quote set.
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    data = get_json(url)
    rows = {}
    for x in data:
        code = str(x.get("Code", x.get("證券代號", ""))).strip()
        if not re.fullmatch(r"\d{4,6}", code): continue
        close = num(x.get("ClosingPrice", x.get("收盤價")))
        vol = num(x.get("TradeVolume", x.get("成交股數")))
        change = num(x.get("Change", x.get("漲跌價差")))
        name = x.get("Name", x.get("證券名稱", ""))
        if close is None or vol is None: continue
        rows[code] = {"code":code,"name":name,"close":close,"volume_shares":vol,"change":change}
    return rows

def fetch_institutional():
    # The T86 response is usually JSON with fields/titles + array rows.
    for ds in date_candidates():
        url = f"{BASE}/fund/T86?response=json&date={ds}&selectType=ALLBUT0999"
        try:
            obj = get_json(url)
            data = obj.get("data", [])
            fields = obj.get("fields", obj.get("titles", []))
            if not data or not fields: continue
            normalized = [str(x).replace(" ", "") for x in fields]
            def idx(*parts):
                for i, f in enumerate(normalized):
                    if all(p in f for p in parts): return i
                return None
            code_i = idx("證券代號")
            foreign_i = idx("外陸資買賣超股數")
            trust_i = idx("投信買賣超股數")
            dealer_i = idx("自營商買賣超股數")
            if code_i is None:
                continue
            out = {}
            for row in data:
                if len(row) <= code_i: continue
                code = str(row[code_i]).strip()
                if not re.fullmatch(r"\d{4,6}", code): continue
                def get_i(i):
                    return num(row[i]) if i is not None and len(row)>i else None
                # T86 data quantities are shares. Convert to lots (1,000 shares).
                out[code] = {
                    "foreign": (get_i(foreign_i)/1000 if get_i(foreign_i) is not None else None),
                    "trust": (get_i(trust_i)/1000 if get_i(trust_i) is not None else None),
                    "dealer": (get_i(dealer_i)/1000 if get_i(dealer_i) is not None else None),
                    "data_date": ds
                }
            if out: return out, ds
        except Exception:
            continue
    return {}, None

def fetch_history(code, yyyymm):
    url = f"{BASE}/afterTrading/STOCK_DAY?response=json&date={yyyymm}01&stockNo={code}"
    try:
        obj = get_json(url)
        return obj.get("data", [])
    except Exception:
        return []

def build():
    quotes = fetch_quotes()
    inst, inst_date = fetch_institutional()
    # Historical daily volume/price sample is pulled per stock only for a bounded set:
    # use up to the 250 most liquid stocks to limit requests; others get neutral volume ratio.
    liquid = sorted(quotes.values(), key=lambda x: x["volume_shares"], reverse=True)[:250]
    hist = {}
    current_month = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y%m")
    previous_month = (datetime.strptime(current_month, "%Y%m") - timedelta(days=1)).strftime("%Y%m")
    for j, q in enumerate(liquid):
        data = fetch_history(q["code"], current_month)
        if len(data) < 8:
            data = fetch_history(q["code"], previous_month) + data
        volumes = []
        for row in data:
            # TWSE STOCK_DAY fields: date, volume, value, transactions, open, high, low, close, change, ...
            if len(row) > 1:
                v = num(row[1])
                if v is not None: volumes.append(v)
        if volumes:
            hist[q["code"]] = sum(volumes[-20:]) / min(20, len(volumes))
        if j and j % 25 == 0: time.sleep(0.15)

    rows = []
    for code, q in quotes.items():
        iv = inst.get(code, {})
        avg_vol = hist.get(code)
        # TradeVolume from STOCK_DAY_ALL is shares, historic volume is also shares.
        vr = (q["volume_shares"] / avg_vol) if avg_vol and avg_vol > 0 else None
        foreign, trust, dealer = iv.get("foreign"), iv.get("trust"), iv.get("dealer")
        chg_pct = None
        if q["close"] and q["change"] is not None:
            prev = q["close"] - q["change"]
            if prev > 0: chg_pct = q["change"] / prev * 100
        # Transparent heuristic score: daily institutional buying, volume expansion,
        # price strength without chasing extreme daily gains.
        score = 35
        if foreign is not None: score += max(-18, min(18, foreign / 300 * 6))
        if trust is not None: score += max(-12, min(12, trust / 100 * 4))
        if dealer is not None: score += max(-5, min(5, dealer / 200 * 2))
        if vr is not None: score += max(-8, min(10, (vr - 1) * 6))
        if chg_pct is not None:
            if 0 <= chg_pct <= 4: score += 8
            elif chg_pct < -4: score -= 8
            elif chg_pct > 7: score -= 5
        score = round(max(0, min(100, score)))
        signals = []
        if foreign is not None and foreign > 0: signals.append("外資買超")
        if trust is not None and trust > 0: signals.append("投信買超")
        if vr is not None and vr >= 1.5: signals.append("量能放大")
        if chg_pct is not None and 0 <= chg_pct <= 4: signals.append("漲幅未過熱")
        if not signals: signals.append("持續觀察")
        rows.append({
            "code":code,"name":q["name"],"close":q["close"],
            "change_pct":round(chg_pct,2) if chg_pct is not None else None,
            "volume_ratio":round(vr,2) if vr is not None else None,
            "foreign":round(foreign,1) if foreign is not None else None,
            "trust":round(trust,1) if trust is not None else None,
            "dealer":round(dealer,1) if dealer is not None else None,
            "score":score,"signal":"、".join(signals)
        })
    rows.sort(key=lambda x: (x["score"], x["foreign"] or 0, x["volume_ratio"] or 0), reverse=True)
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    out = {
        "data_date": inst_date or now.strftime("%Y%m%d"),
        "updated_at": now.strftime("%Y-%m-%d %H:%M Taipei"),
        "market_scope":"TWSE listed stocks only",
        "note":"本版為上市股票 MVP；未接入上櫃市場、集保週資料與券商分點。資料日期以法人資料為準。",
        "rows": rows
    }
    (DATA_DIR / "ranking.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} rows; quote rows={len(quotes)}; institutional date={inst_date}")

if __name__ == "__main__":
    build()
