#!/usr/bin/env python3
"""Build one server-side OHLC + technical-indicator cache shared by stock analysis pages."""
import json, urllib.request, urllib.parse, time
from datetime import timedelta
from pathlib import Path
from update_data import calc_score, now_tw

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

def add_candidate(target, item, source):
    if not isinstance(item, dict):
        return
    code = str(item.get("ticker") or item.get("code") or "").strip()
    if not (code.isdigit() and 4 <= len(code) <= 6):
        return
    row = target.setdefault(code, {"code": code, "name": "", "sources": []})
    row["name"] = row["name"] or item.get("company") or item.get("name") or ""
    row["industry"] = row.get("industry") or item.get("industry") or ""
    row["thesis"] = row.get("thesis") or item.get("thesis") or item.get("why_benefit") or ""
    row["risk"] = row.get("risk") or item.get("risk") or "；".join(item.get("risks", []))
    if source not in row["sources"]:
        row["sources"].append(source)

def main():
    candidates = {}
    ranking_path = DATA / "ranking.json"
    if ranking_path.exists():
        try:
            ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
            for item in ranking.get("rows", []):
                add_candidate(candidates, item, "每日排行")
        except Exception as exc:
            print("Warning: ranking.json unavailable:", exc)

    report_path = DATA / "weekly_report.json"
    if report_path.exists():
        try:
            wrapper = json.loads(report_path.read_text(encoding="utf-8"))
            report = wrapper.get("report", wrapper)
            for item in report.get("watchlist", []):
                add_candidate(candidates, item, "週報觀察名單")
            for industry in report.get("industries", []):
                for item in industry.get("taiwan_candidates", []):
                    enriched = dict(item)
                    enriched.setdefault("industry", industry.get("name", ""))
                    add_candidate(candidates, enriched, "週報產業候選")
        except Exception as exc:
            print("Warning: weekly_report.json unavailable:", exc)

    now = now_tw()
    start = (now - timedelta(days=300)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    rows = []
    for code, meta in sorted(candidates.items()):
        try:
            params = urllib.parse.urlencode({
                "dataset": "TaiwanStockPrice", "data_id": code,
                "start_date": start, "end_date": end
            })
            req = urllib.request.Request(
                "https://api.finmindtrade.com/api/v4/data?" + params,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TWStockTechnicalCache/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8-sig"))
            if payload.get("status") not in (None, 200):
                raise RuntimeError(payload.get("msg") or "FinMind 回傳錯誤")
            history = []
            for item in payload.get("data", []):
                try:
                    candle = {
                        "date": item["date"],
                        "open": float(item["open"]),
                        "high": float(item["max"]),
                        "low": float(item["min"]),
                        "close": float(item["close"]),
                        "volume": float(item.get("Trading_Volume") or 0)
                    }
                    if min(candle[k] for k in ("open", "high", "low", "close")) > 0:
                        history.append(candle)
                except (KeyError, TypeError, ValueError):
                    continue
            history.sort(key=lambda x: x["date"])
            history = history[-180:]
            if len(history) < 30:
                raise ValueError("有效歷史日 K 不足 30 筆：" + str(len(history)))
            quote = {
                "code": code, "name": meta["name"],
                "close": history[-1]["close"],
                "change_pct": (history[-1]["close"] / history[-2]["close"] - 1) * 100
            }
            metrics = calc_score(quote, history, [], code)
            rows.append({
                **meta, "status": "ready", "source": "FinMind TaiwanStockPrice",
                "data_date": history[-1]["date"], "history_count": len(history),
                "close": quote["close"], "change_pct": round(quote["change_pct"], 2),
                "ohlc_history": history, **metrics
            })
        except Exception as exc:
            rows.append({**meta, "status": "insufficient", "reason": str(exc)})
        time.sleep(0.15)

    result = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M Taipei"),
        "source": "FinMind TaiwanStockPrice",
        "candidate_count": len(rows),
        "ready_count": sum(x["status"] == "ready" for x in rows),
        "rows": rows
    }
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    (DATA / "technical_cache.json").write_text(serialized, encoding="utf-8")
    # Keep the old filename as a compatibility alias while both pages migrate.
    (DATA / "weekly_technical.json").write_text(serialized, encoding="utf-8")
    print("Shared technical cache:", result["ready_count"], "/", len(rows),
          "ready; includes ranking and weekly candidates")

if __name__ == "__main__":
    main()
