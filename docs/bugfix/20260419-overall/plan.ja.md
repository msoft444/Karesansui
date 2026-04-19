# バグフィックス実装計画 — 2026-04-19 総合

バグフィックス実行コマンドを受け取った場合、以下の各Phaseを**厳密なプロンプト**として解釈し、直接修正を適用すること。

---

## Phase 1: ページタイトル・ブランディング・バージョン表示の修正

- **Step 1: メタデータタイトルとサイドバーブランディングの更新**
  - [対象]: `frontend/src/app/layout.tsx`
  - [要件]:
    - `metadata.title` を `"Karesansui"` から `"枯山水 v1.4.1"` に変更する。
    - `metadata.description` のユーザー向けコンテキストで「Karesansui」の代わりに「枯山水」を使用する。
    - サイドバーブランディングヘッダの `"Karesansui"` を `"枯山水"` に変更する。
    - サブラベルを `"Multi-Agent Console"` から `"マルチエージェントコンソール"` に変更する（日本語UIルール）。
    - サイドバーフッタのバージョン文字列を `"v0.1.0"` から `"v1.4.1"` に更新し、`requirement_specification.md` のシステムバージョンと一致させる。
  - [制約]: 言語境界ルールに従い、UIテキストは日本語とすること。

---

## Phase 2: 役割テンプレート管理UIの追加

- **Step 1: バックエンド — 役割テンプレートのモデル、スキーマ、マイグレーション**
  - [対象]: `backend/app/models.py`、`backend/app/schemas.py`、新規Alembicマイグレーション
  - [要件]:
    - `RoleTemplate` テーブルを定義する。カラム: `id`（UUID, PK）、`name`（ユニーク文字列、例: `"Data_Gatherer"`）、`description`（テキスト）、`system_prompt`（テキスト）、`tools`（JSONB、利用可能ツール名リスト）、`default_params`（JSONB、デフォルト動的パラメータ）、`created_at`（タイムスタンプ）、`updated_at`（タイムスタンプ）。
    - 対応するPydantic v2スキーマを作成: `RoleTemplateCreate`、`RoleTemplateUpdate`、`RoleTemplateResponse`。
    - 新テーブル用のAlembicマイグレーションを生成する。
  - [制約]: `requirement_specification.md` §4に定義された初期役割テンプレートをマイグレーションまたは起動フックで投入し、初期状態で利用可能にすること。

- **Step 2: バックエンド — 役割テンプレートCRUD API**
  - [対象]: `backend/app/routers/templates.py`（新規）、`backend/app/main.py`
  - [要件]:
    - 完全なCRUDエンドポイントを持つ新規 `APIRouter` を実装する:
      - `GET /api/templates/` — 全役割テンプレートの一覧取得。
      - `GET /api/templates/{id}` — 単一テンプレートの取得。
      - `POST /api/templates/` — 新規テンプレートの作成。
      - `PUT /api/templates/{id}` — 既存テンプレートの更新。
      - `DELETE /api/templates/{id}` — テンプレートの削除。
    - `main.py` にルーターを登録する。
  - [制約]: 既存ルーターと一貫したDBセッション依存性注入を使用すること。

- **Step 3: フロントエンド — 役割テンプレート管理ページ**
  - [対象]: `frontend/src/app/templates/page.tsx`（新規）、`frontend/src/app/layout.tsx`（ナビゲーション更新）
  - [要件]:
    - 全役割テンプレートをカードまたはテーブルレイアウトで表示する新規 `/templates` ページを作成する。
    - 新規テンプレート追加用の作成フォーム（モーダルまたはインライン）を提供する。
    - 各テンプレートにインライン編集および確認付き削除ボタンを提供する。
    - サイドバー（`layout.tsx`）に「役割テンプレート」ナビゲーション項目を追加する。
    - 既存ページと一貫してSWRでデータ取得を行う。
  - [制約]: 全UIテキストは日本語。APIプロキシパスがワイルドカードでカバーされていない場合は `next.config.js` で設定すること。

