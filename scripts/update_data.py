#!/usr/bin/env python3
"""Build a Taiwan listed-stock watchlist using institutional flows, DMI and price position."""
import json, re, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
TZ = timezone(timedelta(hours=8))
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TWStockWatchlist/0.2)"}
BASE = "https://www.twse.com.tw/rwd/zh"

def now_tw():
    return datetime.now(timezone.utc).astimezone(TZ)

def get_json(url, tries=2):
    last = None
    for attempt in range(tries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=20) as r:
                obj = json.loads(r.read().decode("utf-8-sig"))
            if isinstance(obj, dict) and obj.get("stat") in ("很抱歉，沒有符合條件的資料!", "查詢日期大於今日"):
                raise RuntimeError(obj.get("stat"))
            return obj
        except Exception as e:
            last = e
            if attempt + 1 < tries:
                time.sleep(1 + attempt)
    raise RuntimeError(f"API request failed: {url} ({last})")

def num(v):
    if v is None: return None
    s = str(v).strip().replace(",", "").replace("+", "")
    if s in ("", "--", "---", "X", "除權息", "除息", "除權", "N/A"): return None
    try: return float(s)
    except (ValueError, TypeError): return None

def date_candidates(days=20):
    now = now_tw()
    return [(now - timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]

def fetch_quotes():
    data = get_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    out = {}
    for x in data:
        code = str(x.get("Code", x.get("證券代號", ""))).strip()
        if not re.fullmatch(r"\d{4,6}", code): continue
        close = num(x.get("ClosingPrice", x.get("收盤價")))
        vol = num(x.get("TradeVolume", x.get("成交股數")))
        change = num(x.get("Change", x.get("漲跌價差")))
        if close is None or vol is None: continue
        out[code] = {"code": code, "name": x.get("Name", x.get("證券名稱", "")),
                     "close": close, "volume_shares": vol, "change": change}
    return out

def parse_t86(ds):
    url = f"{BASE}/fund/T86?response=json&date={ds}&selectType=ALLBUT0999"
    obj = get_json(url)
    data = obj.get("data", [])
    fields = obj.get("fields", obj.get("titles", []))
    if not data or not fields: return {}
    normalized = [str(x).replace(" ", "") for x in fields]
    def idx(*parts):
        for i, f in enumerate(normalized):
            if all(p in f for p in parts): return i
        return None
    code_i = idx("證券代號")
    foreign_i = idx("外陸資買賣超股數")
    trust_i = idx("投信買賣超股數")
    dealer_i = idx("自營商買賣超股數")
    if code_i is None: return {}
    out = {}
    for row in data:
        if len(row) <= code_i: continue
        code = str(row[code_i]).strip()
        if not re.fullmatch(r"\d{4,6}", code): continue
        def val(i):
            return num(row[i]) if i is not None and len(row) > i else None
        f, t, d = val(foreign_i), val(trust_i), val(dealer_i)
        out[code] = {
            "foreign": f / 1000 if f is not None else None,
            "trust": t / 1000 if t is not None else None,
            "dealer": d / 1000 if d is not None else None
        }
    return out

def fetch_institutional_history():
    # Collect the latest five available trading sessions, newest first.
    sessions = []
    for ds in date_candidates(20):
        try:
            data = parse_t86(ds)
            if data:
                sessions.append((ds, data))
                if len(sessions) >= 5: break
        except Exception:
            continue
    return sessions

def fetch_history(code, yyyymm):
    url = f"{BASE}/afterTrading/STOCK_DAY?response=json&date={yyyymm}01&stockNo={code}"
    try:
        obj = get_json(url)
        fields = obj.get("fields", obj.get("titles", []))
        data = obj.get("data", [])
        rows = []
        for row in data:
            if len(row) < 8: continue
            # TWSE STOCK_DAY: date, volume, value, transactions, open, high, low, close
            vals = [num(row[i]) for i in (1, 4, 5, 6, 7)]
            if any(v is None for v in vals): continue
            rows.append({"volume": vals[0], "open": vals[1], "high": vals[2],
                         "low": vals[3], "close": vals[4]})
        return rows
    except Exception:
        return []

def dmi_series(history, period=14):
    # Wilder-smoothed DMI/ADX. Requires enough daily OHLC observations.
    if len(history) < period * 2 + 2: return None
    tr, plus_dm, minus_dm = [], [], []
    for i in range(1, len(history)):
        cur, prev = history[i], history[i-1]
        up = cur["high"] - prev["high"]
        down = prev["low"] - cur["low"]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(cur["high"] - cur["low"],
                      abs(cur["high"] - prev["close"]),
                      abs(cur["low"] - prev["close"])))
    if len(tr) < period: return None
    sm_tr = sum(tr[:period])
    sm_plus = sum(plus_dm[:period])
    sm_minus = sum(minus_dm[:period])
    dx_values, di_values = [], []
    for i in range(period, len(tr)):
        if i > period:
            sm_tr = sm_tr - sm_tr / period + tr[i]
            sm_plus = sm_plus - sm_plus / period + plus_dm[i]
            sm_minus = sm_minus - sm_minus / period + minus_dm[i]
        if sm_tr <= 0:
            pdi = mdi = 0.0
        else:
            pdi, mdi = 100 * sm_plus / sm_tr, 100 * sm_minus / sm_tr
        den = pdi + mdi
        dx = 100 * abs(pdi - mdi) / den if den > 0 else 0.0
        di_values.append((pdi, mdi))
        dx_values.append(dx)
    if len(dx_values) < period + 2: return None
    adx_values = [None] * (period - 1)
    adx = sum(dx_values[:period]) / period
    adx_values.append(adx)
    for dx in dx_values[period:]:
        adx = ((adx * (period - 1)) + dx) / period
        adx_values.append(adx)
    # Align DI and ADX arrays; retain their common trailing values.
    n = min(len(di_values), len(adx_values))
    return [(di_values[-n+i][0], di_values[-n+i][1], adx_values[-n+i]) for i in range(n)
            if adx_values[-n+i] is not None]

