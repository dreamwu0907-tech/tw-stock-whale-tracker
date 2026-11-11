/**
 * Cloudflare Worker: on-demand Taiwan stock daily OHLC history.
 * Deploy as a separate Worker named tw-stock-history-api.
 */
const ALLOWED_ORIGIN = "https://dreamwu0907-tech.github.io";
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "no-store",
    "Vary": "Origin"
  }
});
const num = v => {
  if (v === null || v === undefined) return NaN;
  const s = String(v).replace(/,/g, "").replace(/[＋+]/g, "").trim();
  if (!s || s === "--" || s === "X" || s === "除權息") return NaN;
  return Number(s);
};
const rocDate = s => {
  const m = String(s || "").trim().match(/^(\d{2,3})\/(\d{1,2})\/(\d{1,2})$/);
  if (m) return String(Number(m[1]) + 1911).padStart(4,"0")+"-"+m[2].padStart(2,"0")+"-"+m[3].padStart(2,"0");
  const d = String(s || "").replace(/\D/g,"");
  if (d.length === 7) return String(Number(d.slice(0,3))+1911)+"-"+d.slice(3,5)+"-"+d.slice(5,7);
  if (d.length === 8) return d.slice(0,4)+"-"+d.slice(4,6)+"-"+d.slice(6,8);
  return "";
};
const monthsBack = n => {
  const now = new Date();
  const out=[];
  for(let i=0;i<n;i++){
    const d=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth()-i,1));
    out.push(d.getUTCFullYear()+"-"+String(d.getUTCMonth()+1).padStart(2,"0")+"-01");
  }
  return out;
};
async function getJson(url, host) {
  const r=await fetch(url,{headers:{
    "User-Agent":"Mozilla/5.0 (compatible; TWStockHistory/1.0)",
    "Accept":"application/json, text/plain, */*",
    "Referer":host
  }});
  const text=await r.text();
  if(!r.ok) throw new Error("上游 HTTP "+r.status);
  try{return JSON.parse(text);}catch(_){throw new Error("官方行情回傳非 JSON（可能暫時被防護或限流）");}
}
async function twse(code, months) {
  const rows=[];
  for(const date of months){
    const compact=date.replace(/-/g,"");
    const url="https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?response=json&date="+compact+"&stockNo="+encodeURIComponent(code);
    const p=await getJson(url,"https://www.twse.com.tw/");
    if(p.stat==="OK" && Array.isArray(p.data)){
      for(const a of p.data){
        const row={date:rocDate(a[0]),volume:num(a[1]),open:num(a[3]),high:num(a[4]),low:num(a[5]),close:num(a[6])};
        if(row.date&&[row.open,row.high,row.low,row.close].every(Number.isFinite)) rows.push(row);
      }
    }
  }
  return rows;
}
async function tpex(code, months) {
  const rows=[];
  for(const date of months){
    const url="https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code="+encodeURIComponent(code)+"&date="+encodeURIComponent(date.replace(/-/g,"/"))+"&response=json";
    const p=await getJson(url,"https://www.tpex.org.tw/");
    const fields=p.fields||p.columns||[];
    const data=p.aaData||p.data||p.rows||[];
    const find=(patterns, fallback)=> {
      const i=fields.findIndex(x=>patterns.some(re=>re.test(String(x))));
      return i>=0?i:fallback;
    };
    const ix={date:find([/日期/],0),volume:find([/成交股數|成交數量|成交量/],1),open:find([/開盤價/],3),high:find([/最高價/],4),low:find([/最低價/],5),close:find([/收盤價/],6)};
    for(const a of data){
      if(Array.isArray(a)){
        const row={date:rocDate(a[ix.date]),volume:num(a[ix.volume]),open:num(a[ix.open]),high:num(a[ix.high]),low:num(a[ix.low]),close:num(a[ix.close])};
        if(row.date&&[row.open,row.high,row.low,row.close].every(Number.isFinite)) rows.push(row);
      }else if(a&&typeof a==="object"){
        const get=(re,keys)=>{const k=Object.keys(a).find(k=>re.test(k));return k?a[k]:keys.map(k=>a[k]).find(v=>v!==undefined);};
        const row={date:rocDate(get(/日期/,["date"])),volume:num(get(/成交股數|成交數量|成交量/,["volume"])),open:num(get(/開盤價/,["open"])),high:num(get(/最高價/,["high"])),low:num(get(/最低價/,["low"])),close:num(get(/收盤價/,["close"]))};
        if(row.date&&[row.open,row.high,row.low,row.close].every(Number.isFinite)) rows.push(row);
      }
    }
  }
  return rows;
}
export default {
 async fetch(request) {
  const origin=request.headers.get("Origin")||"";
  if(origin && origin!==ALLOWED_ORIGIN) return json({error:"不允許的網站來源。"},403);
  if(request.method==="OPTIONS") return new Response(null,{status:204,headers:{
    "Access-Control-Allow-Origin":ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods":"GET, OPTIONS",
    "Access-Control-Allow-Headers":"Content-Type",
    "Vary":"Origin"
  }});
  const url=new URL(request.url);
  if(url.pathname!=="/api/history"||request.method!=="GET") return json({error:"找不到 API 路徑。"},404);
  const code=(url.searchParams.get("code")||"").trim();
  if(!/^\d{4,6}$/.test(code)) return json({error:"股票代號格式錯誤。"},400);
  const monthsCount=Math.max(3,Math.min(12,Number(url.searchParams.get("months")||9)));
  const months=monthsBack(monthsCount);
  try{
    let rows=[],market="";
    try{rows=await twse(code,months);if(rows.length)market="TWSE 上市";}catch(e){console.log("TWSE lookup:",e.message);}
    if(!rows.length){rows=await tpex(code,months);if(rows.length)market="TPEx 上櫃";}
    const unique=new Map();
    rows.forEach(r=>unique.set(r.date,r));
    const result=[...unique.values()].sort((a,b)=>a.date.localeCompare(b.date)).slice(-180);
    if(result.length<30)return json({error:"官方來源未回傳足夠歷史日 K（取得 "+result.length+" 筆）。請確認代號、上市櫃別或稍後再試。"},404);
    return json({code,market,source:market+" 官方月行情 API",rows:result});
  }catch(e){return json({error:e.message||"歷史行情服務暫時異常。"},502);}
 }
};