---

## Phase 3: エージェントサービス制御・ワーカーステータス管理の追加

- **Step 1: バックエンド — ワーカーステータスおよびタスク制御API**
  - [対象]: 新規 `backend/app/routers/workers.py`、`backend/app/main.py`
  - [要件]:
    - `celery_app.control.inspect()` を使用してアクティブワーカーの一覧（状態、アクティブタスク、統計情報）を返す `GET /api/workers/` エンドポイントを実装する。
    - 全ワーカーにわたる現在アクティブおよび予約済み（キュー内）タスクの一覧を返す `GET /api/workers/tasks/` エンドポイントを実装する。
    - `celery_app.control.revoke(task_id, terminate=True)` を呼び出して実行中またはキュー内のタスクを停止する `POST /api/workers/tasks/{task_id}/revoke` エンドポイントを実装する。
    - `main.py` にルーターを登録する。
  - [制約]: `worker.py` の既存 `celery_app` インスタンスを使用すること。ワーカーがオフラインの場合はエラーではなく空のリストを返すなど、グレースフルに処理すること。

- **Step 2: フロントエンド — ワーカーステータスパネルおよびタスク制御UI**
  - [対象]: 新規 `frontend/src/app/workers/page.tsx`、`frontend/src/app/layout.tsx`（ナビゲーション更新）
  - [要件]:
    - 以下を表示する新規 `/workers` ページを作成する：
      - 各ワーカーの名前、ステータス（オンライン/オフライン）、アクティブタスク数、最終ハートビートを表示するワーカーステータステーブル。
      - タスクID、タスク名、ワーカー割当、状態を表示する実行中/キュー内タスクテーブル。
      - 各実行中/キュー内タスク行に、確認ダイアログ付きの「停止」ボタン（バックエンドにrevoke要求を送信）。
    - サイドバー（`layout.tsx`）に「ワーカー管理」ナビゲーション項目を追加する。
    - リアルタイムステータス更新のため、SWRにポーリング間隔（例: 5秒）を設定する。
  - [制約]: 全UIテキストは日本語。取消アクションは実行前にユーザー確認を必須とすること。

---

## Phase 4: Webコンソールからのタスク実行機能の追加

- **Step 1: バックエンド — クエリ送信エンドポイント**
  - [対象]: `backend/app/routers/stream.py` または新規 `backend/app/routers/query.py`、`backend/app/main.py`
  - [要件]:
    - JSONボディ `{ "query": "<ユーザーテキスト>" }` を受け付ける `POST /api/query/` エンドポイントを実装する。
    - エンドポイントはオーケストレーションパイプラインをトリガーする: Plannerを呼び出し、DAGを生成し、既存の `OrchestratorManager` 経由でタスクをエンキューする。
    - 少なくとも `{ "run_id": "<uuid>" }` を含むレスポンスを返し、フロントエンドがライブトレースまたはDAGビジュアライザにリダイレクトできるようにする。
  - [制約]: 既存の `OrchestratorManager` およびCeleryタスクインフラを再利用すること。オーケストレーションロジックを重複させないこと。

- **Step 2: フロントエンド — クエリ送信UI**
  - [対象]: `frontend/src/app/page.tsx`、新規コンポーネント `frontend/src/components/QueryForm.tsx`（必要に応じて）
  - [要件]:
    - ダッシュボードページ（`/`）の上部に、テキストエリアと「実行」送信ボタンを備えたクエリ入力フォームを追加する。
    - 送信成功時、返却された `run_id` を表示し、`/live?run_id=<id>` へ遷移するリンクを提供する。
    - 送信中のローディング状態と、失敗時のエラーフィードバックを表示する。
  - [制約]: 全UIテキストは日本語。フォームは既存の実行履歴テーブルの上に明確に表示すること。
