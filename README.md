# 枯山水 (Karesansui)

Ternary Bonsai Multi-Agent System — A local async multi-agent AI environment powered by 1.58-bit efficient models running natively on Apple Silicon via Metal GPU.

---

## アーキテクチャ概要 (Architecture Overview)

```
[Browser UI] → [Next.js Frontend]
                      ↓
             [FastAPI Backend (Docker)]
              ↓           ↓          ↓
         [PostgreSQL]  [Redis]  [Celery Workers (Docker)]
                                      ↓
                        [Host Inference API (Metal / MLX)]
```

- **推論エンジン (Inference Engine):** Mac ホスト OS ネイティブで動作。コンテナからは `host.docker.internal` 経由でアクセス。
- **バックエンド・UI・DB:** Docker コンテナ上で動作。

---

## 前提条件 (Prerequisites)

- macOS (Apple Silicon推奨)
- Docker Desktop (または OrbStack)
- Python 3.11+ (ホスト側推論エンジン用)

---

## ステップ 1: ホスト側推論エンジンのセットアップ (Host Inference Engine Setup)

コンテナの外、**Mac ホスト OS** で以下を実行してください。

### 1-1. MLX サーバーのインストール

```bash
pip install mlx-lm
```

### 1-2. 推論サーバーの起動

```bash
python3 -m mlx_lm server --model prism-ml/Ternary-Bonsai-8B-mlx-2bit --port 8000
```

起動後、`http://localhost:8000/v1` で OpenAI 互換 API が利用可能になります。  
コンテナからは `http://host.docker.internal:8000/v1` でアクセスします。

> **注意:** サーバーを停止すると推論が止まります。Karesansui のコンテナ起動前に必ずサーバーを起動しておいてください。

### 1-3. ホスト側疎通確認 (Host-side Reachability Check)

推論サーバーを起動したら、ホスト側から接続できることを確認してください。

```bash
curl -s http://localhost:8000/v1/models | head -c 300
```

`{"object":"list","data":[...]}` 形式の JSON が返れば OK です。  
コンテナ (backend/worker) 側からの疎通確認はドッカーサービス起動後にステップ 3-C で行います。

---

## ステップ 2: 環境変数の設定 (Environment Variables)

```bash
cp .env.example .env
```

`.env` を開き、必要な値（GitHub Token、DB パスワード等）を設定してください。  
`.env` は `.gitignore` により Git 管理対象外です。絶対にコミットしないでください。

---

## ステップ 3: Karesansui コンテナの起動 (Boot Karesansui)

```bash
# Build and start all services (DB, Redis, Backend)
docker compose up --build -d
```

サービスの状態確認:
```bash
docker compose ps
```

ログの確認:
```bash
docker compose logs -f backend
```

---

## ステップ 3-B: フロントエンドの起動 (Frontend)

> **重要:** `frontend/package.json` の `prestart` フックが `next build` を自動実行します。`API_BASE_URL` (ビルド時に `next.config.js` の `rewrites()` 先として評価) は **`npm run start` と同時に設定する必要があります**。先に `npm run build` を実行しても `npm run start` 時に再ビルドされるため、必ず以下のいずれかの方法で起動してください。

```bash
cd frontend

# Install dependencies (初回のみ)
npm install

# Build & Start — prestart フックが API_BASE_URL 付きで next build を自動実行
API_BASE_URL=http://localhost:8001 npm run start
```

`.env.local` を使う場合は先に設定してから `npm run start` のみ実行します:
```bash
echo 'API_BASE_URL=http://localhost:8001' > frontend/.env.local
cd frontend && npm run start
```

フロントエンドは `http://localhost:3000` で起動します。

---

## ステップ 3-C: タスク投入前の事前確認 (Pre-submission Checklist)

以下をすべて確認してから `http://localhost:3000/` でタスクを投入してください。

**起動順序チェックリスト:**

