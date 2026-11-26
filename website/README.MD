# 來源：行動屏大 RWD 網站 (`website/`)

本資料夾負責「行動屏大 RWD 網站」資料來源的爬蟲與 API 適配實作。

## 開發前必讀
請先閱讀專案根目錄的 **[`ARCHITECTURE.md`](../ARCHITECTURE.md)**，裡面完整說明了：
1. **紅綠燈修改守則**：本資料夾 (`website/`) 可自由新增／修改檔案；`application/`、`core/`、`ui/`、`discord_bot.py`、`main.py` 皆已鎖定請勿更動。
2. **固定資料結構規格（Data Contract）**：`website/Adapter.py` 必須繼承 `core/base_adapter.py` 的 `BaseNptuAdapter`，並將抓回的資料轉換為文件第 4 節規定的標準欄位名稱。
3. **非同步與快取規範**：請使用 `httpx.AsyncClient`（全 `async def`），並透過 `self.dumper.dump("website", ...)` 保存原始抓包至 `temp_data/`。

## 建議內部檔案拆分
```text
website/
├── README.MD
├── __init__.py
├── Adapter.py      # (已建立骨架) 實作 BaseNptuAdapter 並保留 Adapter = WebsiteAdapter
├── client.py       # (可自行新增) 網站登入 Session/Cookie 管理與 httpx 請求
└── parser.py       # (可自行新增) HTML / JSON 解析並轉換為標準欄位
```

## 測試切換方式
在 `.env` 設定 `NPTU_DEFAULT_SOURCE=website` 即可讓整個 Discord Bot 無縫切換使用本來源進行測試。
