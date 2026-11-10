import json,urllib.request,urllib.parse,time
from datetime import timedelta
from pathlib import Path
from update_data import calc_score,now_tw
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/"data"
def main():
 r=json.loads((DATA/"weekly_report.json").read_text(encoding="utf-8")); p=r.get("report",{})
 cs=list(p.get("watchlist",[]))
 for ind in p.get("industries",[]): cs.extend(ind.get("taiwan_candidates",[]))
 unique={}
 for x in cs:
  code=str(x.get("ticker") or x.get("code") or "").strip()
  if code.isdigit() and 4<=len(code)<=6: unique[code]=x
 now=now_tw(); start=(now-timedelta(days=240)).strftime("%Y-%m-%d"); end=now.strftime("%Y-%m-%d"); rows=[]
 for code,x in unique.items():
  try:
   q=urllib.parse.urlencode({"dataset":"TaiwanStockPrice","data_id":code,"start_date":start,"end_date":end})
   req=urllib.request.Request("https://api.finmindtrade.com/api/v4/data?"+q,headers={"User-Agent":"Mozilla/5.0"})
   with urllib.request.urlopen(req,timeout=30) as f: data=json.loads(f.read().decode("utf-8-sig")).get("data",[])
   h=[]
   for z in data:
    try:
     b={"date":z["date"],"open":float(z["open"]),"high":float(z["max"]),"low":float(z["min"]),"close":float(z["close"]),"volume":float(z.get("Trading_Volume") or 0)}
     if min(b[k] for k in ("open","high","low","close"))>0:h.append(b)
    except (KeyError,TypeError,ValueError):pass
   h.sort(key=lambda z:z["date"]); h=h[-130:]
   if len(h)<30: raise ValueError("有效歷史日 K 不足 30 筆："+str(len(h)))
   qrow={"code":code,"name":x.get("company") or x.get("name") or "","close":h[-1]["close"],"change_pct":(h[-1]["close"]/h[-2]["close"]-1)*100}
   m=calc_score(qrow,h,[],code)
   rows.append({"code":code,"name":qrow["name"],"industry":x.get("industry") or "週報候選","status":"ready","data_date":h[-1]["date"],"history_count":len(h),"close":qrow["close"],"change_pct":round(qrow["change_pct"],2),**m})
  except Exception as e: rows.append({"code":code,"name":x.get("company") or x.get("name") or "","status":"insufficient","reason":str(e)})
  time.sleep(.15)
 out={"updated_at":now.strftime("%Y-%m-%d %H:%M Taipei"),"source":"FinMind TaiwanStockPrice","candidate_count":len(rows),"ready_count":sum(x["status"]=="ready" for x in rows),"rows":rows}
 (DATA/"weekly_technical.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
 print("Weekly technical cache",out["ready_count"],"/",len(rows))
if __name__=="__main__":main()
