# 修正計画 phase 1: exectask の問題の修正 (2026-04-25)

## Step 1: 受理済みの実行を即座に可視化する

### 対象
- `backend/app/routers/query.py`
- `backend/app/tasks.py`
- `backend/app/orchestrator/manager.py`

### 要件
- 受理されたすべての `run_id` について、planner 推論が失敗する前に、少なくとも 1 件の永続的な `History` レコードを保存すること。
- 初期レコードは、その run のライフサイクルの起点を明確に表すこと。例: queued, planner-started, bootstrap-failed。
- 下流の DAG タスクが 1 件も成功しなくても、planner と orchestration の失敗を同じ `run_id` に対して記録すること。
- 既存の `POST /query/` のレスポンス契約は維持し、エンドポイントは `run_id` を伴う `202 Accepted` を即時に返すこと。

### 制約
- 現行の `result` と `progress` の JSON フィールドで必要なライフサイクル状態を表現できるなら、新しいスキーマやマイグレーションは追加しないこと。
- HTTP リクエストを planner 完了、worker 完了、または外部推論呼び出しでブロックしないこと。
- Celery パイプラインが同じ run を再試行した際に、bootstrap レコードが重複しないようにすること。

## Step 2: 早期失敗を履歴とライブトレースに反映する

### 対象
- `backend/app/routers/history.py`
- `backend/app/routers/stream.py`
- `frontend/src/app/page.tsx`
- `frontend/src/components/LiveTrace.tsx`

### 要件
- `GET /history` と `GET /stream/progress` で、送信済み `run_id` に対する queued, planner-started, planner-failed, orchestration-failed の各状態を表示できるようにすること。
- ダッシュボードと Live Trace の描画を更新し、失敗または停止した run が空のまま放置されず、可視なライフサイクルイベントとして表示されるようにすること。
- 新しい bootstrap レコードや失敗レコードと並べて、既存の成功したタスクレコードも読みやすいままにすること。
- UI が「まだ run を送信していない」のか「run は送信されたが、タスク実行が可視化される前に失敗した」のかを区別できるようにすること。

### 制約
- 既存のエンドポイントパスと、現在の frontend 利用者に対する基本的なレスポンス互換性は維持すること。
- UI が既に使っている polling と SSE の挙動以上に、手動リフレッシュを要求しないこと。
- 既存の history row に新しいライフサイクル payload 形式が含まれていなくても動作するよう、描画ロジックは後方互換に保つこと。

## Step 3: 配信中の frontend を checkout 済みソースに一致させる

### 対象
- `frontend/src/app/page.tsx`
- `frontend/src/app/workers/page.tsx`
- `frontend/package.json`
- `next start` で利用される frontend の production build と起動フロー

### 要件
- production build に最新のダッシュボード画面が確実に含まれるようにし、新規タスク送信用フォームも表示されるようにすること。
- 送信後も、新規タスク入力欄が配信中のアプリケーションで表示されたままであることを確認すること。ソースツリー上だけで表示されていてはならない。
- frontend を再ビルドした後、workers 画面が backend の polling エンドポイントを反映することを確認すること。
- checkout 済みソースと `next start` が配信する `.next` 出力の間にある stale build の差を解消すること。

### 制約
- production build や startup workflow を不整合のまま残す UI だけの回避策は実装しないこと。
- 既存のルートと、frontend ソースで定義済みの日本語 UI 文字列は維持すること。
- macOS + Docker の既存開発環境で無理なく使える程度に、ローカル build と startup の流れを簡潔に保つこと。

## Step 4: 推論バックエンドの失敗を無音ではなく診断可能にする

### 対象
- `docker-compose.yml`
- `backend/app/llm/structured_output.py`
- `backend/app/llm/inference_client.py`
- 推論バックエンドの起動方法を定義している runtime ドキュメント

### 要件
- サポート対象のローカル環境で、`backend` と `worker` の両方が到達可能な `INFERENCE_API_BASE_URL` を使っていることを確認すること。
- 推論バックエンドに到達できない場合、その失敗を既存の `run_id` に紐づくユーザー可視の run-level エラーレコードへ変換すること。
- 接続失敗、planner 検証失敗、下流タスク失敗を区別できるだけの診断情報を、ログと永続化された履歴の両方に残すこと。
- この失敗はブラウザから backend への到達性ではなく、コンテナからホストへの到達性が原因であるため、動作確認はコンテナ内部から行うこと。

### 制約
- ローカル環境の文書化済み設定を超える、マシン依存の fallback アドレスはハードコードしないこと。
- 環境変数ベースの設定は維持し、スタックの可搬性を損なわないこと。
- インフラ障害を成功 run として扱ったり、エラー経路を黙殺したりしないこと。

## Step 5: 回帰テストと重点検証を追加する

### 対象
- query 送信と早期 history 可視化に関する backend の回帰テスト
- ダッシュボードと workers 画面に対する frontend の重点確認
- `POST /query/`、`GET /history`、`GET /stream/progress`、worker polling を含む最小限の end-to-end 検証

### 要件
- planner 推論が即座に失敗しても、送信された `run_id` が少なくとも 1 件の可視な history あるいは stream レコードを作成することを示す回帰チェックを追加すること。
- 1 回目の送信後でも、再ビルド済み frontend が新規タスクフォームを表示し続けることを示す確認を追加すること。
- execution history、live trace、worker activity の 3 つの利用者可視面をまたぐ、狭い end-to-end シナリオを再実行すること。
- この bug report には、成功経路だけでなく silent failure 状態も含まれているため、成功経路と early infrastructure-failure 経路の両方を検証すること。

### 制約
- live な外部推論サービスに依存する広範なスイートよりも、狭いテスト、モック、または対象限定のチェックを優先すること。
- 現在の macOS + Docker ローカル環境で再現可能な検証手順にすること。
- orchestration の無関係な機能、knowledge-base のフロー、一般的な frontend リデザインにまで範囲を広げないこと。
