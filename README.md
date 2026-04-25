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

### 1-3. 推論サーバーの疎通確認 (Verifying Reachability)

タスクを投入する前に、以下のコマンドで推論サーバーへの接続を確認してください。

**ホスト側から確認:**
```bash
curl -s http://localhost:8000/v1/models | head -c 300
```

**コンテナ (backend) 側から確認:**
```bash
docker compose exec backend python3 -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8000/v1/models', timeout=5).read(300).decode())"
```

**コンテナ (worker) 側から確認:**
```bash
docker compose exec worker python3 -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8000/v1/models', timeout=5).read(300).decode())"
```

いずれのコマンドも `{"object":"list","data":[...]}` 形式の JSON を返すことを確認してください。  
接続できない場合、ワーカーは `error_type=connectivity` タグ付きの `pipeline_failed_<run_id>` 履歴レコードを書き込み、タスクは Planner 段階で停止します。

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

> **重要:** Next.js の `rewrites()` はビルド時に評価されます。`npm run build` の **前に** `API_BASE_URL` を設定してください。

```bash
cd frontend

# Install dependencies (初回のみ)
npm install

# Build (API_BASE_URL を明示して build)
API_BASE_URL=http://localhost:8001 npm run build

# Start production server
npm run start
```

ローカル開発時は `.env.local` で設定することもできます:
```bash
echo 'API_BASE_URL=http://localhost:8001' > frontend/.env.local
cd frontend && npm run build && npm run start
```

フロントエンドは `http://localhost:3000` で起動します。

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

