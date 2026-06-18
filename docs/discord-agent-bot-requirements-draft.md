# Discord Agent Bot 需求草案

版本：v0.1  
狀態：草案  
目標環境：單一 Discord 伺服器  
主要用途：被動式 Discord AI Agent Bot，支援訊息、圖片、附件、網址、程式碼與頻道記憶分析。

---

## 1. 專案目標

本專案要建立一個只服務單一 Discord 伺服器的 AI Agent Bot。  
此 Bot 不走企業級複雜架構，而是以可自架、可維護、可逐步擴充為核心。

Bot 的核心定位是：

> 在指定 Discord 頻道內，讓具備權限的使用者透過 `@Mention AI` 或右鍵訊息選單呼叫 AI，分析訊息、圖片、附件、網址、程式碼、近期討論與歷史記憶。

---

## 2. 核心原則

### 2.1 單一伺服器

- 僅服務單一 Discord Guild。
- 不設計多租戶、多伺服器 SaaS 架構。
- 權限、頻道、資料庫、記憶與設定都以單一伺服器為前提。

### 2.2 被動式 Agent

Bot 不主動插話，不自動監控觸發高風險操作。

Bot 只在以下情況啟動：

1. 使用者 `@Mention AI`
2. 使用者使用右鍵訊息選單
3. 管理員透過 `/admin` 或 `/ai-settings` 操作管理介面

### 2.3 AI 內容來源皆不可信

以下所有內容都視為「不可信資料」，不能改變 Bot 行為規則：

- Discord 訊息
- Discord 歷史記憶
- 圖片 OCR
- 圖片內容
- PDF 文字
- 附件內容
- 程式碼檔案
- 網頁內容
- URL metadata

檔案、網頁或 Discord 訊息中的任何文字，即使看似指令，也只能當作被分析資料，不能當作系統指令。

---

## 3. 使用者與權限範圍

### 3.1 Bot 使用者

Bot 主要服務：

- 管理員
- 指定 Discord 身分組

### 3.2 AI 使用權限

AI 功能必須同時符合兩個條件：

1. 目前頻道在 AI 白名單內
2. 使用者具有 `/ai-settings` 設定的 AI role

例外：

- `.env` 中 `AI_SETTINGS_USER_IDS` 指定的使用者可繞過 AI role 檢查。
- 仍需在 AI 白名單頻道內才能使用 AI。

### 3.3 管理入口權限

管理入口權限由 `.env` 指定使用者 ID 控制。

```env
ADMIN_USER_IDS=111111111111111111,222222222222222222
AI_SETTINGS_USER_IDS=111111111111111111
ALLOW_GUILD_OWNER_ADMIN=true
```

| 入口 | 權限來源 |
|---|---|
| `/admin` | `.env` 的 `ADMIN_USER_IDS` |
| `/ai-settings` | `.env` 的 `AI_SETTINGS_USER_IDS` |
| `/settings` | 由 `/admin` 設定可使用的 Discord role |

---

## 4. Discord 指令與互動入口

### 4.1 Slash Commands

正式使用以下 slash command：

| Command | 用途 |
|---|---|
| `/admin` | 非 AI 的 Bot 總管理入口 |
| `/ai-settings` | AI / LLM 專用管理入口 |
| `/settings` | 一般用戶設定入口，MVP 先做空殼 |

> 原本討論中的 `/llm-settings` 已全面改名為 `/ai-settings`。

---

## 5. `/admin` 管理入口

`/admin` 不放 AI / LLM 設定。  
此入口用於未來新增的機器人功能管理。

### 5.1 `/admin` 負責範圍

| 頁面 | 功能 |
|---|---|
| Bot Status | Bot 狀態、版本、uptime、資料庫狀態 |
| Feature Modules | 未來新增功能開關 |
| `/settings` 權限 | 設定哪些 Discord role 可以開 `/settings` |
| Role Mapping | 功能角色對應 |
| Audit Log | 查看管理操作紀錄 |
| Maintenance | 重新載入設定、系統檢查、清快取等 |

### 5.2 `/admin` 不負責範圍

