# 機能実装計画 — 2026-04-28 Query Result Details

feature 実行コマンドを受けた場合は、以下の各 Step を strict prompt として解釈し、その Step のみを実装すること。

## Step 1: run 単位 read model と決定的な集約ルールを定義する

### 対象
- `backend/app/schemas.py`
- `backend/app/services/history_runs.py` のような新規 read-model helper

### 要件
- run 単位の履歴サマリーと run 単位の履歴詳細 payload に対する明示的な response model を定義すること。
- 生の `History` row を、`run_id` をキーとしたユーザー向け Query Run へ変換する、決定的な集約レイヤを定義すること。
- 永続化済みの履歴データから、frontend のタイミング前提に依存せず、少なくとも以下を導出できるようにすること。
  - run status
  - 最終クエリ結果プレビュー
  - 最終クエリ結果 payload
  - 順序付きの Display Task 一覧
- Planner DAG トポロジが利用できる場合、それをタスク順序およびタスク所属判定の主ソースとして使うこと。
- Planner トポロジ保存 row 自体はユーザー向けタスク一覧から除外しつつ、DAG 再構築とタスク順序決定には利用すること。
- 同一 Display Task に属する内部生 row は、対応する Planner `task_id` 配下へ集約すること。
- Debate task については、`progress.parent_task_id` のような永続化済みメタデータを使って、ラウンド単位の生 row を同一トップレベル Display Task 配下に集約すること。必要な場合のみ、決定的な `task_id` parsing をフォールバックとして使うこと。

### 制約
- 既存 orchestration の write path を変更するより、加算的な read-model layer を優先すること。
- 現在の `History` payload で決定的な集約が不可能だと証明されない限り、schema migration や新しい table は追加しないこと。
- task 単位 row に依存する既存の raw history consumer との互換性は維持すること。

## Step 2: raw history API を壊さずに run summary / run detail API を追加する

### 対象
- `backend/app/routers/history.py`
- router 登録変更が必要な場合は `backend/app/main.py`

### 要件
- 実行履歴一覧向けに、Query Run ごとに 1 件を返す run summary endpoint を追加すること。例: `GET /history/runs`。
- 1 件の Query Run の完全な詳細 payload を返す run detail endpoint を追加すること。例: `GET /history/runs/{run_id}`。
- run detail payload には、少なくとも以下を含めること。
  - `run_id`
  - run status
  - 最終クエリ結果 payload
  - 最終結果プレビューまたは要約
  - 順序付き Display Task 一覧
  - 同一 run の DAG トポロジ
- 詳細画面向けに、not-found、empty、running、completed、failed の各状態を安定して返せるようにすること。
- Live Trace や、なお raw task row で動作する既存画面のために、既存の raw history endpoint はそのまま利用可能に保つこと。

### 制約
- 既存の task 単位 consumer を壊すような形で `GET /history` を置き換えたり、暗黙に別用途へ転用したりしないこと。
- 新しい endpoint は加算的に追加し、現在の frontend から見て後方互換に保つこと。
- run 集約の責務を frontend 側へ移さないこと。

## Step 3: ダッシュボードの実行履歴を Query Run 単位へ再設計する

### 対象
- `frontend/src/app/page.tsx`

### 要件
- ダッシュボード上の現在の raw task history list を、新しい run summary API を使う run 単位の履歴一覧へ置き換えること。
- 生の task 実行 row 単位ではなく、Query Run ごとに 1 件のトップレベル履歴項目を表示すること。
- 各 run について、少なくとも以下のサマリー項目を表示すること。
  - `run_id`
  - 実行日時
  - run status
  - 最終結果プレビュー
- 各 run 項目はクリック可能とし、選択した `run_id` の専用クエリ結果詳細画面へ遷移させること。
- クエリ送信後の成功表示は、返却された `run_id` の詳細画面へ遷移する導線を主経路に更新すること。
- 既存の query submission form と diagnostics banner の挙動は維持すること。

### 制約
- UI 文言はすべて日本語とすること。
- 現在のクエリ送信フローを壊したり、live trace へのアクセスを消したりしないこと。詳細画面は主たる確認経路にするが、既存 route 全体を置き換えるものではない。
- queued、running、completed、failed のいずれの状態でも、ダッシュボードの可読性を維持すること。

## Step 4: 最終結果、タスク詳細展開、DAG を統合した専用詳細画面を構築する

### 対象
- 新規 `frontend/src/app/history/[run_id]/page.tsx`
- 必要に応じた result panel や task drill-down 用の新規 UI component
- 詳細画面で再利用のために拡張が必要であれば `frontend/src/components/DagVisualizer.tsx`

### 要件
- `run_id` で参照される専用詳細画面を作成すること。
- 新しい backend endpoint から run detail payload を取得し、同一画面内に以下 3 セクションを描画すること。
  - 最終クエリ結果
  - 実行タスク一覧
  - DAG
- 最終クエリ結果は、生 row の dump ではなく、その run に対する canonical なユーザー向け出力として描画すること。
- 実行タスク一覧は、backend 集約レイヤが返す Display Task collection を使って描画すること。
- 画面初期表示では、すべてのタスク詳細パネルを閉じた状態にすること。
- 各タスクは個別に展開・折りたたみできるようにすること。
- 展開後の各タスクには、task metadata、利用可能な planner-assigned parameter、execution status、利用可能な runtime metadata、execution result payload を表示すること。
- Debate task については、集約済みの top-level debate result を主結果として表示し、内部の per-round row は同じ task detail 領域内に保持すること。
- DAG は同一 run detail payload から描画し、task list と graph が同じ run と同じ task set を表すようにすること。

### 制約
- 実用上可能なら、既存の DAG 可視化ロジックを再利用し、別の DAG 描画経路を新設しないこと。
- Planner トポロジ row はユーザー向け task list から隠すこと。
- loading、empty、not-found、error の状態を明確に定義し、小さい viewport でも使えるレイアウトを維持すること。

## Step 5: run summary と detail drill-down の重点回帰確認を追加する

### 対象
- run 集約と history endpoint に対する focused backend test
- dashboard から detail への遷移、および task の展開・折りたたみに対する focused frontend verification

### 要件
- 少なくとも以下を含む run-oriented aggregation rule に対する backend 回帰カバレッジを追加すること。
  - `run_id` ごとに 1 件の summary item が生成されること
  - 最終結果の選択が決定的であること
  - Planner topology row が Display Task list から除外されること
  - Debate の内部 row が対応する top-level task 配下へ集約されること
- dashboard が raw task row ではなく run summary を描画することを確認する focused verification を追加すること。
- run をクリックすると、同じ `run_id` の detail 画面が開くことを確認する focused verification を追加すること。
- 初期表示で全 task detail が閉じており、個別に展開できることを確認する focused verification を追加すること。
- 既存 history に保存される lifecycle state を跨いで新しい read model が動作するよう、completed、running、failed の各 run 状態を確認すること。

### 制約
- live な推論バックエンドを必要とする広範な end-to-end suite ではなく、狭い回帰テストと対象限定 UI check を優先すること。
- 同じ保存データを再利用する既存 raw history consumer について、互換性確認も維持すること。
- この Step を、無関係な orchestration 変更、live trace 全面改修、一般的な dashboard restyling に拡張しないこと。