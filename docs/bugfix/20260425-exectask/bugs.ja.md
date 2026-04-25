# バグ報告: exectask (2026-04-25)

## 症状
- 実行履歴画面から新しいタスクを送信すると `run_id` は返るが、実行履歴には一切レコードが表示されず、Live Trace も空のままになる。
- 1回タスクを送信した後、現在配信されているフロントエンドでは有効な「新規実行」入力欄が表示されなくなり、同じ画面から2回目以降のタスクを開始できない。
- バックエンドの worker は実際にはオーケストレーションタスクを処理しているのに、利用者向けの Worker Management 画面が空のままになる場合がある。

## 再現手順
1. `docker-compose.yml` に基づいて `db`、`redis`、`backend`、`worker` を起動する。ただし、ホスト推論 API の `http://host.docker.internal:8000/v1` には到達できない状態にしておく。
2. 現在配信されている Next.js の本番ビルドで `http://localhost:3000/` を開く。
3. 新しいタスクを送信する。バックエンドは `202 Accepted` を返し、`run_id` を返却する。
4. 直後にその `run_id` に対するバックエンド API を確認する。`GET /history?run_id=<run_id>` は `[]` を返し、`GET /stream/progress?run_id=<run_id>` は `History` 行がまだ存在しないためイベントを返さない。
5. worker / backend の実行状態を確認する。`GET /workers/` ではオーケストレーションタスクが active と表示される一方、worker ログには `InstructorRetryException(APIConnectionError('Connection error.'))` が出ており、backend コンテナから `http://host.docker.internal:8000/v1/models` へ接続すると `URLError: [Errno 101] Network is unreachable` になる。
6. 実行中のフロントエンドと checkout 済みソースを比較する。`frontend/src/app/page.tsx` には `新しいクエリを実行` と `クエリ内容` のフォーム文字列が含まれているが、`http://localhost:3000/` で配信される HTML には含まれていない。`frontend/.next/BUILD_ID` は `frontend/src/app/page.tsx` より古く、`next start` が古いビルドを配信していることが分かる。

## 期待される挙動
- 新しく送信された run は、少なくとも 1 件の永続的な `History` レコードをすぐに作成するべきである。これには、queued / planner-started / error のいずれかの状態が含まれ、下流の推論が失敗しても実行履歴と Live Trace で開始済みであることが分かる必要がある。
- Worker Management UI は、既存のポーリング API を通じてアクティブなオーケストレーションタスクの状態を反映するべきである。
- 新規タスク入力フォームは、送信後も表示されたままであるべきで、再ビルドや stale なフロントエンド資産の再読み込みなしに別のタスクを開始できる必要がある。

## 実際の挙動
- `POST /query/` は Celery ジョブを enqueue して `run_id` を返すだけである。`run_orchestration_pipeline` は最初の `History` 書き込みより前に planner の structured inference を実行するため、推論エンドポイントに到達できないと planner が先に失敗して retry し、`run_id` は有効でも永続化された history row は 0 件のままになる。
- 動的解析ではこの失敗経路が確認できた。`GET /workers/` では送信直後に worker が online で orchestration task が active と表示される一方、`GET /history?run_id=<run_id>` は引き続き `[]` を返した。worker ログには `InstructorRetryException(APIConnectionError('Connection error.'))` が繰り返し出ており、backend コンテナから `http://host.docker.internal:8000/v1/models` への直接接続は `URLError: [Errno 101] Network is unreachable` で失敗した。
- 入力 UI が消えるのは、現在配信されているフロントエンド build が checkout 済みソースより古いためである。`frontend/src/app/page.tsx` の現行ソースには新規タスクフォームが常に含まれているが、`http://localhost:3000/` で配信されている HTML には旧来の実行履歴ビュー（`実行履歴`、`読み込み中...`）しかなく、フォームのラベル（`新しいクエリを実行`、`クエリ内容`）は存在しない。この stale build により、backend の `/workers/` エンドポイントが active task を返していても、ブラウザ上では worker の動きが見えないように見える。

## 影響ファイル
- `backend/app/routers/query.py` — リクエストを受け付けて `run_id` を返すが、永続的な history が書かれる前にレスポンスを返す。
- `backend/app/tasks.py` — `run_orchestration_pipeline` は最初の `History` レコードを出力する前に planner LLM を呼び出す。
- `backend/app/orchestrator/manager.py` — 最初の history 永続化 (`_persist_planner_dag`) は planner の生成が成功した後にしか実行されないため、初期失敗が実行履歴や Live Trace に見えない。
- `backend/app/llm/structured_output.py` と `backend/app/llm/inference_client.py` — orchestration はホスト側 inference API に依存しており、そのエンドポイントに到達できないと即座に失敗する。
- `docker-compose.yml` — `backend` と `worker` は既定で `INFERENCE_API_BASE_URL=http://host.docker.internal:8000/v1` を使用する。
- `frontend/src/app/page.tsx` — 現行ソースでは新規タスクフォームが表示され続けるが、production で配信されているページの内容とは一致していない。
- `frontend/package.json` と `frontend/.next/BUILD_ID` — `next start` は既存の `.next` 出力を配信しており、現在の build は checkout 済みソースより古い。
