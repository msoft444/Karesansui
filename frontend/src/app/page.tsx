"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";

// RunSummary mirrors the RunSummary schema from the backend
interface RunSummary {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  final_result_preview: string | null;
  task_count: number;
}

interface QueryResponse {
  run_id: string;
}

interface DiagnosticsResponse {
  inference_backend_reachable: boolean;
  inference_backend_url: string;
  error: string | null;
  checked_at: string;
}

const fetcher = async (url: string) => {
  const res = await fetch(url);
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

export default function DashboardPage() {
  const [query, setQuery] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submittedRunId, setSubmittedRunId] = useState<string | null>(null);

  // Fetch run-summary list from the run-oriented endpoint
  const { data, error, isLoading } = useSWR<RunSummary[]>(
    "/api/history/runs",
    fetcher,
    { refreshInterval: 5000 }
  );

  const { data: diagnostics } = useSWR<DiagnosticsResponse>(
    "/api/workers/diagnostics",
    fetcher,
    { refreshInterval: 15000 }
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
      {/* Inference backend status banner — shown only when unavailable */}
      {diagnostics && !diagnostics.inference_backend_reachable && (
        <div className="rounded-xl border border-amber-500/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
          <p className="font-semibold">⚠️ 推論バックエンドに接続できません</p>
          <p className="mt-1 text-xs text-amber-300/80">
            URL: <span className="font-mono">{diagnostics.inference_backend_url}</span>
          </p>
          {diagnostics.error && (
            <p className="mt-1 text-xs text-amber-400/70 font-mono">{diagnostics.error}</p>
          )}
          <p className="mt-2 text-xs text-amber-300/70">
            タスクを送信してもプランナーが失敗します。推論サーバーを起動してから再試行してください。
          </p>
        </div>
      )}

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
            <div className="mt-3 flex flex-wrap gap-2">
              <Link
                href={`/history/${submittedRunId}`}
                className="inline-flex items-center rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-emerald-500"
              >
                実行結果を確認
              </Link>
              <Link
                href={`/live?run_id=${submittedRunId}`}
                className="inline-flex items-center rounded-lg border border-emerald-400/50 px-3 py-2 text-xs font-semibold text-emerald-200 transition hover:bg-emerald-400/10"
              >
                ライブトレースを開く
              </Link>
            </div>
          </div>
        )}
      </section>

      <section>
        {/* Page header */}
        <div className="mb-6">
          <h2 className="text-2xl font-bold text-gray-100">実行履歴</h2>
          <p className="mt-1 text-sm text-gray-500">
            クエリ実行の一覧（5秒ごとに自動更新）
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

        {/* Run list */}
        {data && (
          <div className="space-y-3">
            {data.length === 0 ? (
              <div className="rounded-xl border border-gray-800 px-4 py-12 text-center text-sm text-gray-600">
                実行履歴はありません。
              </div>
            ) : (
              data.map((run) => {
                const badge = getRunStatusBadge(run.status);
                return (
                  <Link
                    key={run.run_id}
                    href={`/history/${run.run_id}`}
                    className="block rounded-xl border border-gray-800 bg-gray-950 px-5 py-4 transition-colors hover:border-indigo-700/60 hover:bg-gray-900"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${badge.className}`}
                          >
                            {badge.label}
                          </span>
                          <span className="font-mono text-xs text-indigo-300 truncate max-w-[260px]" title={run.run_id}>
                            {run.run_id}
                          </span>
                        </div>
                        {run.final_result_preview ? (
                          <p className="mt-2 line-clamp-2 text-sm text-gray-300">
                            {run.final_result_preview}
                          </p>
                        ) : (
                          <p className="mt-2 text-xs text-gray-600 italic">
                            {run.status === "queued"
                              ? "実行待機中です"
                              : run.status === "running"
                              ? "実行中です"
                              : "結果なし"}
                          </p>
                        )}
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-xs text-gray-500">
                          {new Date(run.created_at).toLocaleString("ja-JP")}
                        </p>
                        <p className="mt-1 text-xs text-gray-700">
                          {run.task_count} タスク
                        </p>
                      </div>
                    </div>
                  </Link>
                );
              })
            )}
          </div>
        )}

        {/* Record count */}
        {data && data.length > 0 && (
          <p className="mt-3 text-xs text-gray-700">{data.length} 件の実行</p>
        )}
      </section>
    </div>
  );
}