| # | 確認内容 | 完了条件 |
|---|---|---|
| 1 | ホスト推論サーバー起動済み (ステップ 1-2) | `curl -s http://localhost:8000/v1/models` が JSON を返す |
| 2 | Docker サービス起動済み (ステップ 3) | `docker compose ps` で `backend`, `worker`, `db`, `redis` が `Up` |
| 3 | フロントエンド起動済み (ステップ 3-B) | `curl -sI http://localhost:3000/` が `HTTP/1.1 200` を返す |
| 4 | コンテナ側疎通確認 OK (本ステップ) | 以下のコマンドが JSON を返す |

**コンテナ (backend) 側から疎通確認:**
```bash
docker compose exec backend python3 -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8000/v1/models', timeout=5).read(300).decode())"
```

**コンテナ (worker) 側から疎通確認:**
```bash
docker compose exec worker python3 -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8000/v1/models', timeout=5).read(300).decode())"
```

いずれも `{"object":"list","data":[...]}` 形式の JSON が返れば OK です。

**障害シグネチャ (Failure Signatures):**

| 確認場所 | 出力 | 原因 | 対処 |
|---|---|---|---|
| ホスト `curl` | `curl: (7) Failed to connect to localhost port 8000` | ホスト推論プロセスが停止 | ステップ 1-2 のコマンドで再起動 |
| コンテナ `python3` | `OSError: [Errno 101] Network is unreachable` | `host.docker.internal` ルーティング不可 | Docker Desktop の設定確認、`docker-compose.yml` の `extra_hosts` 確認 |
| コンテナ `python3` | `urllib.error.URLError: <urlopen error [Errno 61] Connection refused>` | コンテナから `host.docker.internal` は到達できるがホスト推論プロセスが停止 | ステップ 1-2 のコマンドで再起動 |
| コンテナ `python3` | `urllib.error.HTTPError: HTTP Error 4xx / 5xx` またはレスポンスが JSON 以外 | 推論サーバーは起動中だがモデル未ロードまたは API エラー（application-layer 障害） | 推論サーバーのログを確認し、モデルが正常にロードされているかを検証 |
| コンテナ `python3` | `{"object":"list","data":[...]}` | **正常** | タスク投入可 |

> **上記確認をスキップしてタスクを投入すると**、ワーカーは `error_type=connectivity` タグ付きの `pipeline_failed_<run_id>` 履歴レコードを書き込み、タスクは Planner 段階で停止します。  
> Workers ページの診断パネルおよびダッシュボードのバナーでも推論バックエンドの到達可否を確認できます。

---

## ステップ 4: アクセス (Access)

| サービス | URL | 備考 |
|---|---|---|
| バックエンド API (FastAPI Docs) | http://localhost:8001/docs | Phase 1 Step 2 〜 |
| バックエンド ヘルスチェック | http://localhost:8001/health | Phase 1 Step 2 〜 |
| 推論エンジン (ホスト) | http://localhost:8000/v1 | ホスト側サーバー |
| フロントエンド (管理コンソール) | http://localhost:3000 | Phase 6 〜 |

---

## 環境のクリーンアップ (Cleanup)

```bash
# Stop and remove containers, networks, volumes
docker compose down -v
```

---

## ディレクトリ構成 (Directory Structure)

```
Karesansui/
├── backend/              # FastAPI application
│   ├── app/
│   │   ├── routers/      # API route handlers
│   │   ├── services/     # Document processing, vector store, GitHub sync
│   │   ├── llm/          # Inference client, structured output
│   │   └── orchestrator/ # DAG parser, manager, debate controller
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/             # Next.js management console
│   └── package.json
├── docs/
│   ├── requirement_specification.md
│   └── implementation_guide.md
├── .env.example          # Environment variable template
├── docker-compose.yml    # Container orchestration
├── .gitignore
└── .dockerignore
```

---

## セキュリティ注意事項 (Security Notes)

- `.env` ファイルは **絶対に** Git にコミットしないこと
- `review.md` および `.history/` フォルダも除外対象
- GitHub Token 等のクレデンシャルは環境変数経由でのみ注入すること