def streak_and_buy_days(sessions, code, key):
    streak = 0
    for _, day in sessions:
        v = day.get(code, {}).get(key)
        if v is not None and v > 0: streak += 1
        else: break
    days = sum(1 for _, day in sessions if (day.get(code, {}).get(key) is not None and day[code][key] > 0))
    total = sum(day.get(code, {}).get(key) or 0 for _, day in sessions)
    return streak, days, total

def streak_points(streak, maximum, bands):
    if streak <= 0: return 0
    for days, points in bands:
        if streak <= days: return points
    return maximum

def score_institutional(sessions, code, key, max_points, volume5):
    streak, buy_days, total = streak_and_buy_days(sessions, code, key)
    if key == "trust":
        streak_score = streak_points(streak, 10, [(2, 4), (4, 7)])  # max 10
        ratio_score = 0
        if volume5 and total > 0:
            ratio = total * 1000 / volume5
            ratio_score = 6 if ratio >= 0.005 else 4 if ratio >= 0.002 else 2
        continuity = 4 if buy_days == 5 else 3 if buy_days == 4 else 2 if buy_days == 3 else 0
        return min(max_points, streak_score + ratio_score + continuity), streak, total
    streak_score = streak_points(streak, 7, [(2, 2), (4, 5)])
    ratio_score = 0
    if volume5 and total > 0:
        ratio = total * 1000 / volume5
        ratio_score = 5 if ratio >= 0.005 else 3 if ratio >= 0.002 else 1
    continuity = 3 if buy_days == 5 else 2 if buy_days >= 3 else 0
    return min(max_points, streak_score + ratio_score + continuity), streak, total

