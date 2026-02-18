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
│   ├── cli.py              # CLI 進入點 (click)
│   ├── auth/
│   │   ├── base.py         # 憑證基底類別 + keyring 儲存
│   │   ├── github.py       # GitHub PAT 驗證
│   │   ├── gitlab.py       # GitLab PAT 驗證
│   │   └── bitbucket.py    # Bitbucket App Password 驗證
│   ├── providers/
│   │   ├── base.py         # BaseProvider 抽象介面
│   │   ├── github.py       # GitHub API 操作 (PyGithub)
│   │   ├── gitlab.py       # GitLab API 操作 (python-gitlab)
│   │   └── bitbucket.py    # Bitbucket API 操作 (requests)
│   ├── migrator/
│   │   └── engine.py       # 遷移流程核心 (clone → create → push)
│   └── utils/
│       └── git.py          # git 指令包裝層
├── requirements.txt
└── setup.py
```

### 遷移流程

```
[使用者]
   │
   ▼
CLI (gitmoving migrate ...)
   │
   ├─ 1. 驗證來源平台憑證
   ├─ 2. 驗證目標平台憑證
   ├─ 3. 取得來源 Repo 資訊
   ├─ 4. 在目標平台建立 Private Repo（若不存在）
   ├─ 5. git clone --mirror  (完整複製所有 branch / tag / commit)
   ├─ 6. git push --mirror   (推送到目標，保留所有歷史)
   └─ 7. 完成！（權限設定由人工後續處理）
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