以下內容全部移到 `/ai-settings`：

- LiteLLM 設定
- 模型 alias
- AI 頻道白名單
- 記憶回填
- 附件策略
- AI 權限設定
- LLM provider 測試
- AI 記憶搜尋設定

---

## 6. `/ai-settings` AI 管理入口

`/ai-settings` 專門管理 AI / LLM 模組。

### 6.1 `/ai-settings` 頁面規劃

| 頁面 | 功能 |
|---|---|
| Overview | AI 模組狀態、LiteLLM 連線狀態、目前模型 alias |
| Access Control | 設定哪些角色可以使用 AI |
| Channel Scope | 設定 AI 可觸發、可記憶、可回填的白名單頻道 |
| Memory | SQLite 記憶、FTS、回填狀態 |
| Backfill | 啟動、暫停、繼續完整回填 |
| Attachments | 附件處理策略 |
| LiteLLM | LiteLLM Base URL、model alias、連線測試 |
| Safety | prompt injection 防護、附件大小限制、URL 抓取限制 |
| Logs | LLM 請求紀錄、錯誤紀錄、回填錯誤 |

### 6.2 AI 使用角色設定

- `/ai-settings` 可以設定哪些 Discord role 可以使用 AI。
- 沒有 AI role 的使用者若 `@Mention AI`，Bot 靜默忽略。
- 沒有 AI role 的使用者若使用右鍵 AI 選單，Bot 用 ephemeral 回覆「你沒有使用 AI 功能的權限」。

---

## 7. `/settings` 一般使用者入口

MVP 第一版先做空殼入口。

### 7.1 第一版顯示內容

```text
Settings

目前尚未開放可調整的個人設定。
此入口保留給未來功能使用。
```

### 7.2 未來可能擴充

- AI 回覆語言偏好
- 回覆簡短 / 詳細偏好
- 是否顯示來源
- 個人通知偏好
- 申請刪除與自己相關的記憶

---

## 8. Components V2 UI 規格

### 8.1 UI 技術

管理面板使用 Discord Components V2。

管理入口包含：

- Container
- Text Display
- Section
- Separator
- Button
- Select Menu
- Role Select Menu
- Channel Select Menu
- Modal

### 8.2 Ephemeral 規格

所有管理與設定入口都使用 ephemeral：

| 指令 | 是否 ephemeral |
|---|---|
| `/admin` | 是 |
| `/ai-settings` | 是 |
| `/settings` | 是 |

### 8.3 管理操作生效規則

| 類型 | 行為 |
|---|---|
| 一般設定 | 按下儲存後立即生效 |
| 危險操作 | 需要二次確認 |

危險操作包含：

- 啟動完整歷史回填
- 暫停 / 停止回填
- 刪除某頻道記憶
- 清空全部記憶
- 重建 FTS index
- Reconciliation
- 修改 AI 白名單頻道
- 修改 LiteLLM Base URL / Key

---

## 9. AI 觸發方式

### 9.1 `@Mention AI`

使用者在 AI 白名單頻道內 mention Bot 觸發 AI。

範例：

```text
@AI 我上傳的圖片內容是什麼？
@AI 統整剛剛頻道內在討論什麼？
@AI 這個網站內容是什麼？
@AI 這個檔案內容在說什麼？
@AI 我跟另一位用戶之前有提到這幾天要出門，是幾月幾號？
```

### 9.2 右鍵訊息選單

第一版支援三個右鍵訊息選單：

| 名稱 | 用途 |
|---|---|
| AI 分析這則訊息 | 分析該訊息文字、附件、圖片、URL、程式碼 |
| AI 摘要上下文 | 以該訊息為中心摘要周邊討論 |
| AI 自訂提問 | 右鍵後跳出 Modal，讓使用者輸入補充問題 |

### 9.3 右鍵自訂提問流程

```text
使用者右鍵訊息
  ↓
選擇 AI 自訂提問
  ↓
跳出 Modal
  ↓
使用者輸入問題
  ↓
Bot 分析被選中的訊息 + 使用者問題
  ↓
Discord Reply 回覆被選中的訊息
```

