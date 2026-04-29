# 修正計画: detailedquery (2026-04-28)

## Step 1: 実行時にロールテンプレートを解決して適用する

### Target
- `backend/app/orchestrator/manager.py`
- `backend/app/orchestrator/debate_controller.py`
- `backend/app/services/role_templates.py` のような新規 helper

### Req
- 推論開始前に、すべての Standard ロール、Debate 参加者、Mediator について参照先の `RoleTemplate` レコードを読み込むこと。
- 実際の system prompt は、`system_prompt` と、`default_params` と Planner が与えた `dynamic_params` をマージした内容から構築すること。
- Planner が未知のテンプレートを参照した場合は、汎用プロンプトへ黙ってフォールバックするのではなく、明示的な失敗として扱うこと。
- 履歴上で実際にどのテンプレートとパラメータが使われたか追跡できるよう、`progress` か隣接する runtime 情報に十分なメタデータを残すこと。

### Constrain
- 具体的な runtime 上の不足が additive な項目を必要としない限り、Planner の DAG スキーマは変更しないこと。
- 既存のテンプレート CRUD データモデルを迂回したり、同じプロンプト文面を orchestrator 側に重複ハードコードしたりしないこと。
- エージェント内部通信は英語、ユーザー向け UI は日本語という既存の言語境界を維持すること。

## Step 2: 明示的な runtime tool-dispatch 契約を導入する

### Target
- `backend/app/services/tool_dispatch.py` のような新規 helper
- `backend/app/orchestrator/manager.py`
- `backend/app/orchestrator/debate_controller.py`
- additive な runtime メタデータが本当に必要な場合のみ `backend/app/models.py`

### Req
- 各テンプレートの `tools` 宣言を、prompt 上の文言ではなく、実際の runtime 挙動へ変換すること。
- Standard と Debate の両実行経路で共有できるよう、ツール選択、呼び出し、出力正規化、エラー処理を 1 つの dispatch 層へ集約すること。
- どのツールが利用可能だったか、どのツールを実際に実行したか、どのツールが失敗または skip されたかを記録し、履歴上で調査実施の有無を証明できるようにすること。
- テンプレートが runtime 未対応のツールを宣言している場合は、黙って無視するのではなく、明示的に失敗させること。

### Constrain
- ロール固有のツール実行ロジックを複数の orchestration 呼び出し箇所へ分散させないこと。
- ツール出力は、prompt コンテキストへ安全に入れられるよう、サイズ制限され、serializable であること。
- 現在の `tools` データ形状が不十分だと証明されない限り、RoleTemplate の CRUD 契約は変更しないこと。

## Step 3: DuckDuckGo Search を `web_search` プロバイダとして実装する

### Target
- `backend/app/services/web_search.py` のような新規 service/helper
- 追加の検索ライブラリが必要なら `backend/requirements.txt`
- Step 2 で導入した共有 tool-dispatch 層

### Req
- このバグ修正における唯一の公開 Web 検索プロバイダとして DuckDuckGo Search を使う、実際の `web_search` runtime ツールを実装すること。
- 検索結果は、エージェントコンテキストへ注入しやすく、必要に応じて確認用に永続化もできるよう、決定的でコンパクトな構造へ正規化すること。
- ブランド、商品、企業、地名のような曖昧な一般名詞は、モデルの事前知識で推測するのではなく、統合前に必ず調査できるよう、曖昧性解消向けクエリも扱えるようにすること。
- 失敗時には、プロバイダ到達不能、結果 0 件、prompt 側の誤用を区別できる程度の診断情報を出せるようにすること。

### Constrain
- 検索強化がプロンプトウィンドウを圧迫しないよう、タイムアウト、件数、ペイロードサイズは制限すること。
- この修正で、ブラウザ自動操作、重いスクレイピング、他の検索プロバイダを持ち込まないこと。
- 自動テストで決定的 mock を使える実装形にすること。