def calc_score(q, history, sessions, code):
    # Historical rows are chronological. Return metrics are only computed with enough sessions.
    closes = [x["close"] for x in history]
    volumes = [x["volume"] for x in history]
    five_ret = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else None
    twenty_ret = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else None
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    ma_dev = (closes[-1] / ma20 - 1) * 100 if ma20 else None
    dmis = dmi_series(history)
    pdi = mdi = adx = None
    cross_valid = di_declining = adx_declining = False
    if dmis and len(dmis) >= 3:
        pdi, mdi, adx = dmis[-1]
        # Cross on the latest session or either of the two prior sessions (3 sessions including cross day).
        for j in range(max(1, len(dmis)-3), len(dmis)):
            if dmis[j-1][0] <= dmis[j-1][1] and dmis[j][0] > dmis[j][1]:
                cross_valid = True
        di_declining = dmis[-3][1] > dmis[-2][1] > dmis[-1][1]
        adx_declining = dmis[-3][2] is not None and dmis[-2][2] is not None and dmis[-1][2] is not None and dmis[-3][2] > dmis[-2][2] > dmis[-1][2]

    volume5 = sum(volumes[-5:]) if len(volumes) >= 5 else None
    trust_score, trust_streak, trust5 = score_institutional(sessions, code, "trust", 20, volume5)
    foreign_score, foreign_streak, foreign5 = score_institutional(sessions, code, "foreign", 15, volume5)

    dmi_score = (15 if cross_valid else 0) + (10 if di_declining else 0) + (10 if adx_declining else 0)
    price_score = 0
    if five_ret is not None:
        price_score += 10 if five_ret <= 0 else 8 if five_ret <= 2 else 5 if five_ret <= 5 else 0
    if twenty_ret is not None:
        price_score += 6 if twenty_ret <= 0 else 5 if twenty_ret <= 5 else 3 if twenty_ret <= 10 else 0
    if ma_dev is not None:
        price_score += 4 if -3 <= ma_dev <= 3 else 3 if -5 <= ma_dev <= 5 else 1 if -8 <= ma_dev <= 8 else 0

    avg_turnover = None
    if len(history) >= 5:
        # Shares * NT$ price approximates traded value; history volume is in shares.
        avg_turnover = sum(history[-5+i]["volume"] * history[-5+i]["close"] for i in range(5)) / 5
    liquidity_score = 5 if avg_turnover is not None and avg_turnover >= 100_000_000 else 4 if avg_turnover is not None and avg_turnover >= 30_000_000 else 2 if avg_turnover is not None and avg_turnover >= 10_000_000 else 0
    daily_move = q.get("change_pct")
    move_score = 5 if daily_move is not None and abs(daily_move) <= 5 else 3 if daily_move is not None and abs(daily_move) <= 7 else 1 if daily_move is not None and abs(daily_move) < 9 else 0
    risk_score = liquidity_score + move_score
    score = min(100, trust_score + foreign_score + dmi_score + price_score + risk_score)

    foreign_vals = [day.get(code, {}).get("foreign") for _, day in sessions]
    trust_vals = [day.get(code, {}).get("trust") for _, day in sessions]
    f5_positive = foreign5 > 0
    t5_positive = trust5 > 0
    if f5_positive and t5_positive: inst_label = "雙法人同步買超"
    elif f5_positive and not t5_positive: inst_label = "外資主導"
    elif t5_positive and not f5_positive: inst_label = "投信主導"
    else: inst_label = "法人分歧／未同步"

    reasons = []
    if trust_streak: reasons.append(f"投信連買{trust_streak}日")
    if foreign_streak: reasons.append(f"外資連買{foreign_streak}日")
    if cross_valid: reasons.append("DMI黃金交叉有效")
    if di_declining: reasons.append("-DI連3日下降")
    if adx_declining: reasons.append("ADX連3日下降")
    if five_ret is not None and five_ret <= 5: reasons.append("5日漲幅未超5%")
    if not reasons: reasons.append("條件尚未完整")
    dmi_complete = dmis is not None and len(dmis) >= 3
    price_complete = five_ret is not None and twenty_ret is not None and ma_dev is not None
    strategy_qualified = bool(dmi_complete and cross_valid and di_declining and adx_declining and five_ret is not None and five_ret <= 5)
    tier = "優先觀察" if score >= 80 else "持續追蹤" if score >= 65 else "一般觀察"
    return {
        "score": int(round(score)), "trust_score": trust_score, "foreign_score": foreign_score,
        "dmi_score": dmi_score, "price_score": price_score, "risk_score": risk_score,
        "trust_streak": trust_streak, "foreign_streak": foreign_streak,
        "trust_5d": round(trust5, 1) if sessions else None,
        "foreign_5d": round(foreign5, 1) if sessions else None,
        "plus_di": round(pdi, 2) if pdi is not None else None,
        "minus_di": round(mdi, 2) if mdi is not None else None,
        "adx": round(adx, 2) if adx is not None else None,
        "dmi_cross_valid": cross_valid, "minus_di_declining": di_declining, "adx_declining": adx_declining,
        "return_5d_pct": round(five_ret, 2) if five_ret is not None else None,
        "return_20d_pct": round(twenty_ret, 2) if twenty_ret is not None else None,
        "ma20_deviation_pct": round(ma_dev, 2) if ma_dev is not None else None,
        "strategy_qualified": strategy_qualified, "tier": tier, "institutional_label": inst_label,
        "data_complete": bool(dmi_complete and price_complete and len(sessions) >= 5),
        "signal": "、".join(reasons)
    }

