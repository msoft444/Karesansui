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

# 修正計画 phase 2: Planner 接続失敗の修正 (2026-04-25)

## Step 1: ホスト推論バックエンドの単一ランタイム契約を確立する

### 対象
- `docker-compose.yml`
- `backend/app/llm/structured_output.py`
- `backend/app/llm/inference_client.py`
- `README.md`

### 要件
- `backend` と `worker` の両方が使うホスト側推論バックエンドについて、期待される base URL、health-check パス、およびこのリポジトリがサポートする正確なローカル起動手順を含む、単一の権威あるランタイム契約を定義すること。
- structured inference と non-structured inference の入り口で設定や分類ルールがずれないようにし、両方のコード経路が同じ URL ソースと同じ規則で connectivity、timeout、API-status failure を扱うようにすること。
- `README.md` に運用者向けの起動および確認フローを明記すること。これには、推論サーバを起動する正確なホストコマンドと、タスク送信前に到達性を確認するためのホスト側およびコンテナ側コマンドを含めること。
- 永続化されるエラーテキストとログテキストは、history 利用側、回帰テスト、UI の状態分類が connectivity failure と schema/orchestration failure を区別できる程度に安定した形式を維持すること。

### 制約
- 環境変数ベースの設定を維持し、ユーザーが明示的に上書きしない限り、文書化された既定のローカルアドレスは `http://host.docker.internal:8000/v1` のままにすること。
- マシン依存の fallback アドレス、ホスト名、秘密情報をアプリケーションコードにハードコードしないこと。
- ホスト推論のセットアップ手順は `README.md` に、ランタイム診断は backend に置き、無関係なファイルへ前提条件を分散させないこと。

## Step 2: Planner 境界でバックエンド不達を検知し、決定的な失敗ライフサイクルを永続化する

### 対象
- `backend/app/tasks.py`
- `backend/app/routers/query.py`
- 推論バックエンド readiness check 用に導入する共有ヘルパーがあればそのファイル

### 要件
- worker コンテナから推論バックエンドへ到達できないとき、run が不透明な retry に埋もれないように、Planner 境界で安価かつ決定的な readiness check、または同等の first-failure classification を追加すること。
- 受理済み run の既存ライフサイクルは維持すること。`bootstrap_<run_id>` は送信アンカーとして残し、`planner_started_<run_id>` は Planner 実行開始を示し、Planner の connectivity failure 時には終端の `pipeline_failed_<run_id>` を 1 件だけ書くこと。
- 終端の Planner failure payload には、失敗が preflight reachability check 中に起きたのか、最初の structured Planner request 中に起きたのかを明確に残しつつ、既存の history 利用側が使っている `run_id` と role の意味論は維持すること。
- Celery が同じ Planner task を retry しても終端 failure row が重複しないようにし、推論バックエンドに到達できる場合の success path は変更しないこと。

### 制約
- HTTP submission endpoint を Planner 全体の完了や下流 orchestration の完了まで待たせないこと。
- 現在の `History.result` payload で必要な Planner ライフサイクル状態を表現できるなら、新しいテーブルやスキーマ migration は導入しないこと。
- インフラ障害を成功送信として扱わず、retry が尽きた後の最終 failure state を黙って消さないこと。

## Step 3: 管理 UI に推論バックエンド readiness と Planner 接続失敗を可視化する

### 対象
- `backend/app/routers/workers.py`、または必要なら新しい backend 診断 API
- `frontend/src/app/page.tsx`
- `frontend/src/app/workers/page.tsx`
- `frontend/src/components/LiveTrace.tsx`

### 要件
- frontend がホスト推論サーバへ直接 probe しなくても、コンテナ化されたランタイムから見た推論バックエンドの到達性を表示できるだけの backend 診断情報を公開すること。
- task 実行が推論バックエンド不達で止まっている場合、dashboard および/または workers 画面に明確な日本語 UI 状態を表示し、ユーザーがインフラ障害と idle worker や空の history list を区別できるようにすること。
- Live Trace と execution history は、永続化された Planner ライフサイクル row を、`planner-failed` / `connectivity` が対処可能な失敗として読める形で表示し、空白や停止に見えないようにすること。
- バックエンドが正常なときの通常タスク進行表示は維持し、追加した診断表示が成功 run の可読性を損なわないようにすること。

### 制約
- 診断のために不可欠でない限り、既存のユーザー向け route は維持すること。
- UI 文言はすべて日本語とし、ブラウザ側の挙動は現在の polling/SSE モデルと互換性を保つこと。
- failure の本質は container-to-host reachability にあるため、frontend を browser-to-host-network の直接接続に依存させないこと。

## Step 4: サポート対象のローカル起動経路をタスク送信前に検証可能にする

### 対象
- `README.md`
- frontend/backend スタック起動に使われている既存のローカル起動ヘルパーまたは task 定義
- `docs/bugfix/20260425-exectask/` 配下の関連ランタイム文書

### 要件
- サポート対象ローカル環境向けに、送信前チェック手順を明示すること。ホスト推論サーバを起動し、ホスト側の `/v1/models` を確認し、`host.docker.internal` へのコンテナ側到達性を確認し、その後にタスクを送信する流れを定義すること。
- ホスト側サーバが落ちている場合と、コンテナがホストへ到達できない場合で、どの失敗シグネチャが出るかを文書化し、missing process、network routing problem、application-layer error を運用者が切り分けられるようにすること。
- 文書上の起動順序を、実際のランタイム依存順に合わせること。すなわち、最初にホスト推論バックエンド、次に Docker services、最後に frontend からのタスク送信とすること。
- 文書化された前提条件を `docker-compose.yml` および backend inference clients の実際の仮定と同期させること。

### 制約
- ホスト推論のセットアップを Dockerfile、container entrypoint、アプリケーション起動ロジックへ移さないこと。要件どおり、ホスト側サービスは明示的な外部前提として維持すること。
- ローカルマシンごとにソースファイルを手修正しないで済むようにし、文書化された手順は環境変数とサポート済み起動コマンドに依存させること。
- 手順は `dc` 検証時の運用チェックリストとして使える程度に簡潔に保つこと。

## Step 5: Planner 接続失敗と復旧に対する重点回帰検証を追加する

### 対象
- `backend/tests/test_query_lifecycle.py`
- 推論バックエンド readiness helper 向けに追加する狭い backend test module があればそのファイル
- `POST /query/`、`GET /history`、`GET /workers/`、Live Trace に対する重点手動検証手順

### 要件
- 推論バックエンドが到達不能な場合に、1つの run について `bootstrap`、`planner_started`、終端の `pipeline_failed` row が可視化され、`status=planner-failed` と `error_type=connectivity` を持つことを示す回帰カバレッジを追加すること。
- 同じコード経路で retry を跨いでも終端 failure row が重複しないこと、さらに readiness check が成功した場合には success path を壊さないことを示す重点チェックを追加すること。
- サポート対象ローカル契約から開始する手動検証シーケンスを追加し、まず Planner connectivity failure を再現し、その後 backend reachability を復旧させて、新しい task が Planner を越えて進行することを確認すること。
- このバグで影響を受ける 3 つの利用者可視面、すなわち execution history、Live Trace、worker/diagnostic visibility を明示的に検証対象に含めること。

### 制約
- 実際の外部推論エンジンに依存する広範なスイートよりも、決定的なモックまたは狭い integration test を優先すること。
- 手動検証は現在の macOS + Docker 環境で再現可能であり、Planner connectivity scenario に範囲を限定すること。
- 回帰計画を、無関係な DAG 機能、knowledge-base ingestion flow、一般的な frontend polish にまで拡張しないこと。