---

## 10. AI 觸發權限判斷

### 10.1 判斷流程

```text
使用者觸發 AI
  ↓
檢查是否在 AI 白名單頻道
  ↓
檢查使用者是否有 AI role
  ↓
若沒有 AI role，檢查是否在 AI_SETTINGS_USER_IDS
  ↓
通過後進入 Content Resolver
  ↓
呼叫 LiteLLM
  ↓
用 Discord Reply 回覆
```

### 10.2 觸發失敗行為

| 情境 | 行為 |
|---|---|
| 非白名單頻道 `@Mention AI` | 公開 Discord Reply：此頻道尚未啟用 AI 功能 |
| 沒有 AI role 但 `@Mention AI` | 靜默忽略 |
| 非白名單頻道使用右鍵 AI | Ephemeral 回覆：此頻道尚未啟用 AI 功能 |
| 沒有 AI role 使用右鍵 AI | Ephemeral 回覆：你沒有使用 AI 功能的權限 |
| LiteLLM / 模型全部失敗 | 公開 Discord Reply：目前 AI 服務暫時不可用，附錯誤代碼 |

---

## 11. AI 回覆規格

### 11.1 回覆方式

Bot 使用 Discord Reply 回覆，不在內容開頭額外 `@使用者`。

| 觸發方式 | Bot reply 目標 |
|---|---|
| `@Mention AI` | reply 使用者那則提問 |
| 使用者回覆圖片並 `@Mention AI` | reply 使用者那則提問，但分析被回覆的圖片 |
| 右鍵「AI 分析這則訊息」 | reply 被右鍵選中的那則訊息 |
| 右鍵「AI 摘要上下文」 | reply 被右鍵選中的那則訊息 |
| 右鍵「AI 自訂提問」 | reply 被右鍵選中的那則訊息 |

### 11.2 Reply 通知

- 使用 Discord Reply。
- 通知被回覆者。
- 不在內容中額外 `@使用者`。
- 避免 LLM 生成內容中的 `@everyone`、角色 mention、使用者 mention 真的觸發通知。

### 11.3 預設回答語言

Bot 預設永遠使用繁體中文回答。

例外：

- 使用者明確要求英文或其他語言
- 翻譯任務指定目標語言
- 程式碼、錯誤訊息、API 名稱保留原文
- 引用來源原文可保留原文，再用繁中解釋

### 11.4 長回答

若 AI 回答超過 Discord 單則訊息限制，Bot 自動拆成多則 Discord 訊息。

格式：

```text
[1/3]
第一段回答內容……

[2/3]
第二段回答內容……

[3/3]
第三段回答內容……
```

第一則使用 Discord Reply，後續訊息接在同頻道。

### 11.5 來源顯示

- 短答最多顯示 3 個來源。
- 長答使用 `.md` 附件列完整來源。

### 11.6 分析中提示

不顯示「正在分析中」。  
使用者只會看到完成後的回答。

### 11.7 失敗錯誤代碼

使用者看到簡短錯誤代碼，方便回報管理員。

範例：

```text
目前 AI 服務暫時不可用，請稍後再試。
錯誤代碼：AI-LLM-001
```

建議錯誤代碼：

| 錯誤代碼 | 意義 |
|---|---|
| AI-AUTH-001 | 使用者沒有權限 |
| AI-CHANNEL-001 | 頻道未啟用 AI |
| AI-LITELLM-001 | LiteLLM 無法連線 |
| AI-LLM-001 | 所有模型 fallback 失敗 |
| AI-ATTACH-001 | 附件超過大小限制 |
| AI-ATTACH-002 | 附件格式不支援 |
| AI-URL-001 | URL 無法讀取 |
| AI-URL-002 | URL 被安全規則阻擋 |
| AI-MEMORY-001 | 記憶搜尋失敗 |
| AI-BACKFILL-001 | 回填任務失敗 |
| AI-UNKNOWN-001 | 未分類錯誤 |

---

## 12. LLM Gateway 設計

### 12.1 核心決策

Bot 只呼叫 LiteLLM，不直接碰 OpenRouter、OpenAI、Anthropic、Gemini 或其他 Provider。

