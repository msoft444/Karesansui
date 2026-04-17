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

---

## ステップ 2: 環境変数の設定 (Environment Variables)

> **Note (Phase 1 Step 2):** `.env.example` および `docker-compose.yml` は Phase 1 Step 2 で追加されます。現時点では以下の手順は実行できません。追加後に実施してください。

```bash
cp .env.example .env
```

`.env` を開き、必要な値（GitHub Token、DB パスワード等）を設定してください。  
`.env` は `.gitignore` により Git 管理対象外です。絶対にコミットしないでください。

---

## ステップ 3: Karesansui コンテナの起動 (Boot Karesansui)

> **Note (Phase 1 Step 2):** `docker-compose.yml` および `backend/Dockerfile` は Phase 1 Step 2 で追加されます。現時点では以下の手順は実行できません。

```bash
# Build and start all services (DB, Redis, Backend, Frontend)
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

## ステップ 4: アクセス (Access)

> **Note (Phase 1 Step 2):** 各サービスは Phase 1 Step 2 のコンテナ構成追加後に利用可能になります。

| サービス | URL |
|---|---|
| フロントエンド (管理コンソール) | http://localhost:3000 |
| バックエンド API (FastAPI Docs) | http://localhost:8001/docs |
| 推論エンジン (ホスト) | http://localhost:8000/v1 |

---

## 環境のクリーンアップ (Cleanup)

> **Note (Phase 1 Step 2):** `docker-compose.yml` は Phase 1 Step 2 で追加されます。現時点では以下のコマンドは実行できません。

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
├── .env.example          # Environment variable template (added in Phase 1 Step 2)
├── docker-compose.yml    # Container orchestration (added in Phase 1 Step 2)
├── .gitignore
└── .dockerignore
```

---

## セキュリティ注意事項 (Security Notes)

- `.env` ファイルは **絶対に** Git にコミットしないこと
- `review.md` および `.history/` フォルダも除外対象
- GitHub Token 等のクレデンシャルは環境変数経由でのみ注入すること

