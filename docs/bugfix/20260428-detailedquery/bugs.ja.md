# バグ報告: detailedquery (2026-04-28)

## 症状
- 詳細レポートを要求しても、実際には短い要約と数個の箇条書きしか出ず、十分な内容のレポートにならない。
- 調査系ロールが公開 Web 上の調査を十分に行っているように見えず、そのため出力が薄く、対象を取り違えたハルシネーションが起きる。
- 例として、「たけのこの里」のレポートを依頼すると、明治のチョコレート菓子ではなく、関西の伝統菓子のような内容になることがある。
- 現状では、`Data_Gatherer` などのロールが結果生成前に DuckDuckGo Search を使ったことを示す根拠がない。

## 再現手順
1. backend、worker、database、frontend を含む現在のスタックを起動する。
2. 例えば次のようなクエリを送信する: `Create a detailed report about Meiji's "Takenoko no Sato". Use web search and include concrete findings, supporting evidence, and a structured final report.`
3. 実行完了後、対象の `run_id` の実行詳細画面、または raw の `History` 行を確認する。
4. 最終結果が、証拠・引用・明確な根拠付きの所見を持つ多段のレポートではなく、短い `summary` と数個の `details` に留まっていることを確認する。
5. オーケストレーションの実行経路を確認すると、次が分かる。
   - `RoleTemplate` レコードには `tools=["rag_search", "web_search", "mcp_call"]` が定義されているが、実行時のタスク処理ではそのテンプレートを読み込んで適用していない。
   - backend の runtime を検索しても、`web_search`、`rag_search`、`mcp_call`、DuckDuckGo Search の実装は存在しない。
6. その結果、システムは主にモデルの事前知識に依存して回答しており、商品名の曖昧性解消に弱く、ハルシネーションが発生する。

## 期待される動作
- 明示的に詳細レポートを求めたクエリでは、圧縮された短い要約ではなく、複数セクションから成る実質的な最終レポートが生成されるべきである。
- `Data_Gatherer` のようなロールは、外部事実が必要な場合に公開 Web 調査を実際に実行しなければならず、このバグ修正で要求される Web 検索プロバイダは DuckDuckGo Search である。
- レポートは収集した証拠に基づいて構成され、ブランド名や商品名のような曖昧な対象は、統合前に必ず曖昧性解消されるべきである。
- Planner は、詳細レポート要求に対して、明示的な証拠収集・分析・統合を含む調査指向の DAG に分解すべきである。

## 実際の動作
- 実行時には、保存済みのロールテンプレート定義が使われていない。`RoleTemplate.system_prompt`、`RoleTemplate.tools`、`RoleTemplate.default_params` は CRUD API 経由で永続化・編集できるが、実際の実行経路では `You are a {role} agent.` のような汎用プロンプトと、ユーザークエリおよび親コンテキストしか送っていない。
- backend アプリケーションコードには `web_search`、`rag_search`、`mcp_call` の runtime 実装が存在せず、DuckDuckGo Search 連携もない。seed データ上ではツールが宣言されているが、worker はそれらを実際には実行できない。
- `backend/app/tasks.py` にある既定の Planner プロンプトは、主に DAG JSON の構造と許可ロールを制約するだけであり、詳細レポート要求に対する深いタスク分解、情報源収集、曖昧性解消、根拠付き統合を要求していない。
- Standard タスクの既定 structured output モデルは `ReportSynthesizerResponse` で、`summary: str` と `details: list[str]` しか持てない。この契約により、中間の調査結果も最終レポートも、ユーザーが詳細レポートを明示的に要求していても、短い要約と箇条書きに圧縮されやすい。
- 実行詳細 UI は raw payload 自体は表示できるため、短い結果の主因は frontend 側の切り詰めではない。`History` に保存されているタスク結果そのものがすでに浅い。

## 影響ファイル
- `backend/alembic/versions/20260419_add_role_templates.py` — `web_search`、`rag_search`、`mcp_call` を宣言したロールテンプレートを seed しているが、データ定義に留まっている。
- `backend/app/models.py` — orchestration runtime で消費されていない `RoleTemplate` モデルを定義している。
- `backend/app/routers/templates.py` — ロールテンプレートの CRUD を提供しているが、テンプレートデータは実行系に接続されていない。
- `backend/app/tasks.py` — 既定の Planner system prompt を定義し、すべての Standard タスクの structured output を `ReportSynthesizerResponse` に固定している。
- `backend/app/orchestrator/manager.py` — Standard タスクのプロンプトを `You are a {role} agent.` という汎用テンプレートから組み立てており、宣言済みツールも実行していない。
- `backend/app/orchestrator/debate_controller.py` — Debate 参加者と Mediator のプロンプトも同じ汎用テンプレートから組み立てており、宣言済みツールも実行していない。
- `backend/app/schemas.py` — Standard タスク出力を `summary` と `details` に制限しており、本当の詳細レポートには狭すぎる。
- `docs/requirement_specification.md` — Web Search を worker 側のツール境界として定義し、ロールテンプレートを runtime 実行コンポーネントとして説明しているが、現実装はその契約を満たしていない。