正式架構：

```text
Discord Bot
  ↓
LiteLLM Proxy
  ↓
OpenRouter
  ↓
各家模型
```

### 12.2 LiteLLM

LiteLLM 作為 OpenAI-compatible Gateway，負責：

- Provider routing
- fallback
- virtual key
- model alias
- Dashboard
- usage tracking
- timeout / retry
- 上游 OpenRouter 設定

### 12.3 模型 alias

Bot 只認以下 alias：

```text
discord-text
discord-vision
discord-document
```

LiteLLM 內部再設定 fallback。

### 12.4 LiteLLM Dashboard

需要啟用 LiteLLM Dashboard。  
LiteLLM Dashboard 使用 Postgres 保存模型、key、usage、成本與管理設定。

### 12.5 Dev / Prod LiteLLM

dev/prod 共用同一個 LiteLLM，但使用不同 Discord Bot Token、不同 SQLite、不同 LiteLLM virtual key。

| 環境 | Discord Token | SQLite | LiteLLM Key |
|---|---|---|---|
| prod | 正式 Bot token | bot-prod.sqlite | sk-discord-bot-prod |
| dev | 測試 Bot token | bot-dev.sqlite | sk-discord-bot-dev |

---

## 13. 部署架構

### 13.1 目標環境

- Ubuntu 26.04 LTS
- Docker Compose
- 一個 container 運行正式 Bot
- 一個 container 用於開發 / 測試 / 編寫程式
- 一個 LiteLLM Proxy container
- 一個 LiteLLM Postgres container

### 13.2 Container 規劃

```text
Ubuntu 26.04 LTS Host
  └─ Docker Compose
      ├─ bot-prod
      ├─ bot-dev
      ├─ litellm
      ├─ litellm-postgres
      └─ optional: reverse proxy
```

### 13.3 Bot 技術棧

| 類別 | 選型 |
|---|---|
| 語言 | TypeScript |
| Discord SDK | discord.js |
| Bot DB | SQLite |
| 搜尋 | SQLite FTS5 |
| LLM Gateway | LiteLLM Proxy |
| LiteLLM DB | Postgres |
| 部署 | Docker Compose |

---

## 14. `.env` 規劃

### 14.1 Discord Bot `.env`

```env
DISCORD_TOKEN=
DISCORD_CLIENT_ID=
DISCORD_GUILD_ID=

ADMIN_USER_IDS=
AI_SETTINGS_USER_IDS=
ALLOW_GUILD_OWNER_ADMIN=true

DATABASE_URL=file:./data/bot.sqlite

LITELLM_BASE_URL=http://litellm:4000/v1
LITELLM_API_KEY=

DEFAULT_SUMMARY_MESSAGE_LIMIT=50
REPLY_MENTION_USER=true
SAVE_BOT_MESSAGES=false
ATTACHMENT_MAX_MB=10
BACKFILL_INCLUDE_THREADS=true
BACKFILL_INCLUDE_FORUM_THREADS=true
```

### 14.2 LiteLLM `.env`

```env
LITELLM_MASTER_KEY=
LITELLM_SALT_KEY=
DATABASE_URL=
OPENROUTER_API_KEY=
```

---

## 15. 訊息記憶設計

### 15.1 保存範圍

只保存：

- AI 白名單頻道
- Bot 可讀取的 thread
- Bot 可讀取的 forum / media 貼文
- 真人訊息

不保存：

- Bot 訊息
- Webhook 訊息
- AI 回答內容
- 非白名單頻道內容

### 15.2 歷史回填

- 白名單頻道全部可取得歷史都要回填。
- 包含 Bot 可讀取的 thread / forum / media 貼文。
- 回填只從 `/ai-settings` 啟動。
- 不提供 CLI 啟動回填。

### 15.3 訊息刪除同步

若 Discord 訊息被刪除：

- 刪除 messages 原文
- 刪除 FTS index
- 刪除 attachment metadata
- 刪除 extracted text
- 只保留 deletion log，不保留內容

### 15.4 編輯訊息

