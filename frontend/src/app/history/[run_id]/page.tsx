"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import DagVisualizer, { type DagTask } from "@/components/DagVisualizer";

// ── Types ─────────────────────────────────────────────────────────────────────

type RunStatus = "queued" | "running" | "completed" | "failed";
type TaskStatus = "pending" | "running" | "completed" | "failed";

interface SubRecord {
  id: string;
  task_id: string;
  role: string;
  result: Record<string, unknown> | null;
  progress: Record<string, unknown> | null;
  created_at: string;
}

interface DisplayTask {
  task_id: string;
  task_type: "Standard" | "Debate";
  role: string | null;
  participants: string[] | null;
  mediator: string | null;
  parent_ids: string[];
  dynamic_params: Record<string, unknown>;
  status: TaskStatus;
  created_at: string | null;
  result: Record<string, unknown> | null;
  progress: Record<string, unknown> | null;
  sub_records: SubRecord[];
}

interface RunDetail {
  run_id: string;
  status: RunStatus;
  created_at: string;
  final_result: Record<string, unknown> | null;
  final_result_preview: string | null;
  dag_topology: Record<string, unknown>[] | null;
  tasks: DisplayTask[];
}

// ── Fetcher ───────────────────────────────────────────────────────────────────

const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (res.status === 404) {
    const err = new Error("not_found");
    (err as Error & { status: number }).status = 404;
    throw err;
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

// ── Badge helpers ──────────────────────────────────────────────────────────────

function runStatusBadge(status: string): { label: string; cls: string } {
  const map: Record<string, { label: string; cls: string }> = {
    queued:    { label: "待機中", cls: "border-yellow-700/60 bg-yellow-900/40 text-yellow-300" },
    running:   { label: "実行中", cls: "border-blue-700/60 bg-blue-900/40 text-blue-300" },
    completed: { label: "完了",   cls: "border-emerald-700/60 bg-emerald-900/40 text-emerald-300" },
    failed:    { label: "失敗",   cls: "border-red-700/60 bg-red-900/40 text-red-300" },
  };
  return map[status] ?? { label: status, cls: "border-gray-700/60 bg-gray-900/40 text-gray-400" };
}

function taskStatusBadge(status: string): { label: string; cls: string } {
  const map: Record<string, { label: string; cls: string }> = {
    pending:   { label: "保留",   cls: "border-gray-700/60 bg-gray-900/40 text-gray-400" },
    running:   { label: "実行中", cls: "border-blue-700/60 bg-blue-900/40 text-blue-300" },
    completed: { label: "完了",   cls: "border-emerald-700/60 bg-emerald-900/40 text-emerald-300" },
    failed:    { label: "失敗",   cls: "border-red-700/60 bg-red-900/40 text-red-300" },
  };
  return map[status] ?? { label: status, cls: "border-gray-700/60 bg-gray-900/40 text-gray-400" };
}

// ── JSON display block ─────────────────────────────────────────────────────────

function JsonBlock({ data }: { data: Record<string, unknown> }) {
  return (
    <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 text-xs text-gray-300 font-mono whitespace-pre-wrap max-h-72">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

// ── Debate sub-record (internal round) row ────────────────────────────────────

function DebateRoundRow({ record, index }: { record: SubRecord; index: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-purple-800/30 bg-purple-950/20">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-purple-900/10 transition-colors"
      >
        <span className="text-xs text-purple-400 font-medium shrink-0">ラウンド {index + 1}</span>
        <span className="text-xs text-gray-500 font-mono truncate">{record.role}</span>
        <span className="ml-auto shrink-0 text-gray-600 text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <div>
              <span className="text-gray-500 font-medium">レコードID</span>
              <p className="font-mono text-gray-300 mt-0.5 break-all">{record.task_id}</p>
            </div>
            <div>
              <span className="text-gray-500 font-medium">実行日時</span>
              <p className="text-gray-300 mt-0.5">{new Date(record.created_at).toLocaleString("ja-JP")}</p>
            </div>
          </div>
          {record.progress && Object.keys(record.progress).length > 0 && (
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1.5">ランタイムメタデータ</p>
              <JsonBlock data={record.progress} />
            </div>
          )}
          {record.result ? (
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1.5">結果</p>
              <JsonBlock data={record.result} />
            </div>
          ) : (
            <p className="text-xs text-gray-600 italic">結果なし</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Task card (collapsible) ────────────────────────────────────────────────────

function TaskCard({ task }: { task: DisplayTask }) {
  const [open, setOpen] = useState(false);
  const sb = taskStatusBadge(task.status);
  const hasParams = task.dynamic_params && Object.keys(task.dynamic_params).length > 0;
  const hasProgress = task.progress && Object.keys(task.progress).length > 0;
  const isDebate = task.task_type === "Debate";

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950 overflow-hidden">
      {/* Collapsed header */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex flex-wrap items-center gap-2 px-5 py-3.5 text-left hover:bg-gray-900/60 transition-colors"
      >
        {/* Status badge */}
        <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${sb.cls}`}>
          {sb.label}
        </span>
        {/* Task type badge */}
        <span className={`rounded border px-2 py-0.5 text-xs font-medium ${
          isDebate
            ? "border-purple-800/50 bg-purple-950/40 text-purple-300"
            : "border-indigo-800/50 bg-indigo-950/40 text-indigo-300"
        }`}>
          {isDebate ? "ディベート" : "標準"}
        </span>
        {/* Task ID */}
        <span
          className="font-mono text-xs text-gray-400 truncate max-w-[200px] sm:max-w-xs"
          title={task.task_id}
        >
          {task.task_id}
        </span>
        {/* Role / participants summary */}
        {isDebate && task.participants && task.participants.length > 0 ? (
          <span className="text-xs text-gray-500 truncate">{task.participants.join(" · ")}</span>
        ) : task.role ? (
          <span className="text-xs text-gray-500 truncate">{task.role}</span>
        ) : null}
        {/* Round count for Debate */}
        {isDebate && task.sub_records.length > 0 && (
          <span className="text-xs text-gray-600 shrink-0">{task.sub_records.length} ラウンド</span>
        )}
        {/* Chevron */}
        <span className="ml-auto shrink-0 text-gray-600 text-xs">{open ? "▲" : "▼"}</span>
      </button>

      {/* Expanded detail panel */}
      {open && (
        <div className="border-t border-gray-800 px-5 py-4 space-y-4">
          {/* Metadata grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-xs">
            <div>
              <span className="text-gray-500 font-medium">タスクID</span>
              <p className="font-mono text-gray-300 mt-0.5 break-all">{task.task_id}</p>
            </div>
            <div>
              <span className="text-gray-500 font-medium">タイプ</span>
              <p className="text-gray-300 mt-0.5">{task.task_type === "Debate" ? "ディベート" : "標準"}</p>
            </div>
            {!isDebate && task.role && (
              <div>
                <span className="text-gray-500 font-medium">ロール</span>
                <p className="text-gray-300 mt-0.5">{task.role}</p>
              </div>
            )}
            {isDebate && task.participants && task.participants.length > 0 && (
              <div>
                <span className="text-gray-500 font-medium">参加者</span>
                <p className="text-gray-300 mt-0.5">{task.participants.join(", ")}</p>
              </div>
            )}
            {isDebate && task.mediator && (
              <div>
                <span className="text-gray-500 font-medium">司会</span>
                <p className="text-gray-300 mt-0.5">{task.mediator}</p>
              </div>
            )}
            {task.parent_ids.length > 0 && (
              <div className="sm:col-span-2">
                <span className="text-gray-500 font-medium">依存タスク</span>
                <p className="text-gray-300 mt-0.5 font-mono">{task.parent_ids.join(", ")}</p>
              </div>
            )}
          </div>

          {/* Planner-assigned dynamic params */}
          {hasParams && (
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1.5">プランナーパラメータ</p>
              <JsonBlock data={task.dynamic_params} />
            </div>
          )}

          {/* Runtime metadata (progress) */}
          {hasProgress && (
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1.5">ランタイムメタデータ</p>
              <JsonBlock data={task.progress!} />
            </div>
          )}

          {/* Execution result */}
          <div>
            <p className="text-xs text-gray-500 font-medium mb-1.5">実行結果</p>
            {task.result ? (
              <JsonBlock data={task.result} />
            ) : (
              <p className="text-xs text-gray-600 italic">
                {task.status === "running" ? "実行中です..." : "結果なし"}
              </p>
            )}
          </div>

          {/* Debate internal rounds */}
          {isDebate && task.sub_records.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 font-medium mb-1.5">ディベートラウンド</p>
              <div className="space-y-1.5">
                {task.sub_records.map((rec, i) => (
                  <DebateRoundRow key={rec.id} record={rec} index={i} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function RunDetailPage() {
  const params = useParams<{ run_id: string }>();
  const runId = params.run_id;

  const { data, error, isLoading } = useSWR<RunDetail>(
    runId ? `/api/history/runs/${runId}` : null,
    fetcher,
    { refreshInterval: 5000 }
  );

  const isNotFound =
    error != null &&
    (error as Error & { status?: number }).status === 404;

  // Build DagTask[] for DagVisualizer: merge dag_topology with live task statuses
  const dagTasks: DagTask[] = (() => {
    if (!data?.dag_topology || data.dag_topology.length === 0) return [];
    const statusMap = new Map<string, TaskStatus>(
      (data.tasks ?? []).map((t) => [t.task_id, t.status])
    );
    return data.dag_topology.map((raw) => ({
      task_id:       (raw.task_id as string) ?? "",
      task_type:     (raw.task_type as "Standard" | "Debate") ?? "Standard",
      role:          (raw.role as string | null) ?? null,
      participants:  (raw.participants as string[] | undefined) ?? undefined,
      mediator:      (raw.mediator as string | null | undefined) ?? null,
      parent_ids:    (raw.parent_ids as string[]) ?? [],
      dynamic_params:(raw.dynamic_params as Record<string, unknown> | undefined) ?? undefined,
      status:        statusMap.get(raw.task_id as string) ?? "pending",
    }));
  })();

  // For failed runs where the backend could not derive a run-level final_result,
  // surface the latest relevant error payload from the failed task(s).
  // Sort failed tasks by created_at desc (backend-persisted timestamp) so we
  // always surface the most recently executed failure, regardless of DAG order.
  const failedTaskResult: Record<string, unknown> | null =
    data?.status === "failed" && !data?.final_result
      ? ([...(data.tasks ?? [])]
          .filter((t) => t.status === "failed" && t.result != null && t.created_at != null)
          .sort((a, b) => new Date(b.created_at!).getTime() - new Date(a.created_at!).getTime())
          .at(0)?.result ?? null)
      : null;

  return (
    <div className="p-4 sm:p-6 space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-xs text-gray-500">
        <Link href="/" className="hover:text-gray-300 transition-colors">
          ダッシュボード
        </Link>
        <span>/</span>
        <span className="text-gray-400">実行詳細</span>
      </nav>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center gap-3 py-12 text-gray-400">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
          <span>実行情報を読み込み中...</span>
        </div>
      )}

      {/* Not-found state */}
      {isNotFound && (
        <div className="rounded-xl border border-red-500/60 bg-red-950/30 px-5 py-8 text-center">
          <p className="text-lg font-semibold text-red-300">実行が見つかりません</p>
          <p className="mt-2 font-mono text-xs text-red-400/70 break-all">{runId}</p>
          <Link
            href="/"
            className="mt-4 inline-flex items-center rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:bg-gray-800 transition-colors"
          >
            ダッシュボードに戻る
          </Link>
        </div>
      )}

      {/* Generic error state */}
      {error && !isNotFound && (
        <div className="rounded-lg border border-red-500 bg-red-900/30 px-4 py-3 text-sm text-red-300">
          データの取得に失敗しました。バックエンドの接続を確認してください。
        </div>
      )}

      {/* Run detail content */}
      {data && (
        <>
          {/* Header */}
          <section className="rounded-2xl border border-gray-800 bg-gray-950/80 p-5 shadow-lg shadow-black/20">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-3 mb-2">
                  {(() => {
                    const badge = runStatusBadge(data.status);
                    return (
                      <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${badge.cls}`}>
                        {badge.label}
                      </span>
                    );
                  })()}
                  <span className="font-mono text-xs text-gray-500">
                    {(data.tasks ?? []).length} タスク
                  </span>
                </div>
                <p className="font-mono text-sm text-indigo-300 break-all">{data.run_id}</p>
                <p className="mt-1 text-xs text-gray-500">
                  {new Date(data.created_at).toLocaleString("ja-JP")}
                </p>
              </div>
              <div className="flex flex-wrap gap-2 shrink-0">
                <Link
                  href={`/live?run_id=${data.run_id}`}
                  className="inline-flex items-center rounded-lg border border-gray-700 px-3 py-2 text-xs text-gray-300 hover:bg-gray-800 transition-colors"
                >
                  ライブトレース
                </Link>
                <Link
                  href="/"
                  className="inline-flex items-center rounded-lg border border-gray-700 px-3 py-2 text-xs text-gray-300 hover:bg-gray-800 transition-colors"
                >
                  ダッシュボードに戻る
                </Link>
              </div>
            </div>
          </section>

          {/* ── Section 1: Final query result ── */}
          <section>
            <h2 className="mb-3 text-lg font-bold text-gray-100">最終結果</h2>
            {data.final_result_preview || data.final_result || failedTaskResult ? (
              <div className="rounded-xl border border-gray-800 bg-gray-950 px-5 py-4 space-y-3">
                {data.final_result_preview && (
                  <p className="text-sm text-gray-200 whitespace-pre-wrap leading-relaxed">
                    {data.final_result_preview}
                  </p>
                )}
                {!data.final_result_preview && data.status === "failed" && (
                  <p className="text-sm text-red-400">
                    実行は失敗しました。タスクリストで詳細を確認してください。
                  </p>
                )}
                {(data.final_result ?? failedTaskResult) && (
                  <details>
                    <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-300 transition-colors select-none">
                      {data.final_result ? "生データを表示" : "エラー詳細を表示"}
                    </summary>
                    <div className="mt-2">
                      <JsonBlock data={(data.final_result ?? failedTaskResult)!} />
                    </div>
                  </details>
                )}
              </div>
            ) : (
              <div className="rounded-xl border border-gray-800 px-5 py-6 text-sm text-gray-600 italic">
                {data.status === "queued"
                  ? "実行待機中です。"
                  : data.status === "running"
                  ? "実行中です。完了後に結果が表示されます。"
                  : data.status === "failed"
                  ? "実行は失敗しました。タスクリストで詳細を確認してください。"
                  : "最終結果はありません。"}
              </div>
            )}
          </section>

          {/* ── Section 2: Executed task list ── */}
          <section>
            <h2 className="mb-3 text-lg font-bold text-gray-100">実行タスク</h2>
            {data.tasks && data.tasks.length > 0 ? (
              <div className="space-y-2">
                {data.tasks.map((task) => (
                  <TaskCard key={task.task_id} task={task} />
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-gray-800 px-5 py-6 text-sm text-gray-600 italic">
                タスク情報がありません。
              </div>
            )}
          </section>

          {/* ── Section 3: DAG ── */}
          <section>
            <h2 className="mb-3 text-lg font-bold text-gray-100">DAG</h2>
            {dagTasks.length > 0 ? (
              <div
                className="rounded-xl border border-gray-800 bg-gray-950 overflow-hidden"
                style={{ height: 420 }}
              >
                <DagVisualizer tasks={dagTasks} />
              </div>
            ) : (
              <div className="rounded-xl border border-gray-800 px-5 py-6 text-sm text-gray-600 italic">
                DAGデータがありません。
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
