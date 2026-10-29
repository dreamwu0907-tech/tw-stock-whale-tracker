# 台股大戶動向觀察站（免費 MVP）

這是一個可部署到 GitHub Pages 的靜態網頁。GitHub Actions 於台灣時間約 16:15（週一至週五）抓取公開盤後資料，更新 `data/ranking.json`，網頁讀取該 JSON 顯示每日排行。

## 目前版本的範圍與限制

- **已實作：** 證交所上市股票日行情、三大法人每日買賣超、量價＋法人觀察分數。
- **尚未實作：** 上櫃股票、集保戶股權分散表（每週）、券商分點買賣超。
- 因此本工具目前是「大戶可能進場的代理訊號」，**不能辨識真實大戶，也不應將法人買賣超直接視為大戶進出**。
- 歷史成交量均值目前只對成交量較大的前 250 檔拉取；其他股票成交量比可能顯示「—」。這是為了減少對官方 API 的請求負載。
- 免費公開 API 可能調整格式、延遲或限流。遇到上游異常時需查看 Actions 執行紀錄。

## 免費部署（約 10 分鐘）

1. 登入或註冊 GitHub。
2. 建立一個新的 **Public repository**，例如 `tw-stock-whale-tracker`。
3. 將本資料夾內的所有檔案上傳至 repository 根目錄（保留 `.github/workflows/update.yml`）。
4. 進入 **Settings → Pages**，在 Build and deployment 選 `Deploy from a branch`，Branch 選 `main`、資料夾選 `/ (root)`，儲存。
5. 進入 **Actions**，允許啟用 workflows。打開 `Update stock data`，點 `Run workflow` 手動跑第一次更新。
6. 等 workflow 成功後，網站網址通常會是 `https://你的GitHub帳號.github.io/tw-stock-whale-tracker/`。
7. 網站打開後按「重新載入」即可讀取最新排行。GitHub Pages 與 GitHub Actions 對公開 repository 的個人免費使用通常可免費使用；請以 GitHub 當下方案規則為準。

## 資料更新頻率

| 資料 | 頻率 | 本版狀態 |
|---|---|---|
| 上市股票行情 | 每交易日盤後 | 已接入 |
| 外資／投信／自營商買賣超 | 每交易日盤後 | 已接入（T86） |
| 集保股權分散表 | 每週 | 尚未接入 |
| 券商分點買賣超 | 依來源而定；部分官方服務有驗證或授權限制 | 尚未接入 |
| 網站排行 JSON | GitHub Actions 工作流程排程，每週一至五約 16:15 台灣時間 | 已設定 |

## 計分邏輯（可自行調整）

- 起始分數 35。
- 外資買賣超、投信買賣超、自營商買賣超對分數加減分，並設定上下限。
- 當日成交量相對近期均量放大時加分。
- 小幅上漲（0–4%）加分；單日漲幅超過 7% 或下跌超過 4% 會扣分。
- 分數是排序用的啟發式指標，不是經過驗證的預測模型，也不構成投資建議。

## 常見問題

**為什麼不能直接顯示「大戶買進」？**  
公開資料通常無法逐一辨識最終投資人的身份。集保資料提供持股級距的週變化，券商分點則反映該分點客戶與自營部門合計交易，不等於單一大戶。

**為什麼只有上市股票？**  
第一版優先以證交所公開 API 建立可運作的基礎版本。上櫃市場需要接入櫃買中心 API，集保週資料也需另外整合。

**資料沒更新怎麼辦？**  
到 GitHub repository → Actions → `Update stock data` 查看錯誤紀錄。也可以手動執行 workflow。API 格式若變更，需更新 `scripts/update_data.py`。

## 官方資料來源

- TWSE OpenAPI：<https://openapi.twse.com.tw/>
- TWSE 公開資料平台：<https://www.twse.com.tw/>
- TDCC 集保戶股權分散表：<https://www.tdcc.com.tw/portal/zh/smWeb/qryStock>
- 政府資料開放平台：<https://data.gov.tw/>