編輯過的 Discord 訊息：

- 更新資料庫為最新版
- 只保留最新版內容
- 記錄該訊息曾經被編輯過

---

## 16. 完整回填行為

### 16.1 啟動方式

```text
/ai-settings
  → Memory
  → Backfill
  → Start Full Backfill
  → 二次確認
  → 開始背景回填
```

### 16.2 回填期間 AI 可用

回填期間 AI 功能仍可使用。  
回填任務低優先權背景執行。

### 16.3 回填速度

採保守策略：

- 一個頻道 / thread 一次抓一批
- 每批最多 100 則
- 寫入 SQLite 後才抓下一批
- 遇到 rate limit 就等待
- 不大量並行掃描所有頻道

### 16.4 回填進度

顯示每個頻道 + thread / forum 進度。

範例：

```text
完整回填狀態：執行中

總進度：
- 頻道：3 / 12 完成
- Thread / Forum：18 / 74 完成
- 已寫入訊息：128,430 則
- 目前處理：#討論區 / thread: 週末出門討論
- 最近錯誤：無
```

### 16.5 中斷與重試

- 自動重試 3 次。
- 仍失敗則標記 failed。
- 管理員可在 `/ai-settings` 手動重試、跳過或查看錯誤。

### 16.6 回填 Audit Log

記錄：

- 啟動
- 暫停
- 繼續
- 失敗
- 完成

不把每個頻道完成都寫入 audit log，只在 backfill status 顯示。

---

## 17. 記憶搜尋行為

### 17.1 搜尋範圍

使用者問歷史記憶時：

1. 先搜尋當前頻道
2. 若結果不足，再搜尋全部 AI 白名單頻道

### 17.2 搜尋候選

- 取前 20 則候選訊息
- 每則候選補前後各 5 則上下文

### 17.3 回答來源

回答歷史記憶問題時，盡量附 Discord 原訊息來源。

來源格式：

- 頻道
- 作者
- 時間
- Discord message link

### 17.4 找不到記憶

若找不到相關記憶：

- 直接說找不到
- 請使用者補充時間、頻道或關鍵字
- 不猜測

### 17.5 已刪除訊息

如果相關訊息已刪除：

- 可以保留刪除紀錄
- 不保留內容
- 不回答已刪除內容
- 可提示「部分相關訊息可能已被刪除，因此無法確認完整內容」

---

## 18. 附件與 URL 分析

### 18.1 附件保存策略

回填時只保存附件 metadata，不下載原始檔。

保存：

- attachment_id
- message_id
- filename
- content_type
- size
- last_seen_url

不保存：

- 原始圖片
- 原始 PDF
- 原始 docx/xlsx
- 原始壓縮檔

### 18.2 附件分析策略

採用 A → B → C → D fallback：

```text
A. 直接傳 Discord URL 給 LLM Provider
B. Bot 下載到記憶體，轉 Base64 傳給模型
C. Bot 下載後上傳到 Provider Files API
D. Bot 本地解析，再把文字交給 LLM
```

如果全部失敗，Bot 回覆使用者無法使用或無法分析該附件。

### 18.3 檔案大小限制

第一版限制：

```env
ATTACHMENT_MAX_MB=10
```

超過 10 MB 時回覆：

```text
這個附件超過目前 10 MB 的分析上限，暫時無法處理。
請重新上傳較小的檔案，或改成文字、PDF 摘要、圖片截圖。
```

### 18.4 extracted text 保存

檔案 extracted text 會保存，方便下次搜尋與重複分析。

適用：

- PDF 抽文字
- docx 抽文字
- xlsx/csv 表格摘要
- txt/md/log
- 程式碼檔案
- 圖片 OCR 文字

如果原 Discord 訊息被刪除，對應 extracted text 也要刪除。

### 18.5 URL 分析

URL 分析限制：

- 只抓公開網頁
- 不登入
- 不繞過 paywall
- 不自動點擊危險操作
- 不存取 localhost / 內網 / metadata service
- 限制 redirect 次數、timeout、response size

URL 只保存 metadata，不保存正文。

保存：

