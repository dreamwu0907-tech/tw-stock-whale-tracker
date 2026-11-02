#!/usr/bin/env python3
"""Weekly global-industry research pipeline: RSS collection + OpenAI Responses API."""
import json, os, re, sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
RAW = DATA / "weekly_raw.json"
REPORT = DATA / "weekly_report.json"
TZ = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (compatible; GlobalIndustryWeeklyResearch/1.0)"
QUERIES = [
    "global AI data center semiconductor investment",
    "global semiconductor foundry advanced packaging HBM demand",
    "global robotics automation humanoid industrial robots",
    "global defense aerospace military procurement",
    "global financial markets central banks interest rates capital flows",
    "global energy electricity grid HVDC storage nuclear power",
    "global healthcare biotechnology pharmaceutical industry",
    "global commodities supply chain manufacturing investment",
    "Taiwan listed companies AI server power cooling optical communication supply chain",
    "Taiwan listed companies robotics defense aerospace energy grid supply chain",
]
def now_tw():
    return datetime.now(timezone.utc).astimezone(TZ)
def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()
def rss_items(xml_bytes, query):
    root = ET.fromstring(xml_bytes)
    found = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        desc = re.sub(r"\s+", " ", desc).strip()
        if title and link:
            found.append({"title": title[:400], "url": link, "published": pub,
                          "summary": desc[:1200], "query": query})
    return found
def collect():
    end = now_tw()
    start = end - timedelta(days=7)
    all_items, errors = [], []
    for q in QUERIES:
        params = urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        url = "https://news.google.com/rss/search?" + params
        try:
            all_items.extend(rss_items(fetch(url), q))
        except Exception as e:
            errors.append({"query": q, "error": str(e)[:300]})
        time.sleep(0.25)
    # Deduplicate by canonical URL and title; keep items with date in the last 7 days when parsable.
    unique, seen = [], set()
    for item in all_items:
        key = item["url"].split("&")[0]
        if key in seen: continue
        seen.add(key)
        unique.append(item)
    unique = unique[:180]
    payload = {
        "status": "collected" if unique else "collection_empty",
        "collected_at": end.isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "source_method": "Google News RSS search feeds; links lead to original publishers",
        "queries": QUERIES,
        "article_count": len(unique),
        "articles": unique,
        "collection_errors": errors,
        "limitations": ["RSS headlines/snippets are not full-text article crawling.",
                        "News coverage is not a complete census of all global public information.",
                        "Market-flow claims require independent market-data sources."]
    }
    RAW.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Collected {len(unique)} unique RSS items; {len(errors)} feed errors.")
def response_text(obj):
    chunks = []
    for out in obj.get("output", []):
        for c in out.get("content", []):
            if c.get("type") == "output_text" and c.get("text"):
                chunks.append(c["text"])
    return "\n".join(chunks).strip()
def analyze():
    if not RAW.exists():
        raise SystemExit("weekly_raw.json missing; run collect first")
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        REPORT.write_text(json.dumps({
            "status": "needs_api_key", "generated_at": now_tw().isoformat(),
            "period_start": raw.get("period_start"), "period_end": raw.get("period_end"),
            "article_count": raw.get("article_count", 0),
            "message": "請在 GitHub Repository Secrets 設定 OPENAI_API_KEY，才能執行 GPT 週報分析。",
            "articles": raw.get("articles", [])[:60]
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print("OPENAI_API_KEY missing; saved a clear setup status.")
        return
    articles = raw.get("articles", [])[:120]
    prompt = {
      "task": "Produce a careful Traditional Chinese weekly global industry and Taiwan stock research report.",
      "period": {"start": raw.get("period_start"), "end": raw.get("period_end")},
      "rules": [
        "Treat article titles/snippets as evidence only; do not claim you read full articles.",
        "Do not invent financial flows, company orders, customers, revenue, valuation, stock codes, or facts.",
        "Separate sourced facts from analysis/inference. Provide source URLs for every material claim.",
        "Rank industries by evidence and likely impact over 1-3 months and 1-3 years.",
        "Cover AI/semiconductors/data centers, finance/rates/currencies/capital flows, robotics, defense/aerospace, energy/grid/storage/nuclear, healthcare/biotech, commodities and emerging themes.",
        "For Taiwan listed-stock candidates, include only when an article or verifiable source in the input explicitly supports a company's product/supply-chain relevance. If evidence is insufficient, list the industry but leave stock candidates empty.",
        "For each candidate include ticker, company, supply-chain role, evidence URLs, catalyst, risk, whether price may already reflect the theme (unknown if no price data). Never invent an entry price or target price.",
        "State that RSS collection is not exhaustive and that capital flow conclusions are provisional unless numeric market data is present.",
        "Output valid JSON only, Traditional Chinese, matching this schema: {executive_summary:string, global_macro:string, industries:[{name:string, trend_stage:string, direction:string, short_term:string, long_term:string, evidence:[{claim:string,url:string}], risks:[string], taiwan_candidates:[{ticker:string,company:string,role:string,why_benefit:string,evidence_urls:[string],risks:[string],price_reflection:string}]}], capital_flow:[{market_or_asset:string,observation:string,evidence_urls:[string],confidence:string}], watchlist:[{ticker:string,company:string,industry:string,thesis:string,evidence_urls:[string],risk:string}], next_week_events:[{event:string,when:string,why_it_matters:string,source_url:string}], methodology_notes:[string]}"
      ],
      "articles": articles
    }
    body = json.dumps({"model": os.environ.get("OPENAI_MODEL", "gpt-6-luna"),
                       "input": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
                       "text": {"format": {"type": "json_object"}}}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=body,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as res:
            response = json.loads(res.read().decode("utf-8"))
        text = response_text(response)
        report = json.loads(text)
    except Exception as e:
        raise SystemExit(f"OpenAI Responses API analysis failed: {e}")
    output = {
        "status": "published", "generated_at": now_tw().isoformat(),
        "period_start": raw.get("period_start"), "period_end": raw.get("period_end"),
        "article_count": raw.get("article_count", 0),
        "model": os.environ.get("OPENAI_MODEL", "gpt-6-luna"),
        "source_method": raw.get("source_method"),
        "collection_errors": raw.get("collection_errors", []),
        "report": report,
        "source_articles": articles
    }
    REPORT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Weekly report generated with {len(articles)} source items.")
if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("collect", "analyze"):
        raise SystemExit("Usage: weekly_research.py collect|analyze")
    collect() if sys.argv[1] == "collect" else analyze()