def build():
    quotes = fetch_quotes()
    sessions = fetch_institutional_history()
    # Keep API usage bounded: fetch two months of OHLC for the 250 most liquid stocks.
    liquid_codes = {q["code"] for q in sorted(quotes.values(), key=lambda x: x["volume_shares"], reverse=True)[:250]}
    now = now_tw()
    current_month = now.strftime("%Y%m")
    previous_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
    histories = {}
    for i, code in enumerate(liquid_codes):
        old = fetch_history(code, previous_month)
        current = fetch_history(code, current_month)
        history = old + current
        # Deduplicate adjacent months and require enough bars for DMI/20-day calculations.
        if len(history) >= 21:
            histories[code] = history[-60:]
        if i and i % 20 == 0:
            time.sleep(0.2)

    rows = []
    for code, q in quotes.items():
        history = histories.get(code, [])
        change_pct = None
        if q["close"] and q["change"] is not None:
            prev = q["close"] - q["change"]
            if prev > 0: change_pct = q["change"] / prev * 100
        q["change_pct"] = change_pct
        metrics = calc_score(q, history, sessions, code)
        # Do not silently substitute missing historical fields with zero; incomplete data is explicit.
        iv = sessions[0][1].get(code, {}) if sessions else {}
        vr = None
        if len(history) >= 5 and sum(x["volume"] for x in history[-20:]) > 0:
            avg = sum(x["volume"] for x in history[-20:]) / min(20, len(history))
            if avg > 0: vr = q["volume_shares"] / avg
        rows.append({
            "code": code, "name": q["name"], "close": q["close"],
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "volume_ratio": round(vr, 2) if vr is not None else None,
            "foreign": iv.get("foreign"), "trust": iv.get("trust"), "dealer": iv.get("dealer"),
            **metrics
        })
    rows.sort(key=lambda x: (x["strategy_qualified"], x["score"], x["foreign"] or 0), reverse=True)
    out = {
        "data_date": sessions[0][0] if sessions else now.strftime("%Y%m%d"),
        "updated_at": now.strftime("%Y-%m-%d %H:%M Taipei"),
        "market_scope": "TWSE listed stocks only",
        "score_version": "DMI+institutional v1.0",
        "score_weights": {"trust":20,"foreign":15,"dmi":35,"price":20,"risk":10},
        "history_coverage": f"{len(histories)} liquid stocks with sufficient OHLC history",
        "note": "80–100優先觀察、65–79持續追蹤、0–64一般觀察；策略合格另需DMI三條件成立且近5日漲幅≤5%。歷史技術資料目前限成交量前250檔；缺資料不視為零分以外的有效訊號，請查看 data_complete。",
        "rows": rows
    }
    (DATA_DIR / "ranking.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} rows; historical coverage={len(histories)}; institutional sessions={len(sessions)}")

if __name__ == "__main__":
    build()