- URL
- normalized URL
- title
- HTTP status
- content type
- fetched_at
- source message_id

不保存：

- 完整網頁正文

---

## 19. AI 對話紀錄與隱私保存

### 19.1 AI 對話只保存 metadata

Bot DB 不保存完整：

- 使用者問題
- 完整 prompt
- 完整 response
- 完整上下文片段
- 完整檔案內容

保存：

- actor_id
- channel_id
- source_message_id
- trigger_type
- task_type
- model_alias
- fallback_chain
- status
- error_type
- latency_ms
- token usage
- created_at

### 19.2 AI 回答不寫入記憶

AI 回答不進入 messages 記憶資料庫，也不進 FTS5。

原因：

- 避免 AI 回答污染未來搜尋結果
- 避免模型幻覺被當成歷史事實
- 符合只保存真人訊息的規則

### 19.3 使用者刪除請求

MVP 先由管理員處理。

流程：

```text
使用者提出刪除請求
  ↓
管理員進 /ai-settings
  ↓
搜尋該使用者相關訊息
  ↓
選擇刪除範圍
  ↓
二次確認
  ↓
刪除 messages / FTS / attachments / extracted text
  ↓
寫入 audit log
```

---

## 20. Audit Log

### 20.1 保留期限

Audit log 永久保留。

### 20.2 記錄範圍

記錄所有管理寫入操作：

- `/admin` 權限變更
- `/ai-settings` AI role 變更
- 頻道白名單變更
- 回填啟動 / 暫停 / 繼續 / 失敗 / 完成
- 附件策略變更
- LiteLLM 設定變更
- 系統維護操作
- 刪除記憶操作
- Reconciliation 操作

### 20.3 Audit Log 欄位

