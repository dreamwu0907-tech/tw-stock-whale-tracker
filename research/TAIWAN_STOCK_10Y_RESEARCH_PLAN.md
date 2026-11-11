# 台股十年起漲／下跌歷史研究計畫

## 研究範圍

- 期間：2016-01-01 至 2026-11-11；實際起訖以來源可取得資料為準。
- 標的：TWSE 上市與 TPEx 上櫃普通股；排除 ETF、ETN、權證、特別股、興櫃。
- 已下市／下櫃股票：納入可取得的歷史證券名單與行情；若無法取得完整名單，報告必須標示涵蓋率，不得宣稱完整全市場。
- 研究方向：起漲、主升段、轉弱、主跌段。
- 預測觀察期：訊號日後 5、10、15、20、60 個交易日；1～3 週主要看 5、10、15 日。

## 目前專案基線

原網站的每日排行與技術快取不是十年全市場資料庫。現有技術歷史資料主要覆蓋成交量較大的部分股票；集保股權分散表尚未接入。原本的 DMI 分數屬啟發式篩選，不能當作回測績效。

本研究應獨立於每日排行模組，避免改動既有網站行為。

## 資料表設計

### 1. instruments
- stock_id：證券代號
- stock_name：名稱
- market：TWSE / TPEx
- security_type：普通股等
- listed_date、delisted_date
- source、source_updated_at

### 2. daily_prices
主鍵：(trade_date, market, stock_id)
- trade_date、stock_id、market
- open、high、low、close
- volume_shares、turnover、trade_count
- price_change、trading_status
- source、ingested_at

需保留未復權原始行情；另建立 corporate_actions / adjusted_prices，處理除權息、減資、分割等事件。回測報酬需使用一致的調整口徑，避免把除權息缺口誤判成暴跌。

### 3. institutional_flows
主鍵：(trade_date, market, stock_id)
- foreign_buy、foreign_sell、foreign_net
- trust_buy、trust_sell、trust_net
- dealer_buy、dealer_sell、dealer_net
- data_publish_time、source

### 4. margin_short
主鍵：(trade_date, market, stock_id)
- margin_balance、margin_change
- short_balance、short_change
- short_sale_volume、short_cover_volume（來源有提供時）
- data_publish_time、source

### 5. securities_lending
主鍵：(trade_date, market, stock_id)
- lending_sell_volume
- lending_sell_balance
- lending_return_volume
- available_lending_sell_shares（若有）
- data_publish_time、source

不可把借券餘額、借券賣出餘額、當日借券賣出量混為同一欄位；借券不必然等於看空。

### 6. ownership_distribution
主鍵：(reference_date, market, stock_id, holding_bucket)
- holding_bucket
- holder_count、share_count、share_ratio
- publication_date、source

集保股權分散資料是週頻率，且公布時間晚於資料基準日。回測只能從實際公布日之後使用該筆資訊，不能回填到基準日當天。

### 7. market_context
- trade_date、TAIEX、TPEx index
- industry_index / industry_return（可取得時）
- market_regime、source

### 8. derived_features
- MA5/10/20/60/120、RSI14、MACD(12,26,9)、KD(9,3,3)
- DMI/ADX(14)、ATR14
- relative_volume、turnover_ratio
- 20/60/120 日報酬、距離 20/60 日高低點
- candlestick_pattern、breakout_flags
- 所有特徵必須由當日及之前已知資料計算

## 起漲與下跌事件定義（研究標籤）

不能先看結果再挑案例。第一版採雙層標籤：

### A. 前瞻報酬標籤
以訊號日收盤價為基準，計算未來 5、10、15、20、60 交易日報酬；同時記錄最大有利波動 MFE、最大不利波動 MAE。另記錄未來區間是否觸及漲停／跌停、停牌或無成交。

### B. 趨勢事件標籤
以波動度標準化的門檻定義事件，例如未來 20 個交易日最大上漲幅度達 +2 ATR 且最大回撤未超過預設容忍值，標記為起漲候選；向下達 -2 ATR 則標記為下跌候選。門檻需做敏感度測試（1.5、2.0、2.5 ATR），不把單一門檻當唯一真理。
事件起點只可使用當時可得資料判定；事後高低點只能用來產生結果標籤，不能作為當時輸入特徵。

