# GitMoving

方便 Git 倉庫跨平台搬移，**完整保留 commit 歷史**，專為 **private → private** 場景設計。

## 支援平台

| 平台 | 雲端 | 自架 (Self-hosted) |
|------|------|--------------------|
| GitHub | ✅ github.com | ✅ GitHub Enterprise |
| GitLab | ✅ gitlab.com | ✅ 任何 GitLab 執行個體 |
| Bitbucket | ✅ bitbucket.org | ✅ Bitbucket Data Center |

支援所有方向的組合：GitHub → GitLab、Bitbucket → GitHub、GitHub → GitHub（跨組織）⋯

---

## 架構說明

```
GitMoving/
├── gitmoving/
│   ├── cli.py              # CLI 進入點 (click)：migrate / auth / ui
│   ├── auth/
│   │   ├── base.py         # 憑證基底類別 + keyring 儲存
│   │   ├── github.py       # GitHub PAT 驗證
│   │   ├── gitlab.py       # GitLab PAT 驗證
│   │   └── bitbucket.py    # Bitbucket App Password 驗證
│   ├── providers/
│   │   ├── base.py         # BaseProvider 抽象介面（含 list_repos）
│   │   ├── github.py       # GitHub API 操作 (PyGithub)
│   │   ├── gitlab.py       # GitLab API 操作 (python-gitlab)
│   │   └── bitbucket.py    # Bitbucket API 操作 (requests)
│   ├── migrator/
│   │   └── engine.py       # 遷移流程核心 (clone → create → push)
│   ├── ui/
│   │   ├── __init__.py
│   │   └── app.py          # Textual TUI 三分頁應用程式
│   └── utils/
│       └── git.py          # git 指令包裝層
├── requirements.txt
└── setup.py
```

### 遷移流程（共用核心）

```
[使用者]
   │
   ├─── gitmoving migrate ...     ← CLI 單一 Repo
   │
   └─── gitmoving ui             ← TUI 多 Repo 批次
          │
          ▼
   ├─ 1. 驗證來源 / 目標平台憑證
   ├─ 2. list_repos() 列舉來源所有 Repo
   ├─ 3. repo_exists() 檢查目標狀態
   ├─ 4. 使用者選取後 → 逐一執行：
   │     ├─ get_repo()       取得 Repo 詳情
   │     ├─ create_repo()    建立目標 Repo（不存在時）
   │     ├─ clone --mirror   完整鏡像複製
   │     └─ push --mirror    推送至目標
   └─ 5. 完成（顯示每個 Repo 的 branch/tag 數量與狀態）
```

---

## 安裝

```bash
# 建議使用虛擬環境
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e .
```

---

## 互動式 TUI（終端機圖形介面）

```bash
gitmoving ui
```

提供三分頁的視覺化操作介面，適合**批次搬移整個組織的所有 Repo**。

### 分頁一：⚙ Setup — 設定來源與目標

```
◀ Source Platform
  Platform:   [ GitHub ▼ ]
  Owner/Org:  [ my-org         ]   ← 用戶名或組織名
  Token:      [ ••••••••••••   ]   ← PAT（可留空，自動讀 keyring / 環境變數）
  Username:   [ Bitbucket 專用  ]
  Base URL:   [ 自架 URL 選填   ]

▶ Destination Platform
  Platform:   [ GitLab ▼ ]
  Owner/Org:  [ new-group       ]   ← 留空則使用 token 擁有者
  Token:      [ 留空重用來源     ]
  ...

                          [ Load Repositories → ]
```

點擊 **Load Repositories** 後，系統會在背景執行緒中：
1. 同時驗證來源與目標憑證
2. 列出來源 owner 下的所有 Repo
3. 逐一檢查目標平台是否已存在同名 Repo
4. 自動切換至 Repositories 分頁

---

### 分頁二：📋 Repositories — 確認並選取

```
[☑ All]  [☐ None]                    [▶ Migrate Selected]
25 repositories · 18 selected · click a row to toggle
──────────────────────────────────────────────────────────────────
  ☑  api-service    main    🔒 private   ✓ exists   API gateway
  ☑  frontend       main    🔒 private   ✗ new      React SPA
  ☐  legacy-app     master  🔒 private   ✓ exists   (未選取)
  ☑  auth-service   main    🔒 private   ✗ new      OAuth2 服務
  ☑  infra-scripts  main    🌐 public    ✗ new      Terraform
```

| 欄位 | 說明 |
|------|------|
| ☑ / ☐ | 是否納入本次遷移，點擊列即可切換 |
| Destination | `✓ exists` = 目標已有此 Repo；`✗ new` = 將自動建立 |
| 🔒 / 🌐 | 來源 Repo 的公/私設定（目標一律建為 private） |

選好後點 **▶ Migrate Selected** 開始遷移。

---

### 分頁三：🚀 Migration — 即時進度

```
Repository      Status       Branches  Tags  Notes
────────────────────────────────────────────────────
api-service     ✓  done      4         12
frontend        ⟳ running    -         -
auth-service    ⏳ pending    -         -
legacy-app      ✗  error     -         -    push rejected: 403

[Migration Log]────────────────────────────────────
[1/4] Migrating api-service …
  → Cloning (mirror)…
  → Pushing  (4 branches, 12 tags)…
  ✓  Done: api-service

[2/4] Migrating frontend …
  → Created: new-group/frontend
  → Cloning (mirror)…
```