## Step 4: 詳細レポート要求に対する Planner の分解方針を強化する

### Target
- `backend/app/tasks.py`
- 既定の planner prompt を管理している seed または設定面

### Req
- 詳細レポート要求では、証拠収集、分析、必要に応じたレビュー、最終統合を含む多段 DAG を優先するよう、既定の Planner prompt を更新すること。
- ユーザーが詳細レポートや Web 上の最新事実を求めている場合は、最終統合前に少なくとも 1 つの調査系タスクを割り当てるよう Planner に指示すること。
- クエリが複数の実在対象を指し得る場合、対象の曖昧性解消を必須手順として扱うよう Planner に指示すること。
- Step 1-3 の runtime 契約で実際に実行可能な場合にのみ、tool-capable な調査ロールを割り当てるよう Planner に要求すること。

### Constrain
- 既存の DAG JSON 契約と互換ロール名は維持すること。
- すべての単純要求で大きな DAG を強制しないこと。分解強化は、ユーザーが詳細性、根拠、Web 調査を求める場合に発動すること。
- 既存の structured-output 検証経路で扱える程度の決定性は維持すること。

## Step 5: 調査タスクと最終レポートの出力契約を拡張する

### Target
- `backend/app/schemas.py`
- `backend/app/tasks.py`
- `backend/app/services/history_runs.py`
- richer payload に合わせて描画変更が必要なら `frontend/src/app/history/[run_id]/page.tsx`

### Req
- 複数セクションの本文、主要 findings、根拠や source note、必要に応じた不確実性を表現できる、本当の詳細レポート用 output model を導入すること。
- 最終成果物が詳細レポートである場合に、すべての Standard タスクへ同じ最小構造 `ReportSynthesizerResponse(summary, details[])` を使い続けるのをやめること。
- 調査ステップで得た有用な証拠を保持し、最終 synthesizer がそれを数個の箇条書きへ潰すのではなく、引用または要約して使えるようにすること。
- richer な payload 形状を導入した後も、run-summary preview の生成を決定的に保ち、run-detail 画面が旧形式と新形式の両方を扱えるようにすること。

### Constrain
- 既存の `summary/details` 構造を使う過去の履歴行とは後方互換を保つこと。
- richer な payload を既存の JSONB カラム内に収められるなら、スキーマ migration は要求しないこと。
- backend の結果契約が弱いままなのに frontend 側だけで整形してごまかすような対応は避けること。

## Step 6: レポート深度と Web 根拠付けに対する回帰テストと検証を追加する

### Target
- `backend/tests/` 配下の focused な backend テスト
- run detail 描画に必要な最小限の frontend 検証
- `Takenoko no Sato` のような既知の曖昧クエリに対する focused manual verification

### Req
- runtime 実行が汎用プロンプトへフォールバックせず、`RoleTemplate` レコードを解決して使っていることを証明する回帰テストを追加すること。
- 新しい dispatch 層で、未対応ツール宣言が黙って無視されず、明示的に失敗することを証明する回帰テストを追加すること。
- `web_search` が利用可能なタスクで DuckDuckGo Search 連携が呼ばれ、正規化された検索証拠がタスクコンテキストへ投入されることを証明する回帰テストを追加すること。
- `Takenoko no Sato` のような曖昧クエリに対し、菓子商品として根拠付きで回答し、別の対象へハルシネーションしないことを確認する focused な検証ケースを追加すること。
- 詳細レポート要求で、現状の短い summary-plus-bullets より豊かな最終結果形状が生成されることを確認する回帰チェックを追加すること。

### Constrain
- 自動テストでは live DuckDuckGo 依存よりも、決定的な mock か記録済み tool response を優先すること。
- 検証範囲はこのバグに限定し、レポート深度、証拠収集、ロールテンプレート実行、runtime のツール配線、Web 検索による根拠付けに集中すること。
- この修正で必要な範囲を超えて、history UI 全体の再設計や一般的な orchestration リファクタへ広げないこと。