## 特徵研究清單

### 技術面
- DMI：+DI、-DI、兩者差距、交叉前斜率、ADX 斜率及所處區間。
- MACD：DIF/DEA 交叉、柱狀體方向與連續變化。
- KD、RSI：低檔轉折、50 軸位置、背離。
- 均線：糾結、斜率、排列、突破與回測。
- ATR：波動收縮、突破後擴張。
- 價量：量縮整理、相對量放大、價漲量增、爆量不漲。
- K 線：吞噬、錘頭、流星、長上／下影、跳空。
- 型態：平台突破、W 底、前高突破；型態演算法必須明確定義，避免人工主觀標註。

### 籌碼面
- 三大法人單日、5／10／20 日累計買賣超。
- 法人買超占成交量比例及連續性。
- 融資餘額變化、融券餘額變化。
- 借券賣出量與借券賣出餘額變化。
- 集保大額持股級距占比變化、股東人數變化。
- 籌碼資料需同時保留原始股數及換算張數；不可只保留比率。

## 統計與驗證方法

每個訊號及訊號組合至少輸出：
- 有效樣本數、上漲機率、平均／中位數報酬
- 5／10／15／20／60 日報酬分布
- MFE、MAE、最大回撤
- 樣本期間、上市／上櫃分組、產業分組
- 缺值率、資料涵蓋率、資料來源

驗證規則：
1. 嚴格時間序列切分：較早年份訓練／探索，中間年份驗證，最近年份保留作樣本外測試。
2. 不可隨機打散時間序列。
3. 同一股票相鄰且重疊的事件需去重或以群聚方式計算信賴區間，避免把同一波行情重複當成獨立樣本。
4. 納入交易成本、滑價、漲跌停無法成交、停牌與下市處理。
5. 與簡單基準比較，例如單純站上 MA20、隨機訊號、買進持有。
6. 多重訊號測試需控制過度擬合；最終結論以樣本外結果為主。

## 資料來源與目前已知限制

- TWSE OpenAPI：上市日行情及部分法人／信用交易資訊。OpenAPI 的全市場當日快照不等於十年歷史資料；歷史日線通常需按個股、月份回補。
- TPEx OpenAPI：上櫃日行情及部分信用交易資訊；需逐項確認歷史端點、欄位與可回溯期間。
- TDCC 集保股權分散表：官方網站說明資料每週編製；目前線上歷史查詢頁標示歷史檔案保存期間一年。十年歷史需要另行確認可合法取得的歷史來源，不可假設官方查詢頁能直接提供十年。
- 借券與法人歷史資料：必須逐項確認上市／上櫃端點與回溯期間，缺資料時標記 NA，不可用當日快照冒充歷史序列。
- 所有來源需保存 URL、擷取時間、欄位對照與原始回應檔案雜湊值，便於稽核。

## 儲存與部署原則

原始十年全市場日資料不應直接塞入 GitHub Pages JSON 或網站前端。先用分年／分市場分檔的壓縮 CSV 或 Parquet 建立可重跑的回補流程，完成容量與 API 限流測試後，再決定長期資料庫。網站只發布研究摘要、指標統計與回測結果；原始資料與研究輸出分離。

## 建置里程碑

1. 資料源盤點與 API 欄位驗證：先驗證 1 檔上市、1 檔上櫃，涵蓋正常交易、除權息與下市案例。
2. 股票主檔與日行情回補：建立上市／上櫃十年 OHLCV；先抽樣核對，再擴大全市場。
3. 法人、融資融券、借券歷史回補。
4. 集保週資料取得與公告日期對齊。
5. 指標計算與事件標籤。
6. 全市場統計、分組分析及樣本外驗證。
7. 將驗證有效的條件回饋到既有台股網站。

## 第一個驗收標準

在聲稱「全市場十年」之前，必須提供：
- 上市／上櫃股票主檔筆數與涵蓋期間
- 每年每市場的行情筆數及缺漏比例
- 已下市股票數及其歷史資料涵蓋率
- 法人、融資融券、借券、集保各自的歷史涵蓋率
- 至少抽樣 10 檔上市、10 檔上櫃，核對原始官方頁面與匯入資料

在此之前，任何績效或勝率只能標示為「部分資料初步結果」，不能宣稱代表全台股。