```sql
CREATE TABLE audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id TEXT NOT NULL,
  actor_name TEXT,
  entrypoint TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT,
  old_value TEXT,
  new_value TEXT,
  result TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

---

## 21. 資料庫草案

### 21.1 messages

```sql
CREATE TABLE messages (
  message_id TEXT PRIMARY KEY,
  guild_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  parent_channel_id TEXT,
  author_id TEXT NOT NULL,
  author_name TEXT,
  content TEXT,
  created_at TEXT NOT NULL,
  edited_at TEXT,
  edited_flag INTEGER NOT NULL DEFAULT 0,
  referenced_message_id TEXT,
  message_url TEXT,
  has_attachments INTEGER NOT NULL DEFAULT 0
);
```

### 21.2 message_fts

```sql
CREATE VIRTUAL TABLE message_fts USING fts5(
  message_id UNINDEXED,
  channel_id UNINDEXED,
  author_name,
  content,
  tokenize = 'unicode61'
);
```

### 21.3 attachments

```sql
CREATE TABLE attachments (
  attachment_id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL,
  filename TEXT,
  content_type TEXT,
  size_bytes INTEGER,
  last_seen_url TEXT,
  proxy_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 21.4 attachment_extractions

```sql
CREATE TABLE attachment_extractions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  attachment_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  filename TEXT,
  content_type TEXT,
  size_bytes INTEGER,
  extracted_text TEXT,
  extraction_method TEXT,
  extracted_at TEXT NOT NULL
);
```

### 21.5 url_fetch_logs

```sql
CREATE TABLE url_fetch_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT,
  url TEXT NOT NULL,
  normalized_url TEXT,
  title TEXT,
  http_status INTEGER,
  content_type TEXT,
  fetched_at TEXT NOT NULL,
  error_type TEXT
);
```

### 21.6 deleted_messages

```sql
CREATE TABLE deleted_messages (
  message_id TEXT PRIMARY KEY,
  guild_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  deleted_at TEXT NOT NULL,
  deletion_source TEXT NOT NULL
);
```

### 21.7 ai_allowed_roles

```sql
CREATE TABLE ai_allowed_roles (
  role_id TEXT PRIMARY KEY,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 21.8 ai_channel_whitelist

```sql
CREATE TABLE ai_channel_whitelist (
  channel_id TEXT PRIMARY KEY,
  include_threads INTEGER NOT NULL DEFAULT 1,
  memory_enabled INTEGER NOT NULL DEFAULT 1,
  backfill_enabled INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

### 21.9 ai_runtime_settings

```sql
CREATE TABLE ai_runtime_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_by TEXT,
  updated_at TEXT NOT NULL
);
```

### 21.10 ai_request_logs

```sql
CREATE TABLE ai_request_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  source_message_id TEXT,
  trigger_type TEXT NOT NULL,
  task_type TEXT NOT NULL,
  model_alias TEXT,
  fallback_chain TEXT,
  status TEXT NOT NULL,
  error_type TEXT,
  latency_ms INTEGER,
  input_tokens INTEGER,
  output_tokens INTEGER,
  created_at TEXT NOT NULL
);
```

### 21.11 backfill_jobs

```sql
CREATE TABLE backfill_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT NOT NULL,
  scope TEXT NOT NULL,
  started_by TEXT NOT NULL,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT
);
```

### 21.12 backfill_targets

```sql
CREATE TABLE backfill_targets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL,
  channel_id TEXT NOT NULL,
  parent_channel_id TEXT,
  type TEXT NOT NULL,
  status TEXT NOT NULL,
  oldest_fetched_message_id TEXT,
  fetched_message_count INTEGER NOT NULL DEFAULT 0,
  retry_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  started_at TEXT,
  updated_at TEXT NOT NULL,
  completed_at TEXT
);
```

---

## 22. 模組切分草案

```text
src/
  bot/
    commands/
      admin.command.ts
      ai-settings.command.ts
      settings.command.ts

    interactions/
      component-router.ts
      modal-router.ts
      message-context-router.ts
      mention-router.ts

  admin/
    admin-panel.ts
    feature-settings.ts
    settings-permissions.ts
    audit-log.ts

  ai-settings/
    ai-panel.ts
    access-control-panel.ts
    channel-scope-panel.ts
    memory-panel.ts
    backfill-panel.ts
    attachment-policy-panel.ts
    litellm-panel.ts
    safety-panel.ts
    logs-panel.ts

  ui/
    components-v2/
      panel.ts
      navigation.ts
      buttons.ts
      selects.ts
      modals.ts
      status-card.ts

  auth/
    env-admin-auth.ts
    role-permission-auth.ts
    ai-access-control.ts

  llm/
    litellm-client.ts
    model-alias.ts
    provider-health.ts
    prompt-builder.ts
    response-formatter.ts

  memory/
    sqlite.ts
    message-store.ts
    fts.ts
    backfill.ts
    deletion-sync.ts
    reconciliation.ts

  content/
    resolver.ts
    attachment-resolver.ts
    url-resolver.ts
    image-resolver.ts
    document-resolver.ts
    code-resolver.ts

  safety/
    untrusted-content.ts
    ssrf-guard.ts
    prompt-injection-guard.ts

  logs/
    audit-log-store.ts
    ai-request-log-store.ts
```

---

## 23. GitHub 專案參考策略

目前沒有單一成熟 GitHub 專案能直接完整符合本需求。

建議組合：

| 用途 | 建議 |
|---|---|
| LLM Gateway | 直接使用 LiteLLM |
| Discord Bot 骨架 | 參考或 fork Discord.js v14 + Components V2 template |
| Components V2 UI | 參考 Components V2 範例專案 |
| Discord RAG / 記憶 | 參考 knowledge bot 類專案的索引思路 |
| 完整成品 | 不建議硬改現成 ChatGPT Discord Bot |

推薦實作方向：

```text
1. LiteLLM 直接部署
2. Discord.js + Components V2 template 作為 bot 骨架
3. 自行實作 SQLite FTS5 記憶、回填、權限、附件策略與管理面板
```

---

## 24. MVP 必做功能

| 功能 | 說明 |
|---|---|
| `@Mention AI` | 使用者 mention Bot 後回答 |
| 右鍵分析訊息 | 分析指定訊息 |
| 右鍵摘要上下文 | 摘要指定訊息周邊討論 |
| 右鍵自訂提問 | Modal 輸入問題 |
| Discord Reply | 回覆原訊息，通知被回覆者 |
| `/admin` | 非 AI 管理入口 |
| `/ai-settings` | AI 管理入口 |
| `/settings` | 空殼入口 |
| Components V2 | ephemeral 管理 UI |
| AI role 權限 | `/ai-settings` 設定 |
| AI 頻道白名單 | `/ai-settings` 設定 |
| LiteLLM Proxy | Bot 只呼叫 LiteLLM |
| OpenRouter 上游 | LiteLLM → OpenRouter |
| SQLite + FTS5 | 訊息記憶與搜尋 |
| 完整歷史回填 | AI 白名單頻道全部回填 |
| Thread / Forum 回填 | 包含 Bot 可讀內容 |
| 附件 metadata | 回填時保存 metadata |
| 附件分析 fallback | URL → Base64 → Files API → 本地解析 |
| URL 分析 | 只抓公開網頁 |
| 檔案 extracted text | 保存並可搜尋 |
| 刪除同步 | Discord 刪除後 DB 同步刪除 |
| Audit Log | 永久保存管理操作 |
| 錯誤代碼 | AI 失敗時提供簡短代碼 |

---

## 25. 第二階段功能

| 功能 | 說明 |
|---|---|
| embedding 語意搜尋 | 讓歷史記憶搜尋更接近 ChatGPT 記憶 |
| 更完整 docx/xlsx 分析 | 深度表格與文件結構分析 |
| PDF 頁面圖片分析 | 掃描型 PDF、圖表、截圖 |
| OCR 強化 | 更完整圖片文字辨識 |
| Web Admin UI | 若 Discord Components V2 不夠用，追加網頁管理介面 |
| `/settings` 個人偏好 | 回覆語言、風格、來源顯示偏好 |
| 使用者刪除申請 | 讓使用者申請刪除與自己相關記憶 |
| Markdown 完整報告 | 長回答或多來源分析可附 `.md` |
| Reconciliation UI | 更完整離線後資料比對修復 |
| 本機模型 Ollama | 可選擇降低第三方 API 依賴 |

---

## 26. 暫不做

| 功能 | 原因 |
|---|---|
| 外部工具整合 | 已移除 |
| 任務管理 | 已移除 |
| 主動提醒 | 與被動式 Bot 定位不符 |
| 自動審核 / 刪文 | 高風險，暫不做 |
| 企業級架構 | 單一伺服器不需要 |
| 多伺服器 SaaS | 不符合需求範圍 |
| 保存所有原始附件 | 儲存成本與隱私壓力高 |
| 保存完整 AI prompt / response | 隱私與資料污染風險高 |

---

## 27. 待實作時再確認事項

以下項目尚未進入實作細節定案：

1. LiteLLM 實際 OpenRouter model alias
2. LiteLLM fallback chain 詳細順序
3. Discord Components V2 實際 UI 畫面
4. SQLite migration 工具
5. Drizzle / Prisma / better-sqlite3 選型
6. PDF / docx / xlsx 解析套件
7. URL 正文擷取套件
8. SSRF guard 實作方式
9. 回填 reconciliation 演算法
10. Docker Compose 最終檔案
11. CI / 測試策略
12. GitHub 專案骨架是否 fork 或從零建立

---

## 28. 最終摘要

本專案是一個單一 Discord 伺服器使用的被動式 AI Agent Bot。

它的核心能力是：

```text
@Mention AI / 右鍵訊息選單
  ↓
檢查頻道白名單與 AI role
  ↓
解析訊息、圖片、附件、URL、程式碼、歷史記憶
  ↓
將可信系統規則與不可信資料隔離
  ↓
透過 LiteLLM 呼叫 OpenRouter 模型
  ↓
以 Discord Reply 用繁體中文回答
  ↓
附來源、保存 metadata、寫入 audit log
```

專案不追求企業級複雜架構，而是以：

- Docker Compose
- TypeScript
- discord.js
- SQLite + FTS5
- LiteLLM Proxy
- OpenRouter
- Components V2

作為可落地、可維護、可逐步擴充的基礎。
