# 修正計画: detailedquery (2026-04-28) — 改訂版（7ステップ）

## Step 1: RoleTemplate を権威あるソースとして実行時に解決する

### Target
- `backend/app/orchestrator/manager.py`
- `backend/app/orchestrator/debate_controller.py`
- `backend/app/services/role_templates.py` のような新規 helper

### Req
- DB の `RoleTemplate` をロールプロンプト、デフォルトツール、デフォルトパラメータの権威あるソースとして扱うこと。
- 推論呼び出し前に `system_prompt`、`default_params`、Planner が与えた `dynamic_params` をマージして実行時プロンプトを組み立てること。
- Planner が未知のテンプレートを参照した場合は明示的に失敗を記録し、黙って汎用プロンプトへフォールバックしないこと。
- 履歴に実際に使用されたテンプレートとパラメータが追跡できるように十分なランタイムメタデータを保存すること。

### Constrain
- 追加のランタイムフィールドが真に必要でない限り Planner の DAG スキーマは変更しないこと。
- orchestrator 側へプロンプト文を重複ハードコードしないこと。

## Step 2: 単一の runtime tool-dispatch 契約を導入する

### Target
- `backend/app/services/tool_dispatch.py` のような新規 helper
- `backend/app/orchestrator/manager.py`
- `backend/app/orchestrator/debate_controller.py`

### Req
- テンプレートの `tools` 宣言を、能力検出、呼び出し、出力正規化、エラー分類、リトライ等を担う単一の dispatch 層で実装すること。
- dispatch 層はシリアライズ可能でプロンプトへ安全に挿入できる安定した `ToolResult` 形を提供すること。
- 利用可能だったツール、実際に実行したツール、スキップまたは失敗したツールを記録し、診断情報をランに残すこと。
- 未実装のツールをテンプレートが宣言している場合は、黙って無視せず明示的に失敗を返すこと。

### Constrain
- ツール固有ロジックを orchestrator の複数箇所へ散らさないこと。共有 helper を使うこと。
- ツール出力はサイズ制限と決定性を持たせ、プロンプト肥大化を避けること。

## Step 3: DuckDuckGo を `web_search` プロバイダとして実装する

### Target
- `backend/app/services/web_search.py`
- 必要なら `backend/requirements.txt` の小さな HTTP ヘルパー
- Step 2 の dispatch 層への組み込み

### Req
- DuckDuckGo 結果を決定的かつコンパクトに正規化し、プロンプト注入と軽量な履歴保存を可能にすること。
- 曖昧名称に対する disambiguation クエリをサポートし、合成前に対象が特定できること。
- プロバイダ到達不能、0件、想定外レスポンスを区別する診断情報を提供すること。
- タイムアウトや件数上限、ペイロードキャップを設けること。

### Constrain
- ブラウザ自動化や他プロバイダ導入はこの修正で行わないこと。
- 自動テストでのモック化が容易な実装にすること。

## Step 4: 詳細レポート要求向けの Planner 分解を強化する

### Target
- `backend/app/tasks.py`
- Planner のデフォルト振る舞いを定めるプロンプトや seed

### Req
- ユーザーが「詳細レポート」を要求した場合、Planner が調査（research）・分析・必要ならレビュー・最終統合の多段 DAG を優先するようプロンプトを調整すること。
- Web 根拠や曖昧性解消が必要な場合は、最終統合前に明示的な調査タスクを含めること。
- Step 1–3 の runtime 契約が満たされる場合にのみ、tool-capable な調査ロールを割り当てること。

### Constrain
- 既存の DAG JSON 契約とロール名の互換性を維持すること。
- すべてのクエリで大型 DAG を強制しないこと。

## Step 5: リッチな出力契約とタスク単位の response-model 戦略を導入する

### Target
- `backend/app/schemas.py`
- `backend/app/tasks.py`
- `backend/app/services/history_runs.py`
- 必要なら `frontend/src/app/history/[run_id]/page.tsx`

### Req
- `DetailedReportResponse` のようなリッチモデルを導入し、複数セクション、所見、証拠メモ、引用、不確実性を表現できるようにすること。
- タスク単位で `response_model_class_path` を選べるようにし、調査/統合タスクはリッチスキーマを使い、簡易タスクは軽量スキーマを使えるようにすること。
- 互換ルールを定めること: タスク単位のスキーマがない場合は `GlobalSettings.response_model_class_path` を使い、なければ従来の `ReportSynthesizerResponse` をフォールバックとする。
- 調査タスクで得た証拠は保持して最終 synthesizer が引用や要約へ使えるようにすること。

### Constrain
- DB 上は可能な限り既存 JSONB カラムを流用することで破壊的なスキーマ migration を避けること。
- 旧履歴との互換性を保持すること。

## Step 6: 根拠付けと深度について回帰検証を追加する

### Target
- `backend/tests/`（単体・統合の焦点テスト）
- run-detail 描画の最小限の frontend 検証
- 曖昧クエリに対する手動検証フロー（例: `Takenoko no Sato`）

### Req
- `RoleTemplate` が実行時に解決され、汎用プロンプトへ静かにフォールバックしていないことを示す回帰テスト。
- 未実装ツールがテンプレートで宣言されている場合、dispatch 層で明示的に失敗することを示すテスト。
- `web_search` が DuckDuckGo に対して呼ばれ、正規化された証拠がタスクコンテキストへ投入されることをテスト（モック使用）。
- 曖昧クエリで意図した対象へ根拠付きで回答することを手動検証で確認すること。

### Constrain
- CI ではライブ DuckDuckGo ではなく決定的なモックを使うこと。

## Step 7: マイグレーション、段階的ロールアウトと監視の指針

### Target
- 監査スクリプトや（必要なら） alembic revision
- `backend/app/services/tool_dispatch.py` と `backend/app/services/role_templates.py` での実行時警告・メトリクス
- 運用向け手順書

### Req
- Seed で入った `RoleTemplate` のうち未実装ツールを宣言しているものを検出する監査スクリプトを提供する（自動書換は行わない）。
- 新しい dispatch を段階的に有効化するための feature-flag を用意し、小さな割合からロールアウトして観察する手順を用意する。
- 監視対象メトリクス: ツール呼び出し数、ツール失敗の分類、タスク単位リッチスキーマ使用率、テンプレート欠落によるラン失敗割合。
- ロールアウト手順書: 監査実行 → 少数割合で有効化 → メトリクス監視 → 問題なければ拡大。

### Constrain
- 破壊的なデータ変更は避け、運用者監査を優先すること。
- ロールアウトは可逆で観察可能にすること。

---

手順の順序は上記の通りです。Step 1–3 が整わない限り Step 5（タスク単位のリッチスキーマ）は有効化しないでください。Step 7 は安全な段階的展開と監査のために必須です。