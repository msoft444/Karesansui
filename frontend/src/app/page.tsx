"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";

// HistoryRecord mirrors the HistoryResponse schema from the backend
interface HistoryRecord {
  id: string;
  run_id: string | null;
  task_id: string;
  role: string;
  result: Record<string, unknown> | null;
  progress: Record<string, unknown> | null;
  created_at: string;
}

interface QueryResponse {
  run_id: string;
}

const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

function getLifecycleLabel(
  status: string,
): { label: string; className: string } | null {
  const map: Record<string, { label: string; className: string }> = {
    queued: {
      label: "待機中",
      className: "border-yellow-700/60 bg-yellow-900/40 text-yellow-300",
    },
    "planner-started": {
      label: "プランナー起動中",
      className: "border-blue-700/60 bg-blue-900/40 text-blue-300",
    },
    enqueue_failed: {
      label: "キュー失敗",
      className: "border-red-700/60 bg-red-900/40 text-red-300",
    },
    "planner-failed": {
      label: "プランナー失敗",
      className: "border-red-700/60 bg-red-900/40 text-red-300",
    },
    "orchestration-failed": {
      label: "オーケストレーション失敗",
      className: "border-red-700/60 bg-red-900/40 text-red-300",
    },
    failed: {
      label: "失敗",
      className: "border-red-700/60 bg-red-900/40 text-red-300",
    },
  };
  return map[status] ?? null;
}

export default function DashboardPage() {
  const [query, setQuery] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submittedRunId, setSubmittedRunId] = useState<string | null>(null);

  // Fetch from /api/history/ which is proxied by Next.js to the FastAPI backend
  const { data, error, isLoading } = useSWR<HistoryRecord[]>(
    "/api/history",
    fetcher,
    { refreshInterval: 5000 }
  );

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedQuery = query.trim();
    if (!trimmedQuery || isSubmitting) {
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);
    setSubmittedRunId(null);

    try {
      const response = await fetch("/api/query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: trimmedQuery }),
      });

      const payload = (await response.json().catch(() => null)) as
        | QueryResponse
        | { detail?: string }
        | null;

      if (!response.ok) {
        const detail =
          payload && "detail" in payload && typeof payload.detail === "string"
            ? payload.detail
            : "クエリの送信に失敗しました。時間をおいて再試行してください。";
        throw new Error(detail);
      }

      if (!payload || !("run_id" in payload) || typeof payload.run_id !== "string") {
        throw new Error("run_id を取得できませんでした。");
      }

      setSubmittedRunId(payload.run_id);
    } catch (submitException) {
      setSubmitError(
        submitException instanceof Error
          ? submitException.message
          : "クエリの送信に失敗しました。時間をおいて再試行してください。"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <section className="rounded-2xl border border-gray-800 bg-gray-950/80 p-5 shadow-lg shadow-black/20">
        <div className="mb-4">
          <h1 className="text-2xl font-bold text-gray-100">新しいクエリを実行</h1>
          <p className="mt-1 text-sm text-gray-500">
            タスク内容を送信してオーケストレーションを開始し、run_id を取得します。
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="dashboard-query"
              className="mb-2 block text-sm font-medium text-gray-300"
            >
              クエリ内容
            </label>
            <textarea
              id="dashboard-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="実行したいタスクや調査内容を入力してください。"
              rows={5}
              className="w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-3 text-sm text-gray-100 outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/40 placeholder:text-gray-600"
            />
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-gray-500">
              送信後に発行された run_id からライブトレースへ移動できます。
            </p>
            <button
              type="submit"
              disabled={!query.trim() || isSubmitting}
              className="inline-flex items-center justify-center rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {isSubmitting ? "実行中..." : "実行"}
            </button>
          </div>
        </form>

        {submitError && (
          <div className="mt-4 rounded-xl border border-red-500/70 bg-red-950/40 px-4 py-3 text-sm text-red-200">
            {submitError}
          </div>
        )}

        {submittedRunId && (
          <div className="mt-4 rounded-xl border border-emerald-500/40 bg-emerald-950/20 px-4 py-4 text-sm text-emerald-100">
            <p className="font-medium text-emerald-200">クエリを受け付けました。</p>
            <p className="mt-2 font-mono text-xs text-emerald-300 break-all">
              run_id: {submittedRunId}
            </p>
            <Link
              href={`/live?run_id=${submittedRunId}`}
              className="mt-3 inline-flex items-center rounded-lg border border-emerald-400/50 px-3 py-2 text-xs font-semibold text-emerald-200 transition hover:bg-emerald-400/10"
            >
              ライブトレースを開く
            </Link>
          </div>
        )}
      </section>

      <section>
        {/* Page header */}
        <div className="mb-6">
          <h2 className="text-2xl font-bold text-gray-100">実行履歴</h2>
          <p className="mt-1 text-sm text-gray-500">
            エージェントタスクの実行ログ（5秒ごとに自動更新）
          </p>
        </div>

        {/* Loading state */}
        {isLoading && (
          <div className="flex items-center gap-3 py-8 text-gray-400">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
            <span>読み込み中...</span>
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="rounded-lg border border-red-500 bg-red-900/30 px-4 py-3 text-sm text-red-300">
            データの取得に失敗しました。バックエンドの接続を確認してください。
          </div>
        )}

        {/* History table */}
        {data && (
          <div className="overflow-x-auto rounded-xl border border-gray-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-800 bg-gray-900">
                <tr>
                  {["Task ID", "ロール", "結果（抜粋）", "作成日時"].map((heading) => (
                    <th
                      key={heading}
                      className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500"
                    >
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {data.length === 0 ? (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-4 py-12 text-center text-sm text-gray-600"
                    >
                      履歴データがありません。
                    </td>
                  </tr>
                ) : (
                  data.map((record) => (
                    <tr
                      key={record.id}
                      className="bg-gray-950 transition-colors hover:bg-gray-900"
                    >
                      {/* Task ID */}
                      <td className="max-w-[180px] px-4 py-3">
                        <span
                          className="block truncate font-mono text-xs text-indigo-300"
                          title={record.task_id}
                        >
                          {record.task_id}
                        </span>
                      </td>

                      {/* Role badge */}
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className="inline-flex items-center rounded-full border border-indigo-700/60 bg-indigo-900/50 px-2.5 py-0.5 text-xs font-medium text-indigo-300">
                          {record.role}
                        </span>
                      </td>

                      {/* Result preview */}
                      <td className="max-w-[340px] px-4 py-3">
                        {(() => {
                          if (!record.result) {
                            return (
                              <span className="font-mono text-xs text-gray-700">
                                —
                              </span>
                            );
                          }
                          const statusStr =
                            typeof (record.result as { status?: unknown }).status ===
                            "string"
                              ? (record.result as { status: string }).status
                              : null;
                          const lifecycle = statusStr
                            ? getLifecycleLabel(statusStr)
                            : null;
                          if (lifecycle) {
                            return (
                              <span
                                className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${lifecycle.className}`}
                              >
                                {lifecycle.label}
                              </span>
                            );
                          }
                          return (
                            <span
                              className="block truncate font-mono text-xs text-gray-500"
                              title={JSON.stringify(record.result)}
                            >
                              {JSON.stringify(record.result).slice(0, 120)}
                            </span>
                          );
                        })()}
                      </td>

                      {/* Timestamp */}
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-600">
                        {new Date(record.created_at).toLocaleString("ja-JP")}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Record count */}
        {data && data.length > 0 && (
          <p className="mt-3 text-xs text-gray-700">{data.length} 件のレコード</p>
        )}
      </section>
    </div>
  );
}
