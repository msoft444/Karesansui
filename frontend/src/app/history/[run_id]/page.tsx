"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";

// RunStatus mirrors the RunStatus enum from the backend
type RunStatus = "queued" | "running" | "completed" | "failed";

// TaskStatus mirrors the TaskStatus enum from the backend
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

function getRunStatusBadge(
  status: string,
): { label: string; className: string } {
  const map: Record<string, { label: string; className: string }> = {
    queued: {
      label: "待機中",
      className: "border-yellow-700/60 bg-yellow-900/40 text-yellow-300",
    },
    running: {
      label: "実行中",
      className: "border-blue-700/60 bg-blue-900/40 text-blue-300",
    },
    completed: {
      label: "完了",
      className: "border-emerald-700/60 bg-emerald-900/40 text-emerald-300",
    },
    failed: {
      label: "失敗",
      className: "border-red-700/60 bg-red-900/40 text-red-300",
    },
  };
  return (
    map[status] ?? {
      label: status,
      className: "border-gray-700/60 bg-gray-900/40 text-gray-400",
    }
  );
}

function getTaskStatusBadge(
  status: string,
): { label: string; className: string } {
  const map: Record<string, { label: string; className: string }> = {
    pending: {
      label: "保留",
      className: "border-gray-700/60 bg-gray-900/40 text-gray-400",
    },
    running: {
      label: "実行中",
      className: "border-blue-700/60 bg-blue-900/40 text-blue-300",
    },
    completed: {
      label: "完了",
      className: "border-emerald-700/60 bg-emerald-900/40 text-emerald-300",
    },
    failed: {
      label: "失敗",
      className: "border-red-700/60 bg-red-900/40 text-red-300",
    },
  };
  return (
    map[status] ?? {
      label: status,
      className: "border-gray-700/60 bg-gray-900/40 text-gray-400",
    }
  );
}

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

  return (
    <div className="p-6 space-y-6">
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
                    const badge = getRunStatusBadge(data.status);
                    return (
                      <span
                        className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${badge.className}`}
                      >
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
              <div className="flex gap-2 shrink-0">
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

          {/* Final result */}
          <section>
            <h2 className="mb-3 text-lg font-bold text-gray-100">最終結果</h2>
            {data.final_result_preview || data.final_result ? (
              <div className="rounded-xl border border-gray-800 bg-gray-950 px-5 py-4">
                {data.final_result_preview && (
                  <p className="text-sm text-gray-200 whitespace-pre-wrap leading-relaxed">
                    {data.final_result_preview}
                  </p>
                )}
                {data.final_result && !data.final_result_preview && (
                  <pre className="overflow-x-auto text-xs text-gray-400 font-mono whitespace-pre-wrap">
                    {JSON.stringify(data.final_result, null, 2)}
                  </pre>
                )}
              </div>
            ) : (
              <div className="rounded-xl border border-gray-800 px-5 py-6 text-sm text-gray-600 italic">
                {data.status === "queued"
                  ? "実行待機中です。"
                  : data.status === "running"
                  ? "実行中です。完了後に結果が表示されます。"
                  : "最終結果はありません。"}
              </div>
            )}
          </section>

          {/* Task list */}
          {data.tasks && data.tasks.length > 0 && (
            <section>
              <h2 className="mb-3 text-lg font-bold text-gray-100">実行タスク</h2>
              <div className="space-y-2">
                {data.tasks.map((task) => {
                  const badge = getTaskStatusBadge(task.status);
                  return (
                    <div
                      key={task.task_id}
                      className="rounded-xl border border-gray-800 bg-gray-950 px-5 py-4"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${badge.className}`}
                        >
                          {badge.label}
                        </span>
                        <span className="rounded border border-indigo-800/50 bg-indigo-950/40 px-2 py-0.5 text-xs font-medium text-indigo-300">
                          {task.task_type}
                        </span>
                        <span className="font-mono text-xs text-gray-400 truncate max-w-[220px]" title={task.task_id}>
                          {task.task_id}
                        </span>
                        {task.role && (
                          <span className="text-xs text-gray-500">{task.role}</span>
                        )}
                        {task.sub_records.length > 0 && (
                          <span className="text-xs text-gray-600">
                            サブレコード: {task.sub_records.length}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-gray-700">
                詳細なタスクドリルダウンは後続ステップで実装されます。
              </p>
            </section>
          )}
        </>
      )}
    </div>
  );
}