遷移在背景執行緒中**循序**處理，介面全程可操作。每個 Repo 的狀態會即時更新。

### TUI 鍵盤快速鍵

| 按鍵 | 功能 |
|------|------|
| `q` | 離開應用程式 |
| `Ctrl+R` | 重新載入 Repo 清單 |
| `Tab` / 方向鍵 | 在分頁與元件間移動 |
| `Enter` | 點擊選取的按鈕或列 |

---

## 快速開始

### 1. 準備存取金鑰

| 平台 | 所需憑證 | 最低權限 |
|------|----------|----------|
| **GitHub** | Personal Access Token (classic) | `repo` |
| **GitLab** | Personal Access Token | `api` |
| **Bitbucket** | App Password | Repositories: Read, Write, Admin |

> 憑證會以安全方式儲存在系統 Keyring（macOS Keychain / Windows Credential Manager / Linux Secret Service）。
> 也可透過環境變數傳入（見下方）。

---

### 2. 執行遷移

#### GitHub → GitLab

```bash
gitmoving migrate \
  --src-provider github  --src-owner my-org    --src-repo my-repo \
  --dst-provider gitlab  --dst-owner my-group
```

#### GitHub → GitHub（跨組織）

```bash
gitmoving migrate \
  --src-provider github --src-owner org-a --src-repo api-service \
  --dst-provider github --dst-owner org-b --dst-repo api-service-v2
```

#### Bitbucket → GitHub

```bash
gitmoving migrate \
  --src-provider bitbucket --src-owner my-team --src-repo legacy-app \
  --dst-provider github    --dst-owner new-org
```

#### 自架 GitLab → 雲端 GitHub

```bash
gitmoving migrate \
  --src-provider gitlab  --src-owner internal-group --src-repo project-x \
  --src-base-url https://gitlab.mycompany.com \
  --dst-provider github  --dst-owner public-org
```

---

### 3. 強制覆寫（目標已有同名 Repo）

```bash
gitmoving migrate \
  --src-provider github --src-owner org-a --src-repo repo \
  --dst-provider github --dst-owner org-b \
  --force
```

---

## 環境變數（免互動驗證）

| 變數 | 對應平台 |
|------|----------|
| `GITHUB_TOKEN` / `GH_TOKEN` | GitHub |
| `GITLAB_TOKEN` | GitLab |
| `BITBUCKET_USERNAME` + `BITBUCKET_APP_PASSWORD` | Bitbucket |

---

## 憑證管理指令

```bash
# 查看某平台是否有已儲存的憑證
gitmoving auth status github

# 清除憑證（source / destination / default）
gitmoving auth clear github --label source
gitmoving auth clear gitlab --label destination

# 強制重新驗證
gitmoving migrate ... --reauth-src --reauth-dst
```

---

## 完整 CLI 選項

```
gitmoving [COMMAND]

  ui                            啟動互動式 TUI（批次遷移）
  migrate [OPTIONS]             遷移單一 Repo（命令列）
  auth status <provider>        查看已儲存憑證
  auth clear  <provider>        刪除已儲存憑證
```

```
gitmoving migrate [OPTIONS]

  --src-provider, -sp    TEXT    來源平台 [github|gitlab|bitbucket]
  --src-owner,    -so    TEXT    來源擁有者（用戶或組織）
  --src-repo,     -sr    TEXT    來源 Repo 名稱
  --dst-provider, -dp    TEXT    目標平台 [github|gitlab|bitbucket]
  --dst-owner,    -do    TEXT    目標擁有者（預設：登入帳號）
  --dst-repo,     -dr    TEXT    目標 Repo 名稱（預設：同來源）
  --src-base-url         TEXT    來源自架 API URL
  --dst-base-url         TEXT    目標自架 API URL
  --force, -f                   強制推送（覆蓋目標現有 refs）
  --no-create                   目標不存在時直接報錯，不自動建立
  --reauth-src                  強制重新驗證來源
  --reauth-dst                  強制重新驗證目標
  --verbose, -v                 顯示詳細 git 指令輸出
```

---

## 保留內容 vs 不保留內容

| 項目 | 狀態 |
|------|------|
| 所有 branches | ✅ 保留 |
| 所有 tags | ✅ 保留 |
| 完整 commit 歷史（author、時間）| ✅ 保留 |
| Repo 設定為 Private | ✅ 強制 |
| Issues / Pull Requests | ❌ 不遷移（需平台內建工具） |
| Wiki | ❌ 不遷移 |
| Team / 成員權限 | ❌ 由人工後續設定 |
| Webhooks / CI 設定 | ❌ 由人工後續設定 |

---

## 安全說明

- 憑證存儲在作業系統 Keyring，**不寫入磁碟明文**。
- Clone URL 中的 token 僅存在記憶體內，不落地。
- 遷移完成後的臨時目錄（mirror bare clone）會自動刪除。
- 目標 Repo **一律建立為 Private**，不受來源設定影響。

---

## 後續人工作業清單

遷移完成後，請手動處理以下項目：

- [ ] 將團隊成員加入目標 Repo 並設定適當角色
- [ ] 更新 CI/CD Pipeline（Actions / GitLab CI / Bitbucket Pipelines）
- [ ] 更新 Webhooks 設定
- [ ] 更新本地開發者的 remote URL：`git remote set-url origin <new-url>`
- [ ] 確認 Branch Protection Rules
- [ ] 歸檔或封存來源 Repo（視需求）
