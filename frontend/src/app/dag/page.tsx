"use client";

import { useState } from "react";
import useSWR from "swr";

import DagVisualizer, { DagNodeStatus, DagTask } from "../../components/DagVisualizer";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HistoryRecord {
  id: string;
  run_id: string | null;
  task_id: string;
  role: string;
  result: Record<string, unknown> | null;
  progress: Record<string, unknown> | null;
  created_at: string;
}

/** Shape of each entry in the Planner's `result.tasks` array. */
interface PlannerTask {
  task_id: string;
  task_type: "Standard" | "Debate";
  role?: string | null;
  participants?: string[];
  mediator?: string | null;
  parent_ids: string[];
  dynamic_params?: Record<string, unknown>;
}

/**
 * A selectable DAG run anchored by a single Planner history record.
 * The Planner record's `run_id` is the deterministic foreign key that links
 * every History row produced during the same orchestration invocation.
 */
interface DagRun {
  id: string;                        // plannerRecord.id — unique Planner row UUID
  runId: string;                     // shared run_id across all History rows for this run
  createdAt: string;                 // ISO timestamp for display purposes
  topology: PlannerTask[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

/** Derive an execution status from a single history record. */
function statusFromRecord(record: HistoryRecord | undefined): DagNodeStatus {
  if (!record) return "pending";
  if (record.result && (record.result as { error?: unknown }).error) return "failed";
  if (record.result) return "completed";
  if (record.progress) return "running";
  return "pending";
}

/**
 * Scan all history records for Planner records that carry a `result.tasks`
 * topology array and a non-null `run_id`.  Each such record represents
 * one completed DAG planning run.
 *
 * Returns newest-first for the selector UI.
 */
function extractDagRuns(records: HistoryRecord[]): DagRun[] {
  const plannerRecords = records.filter((r) => {
    const tasks = r.result?.tasks;
    return (
      r.role.toLowerCase() === "planner" &&
      r.run_id !== null &&
      Array.isArray(tasks) &&
      (tasks as unknown[]).length > 0
    );
  });

  const runs: DagRun[] = plannerRecords.map((r) => ({
    id: r.id,
    runId: r.run_id!,
    createdAt: r.created_at,
    topology: r.result!.tasks as PlannerTask[],
  }));

  // Newest first for the selector
  runs.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  return runs;
}

/**
 * Build a DagTask array for a selected run.
 *
 * Topology comes from the Planner record's `result.tasks`.
 * Execution status is resolved **per task_id** by filtering all History
 * records that share the same `run_id` — a deterministic foreign key set
 * by the backend at orchestration time.  This is immune to concurrent-run
 * timing issues because the association is explicit, not time-based.
 */
function buildDagTasksForRun(
  run: DagRun,
  allRecords: HistoryRecord[]
): DagTask[] {
  // Filter records belonging to this run by run_id (deterministic match).
  const byTaskId = new Map<string, HistoryRecord>();
  for (const r of allRecords) {
    if (r.run_id !== run.runId) continue;
    const existing = byTaskId.get(r.task_id);
    if (!existing || r.created_at > existing.created_at) {
      byTaskId.set(r.task_id, r);
    }
  }

  return run.topology.map((pt) => ({
    task_id: pt.task_id,
    task_type: pt.task_type,
    role: pt.role ?? null,
    participants: pt.participants,
    mediator: pt.mediator,
    parent_ids: pt.parent_ids,
    dynamic_params: pt.dynamic_params,
    // Status keyed by task_id — correct even when multiple nodes share a role
    status: statusFromRecord(byTaskId.get(pt.task_id)),
  }));
}

/**
 * Fallback visualisation when no structured Planner records exist.
 * Each unique task_id becomes a flat, unconnected node.
 * Status is resolved by task_id (most recent record wins).
 */
function buildFlatDagTasks(records: HistoryRecord[]): DagTask[] {
  const byTaskId = new Map<string, HistoryRecord>();
  for (const r of records) {
    const existing = byTaskId.get(r.task_id);
    if (!existing || r.created_at > existing.created_at) {
      byTaskId.set(r.task_id, r);
    }
  }
  return Array.from(byTaskId.values()).map((r) => ({
    task_id: r.task_id,
    task_type: "Standard" as const,
    role: r.role,
    parent_ids: [],
    status: statusFromRecord(r),
  }));
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DagPage() {
  const [selectedRunId, setSelectedRunId] = useState<string>("");

  // Fetch all records — 3 s polling for live status updates during execution
  const { data: allHistory, error, isLoading } = useSWR<HistoryRecord[]>(
    "/api/history",
    fetcher,
    { refreshInterval: 3000 }
  );

  const dagRuns = allHistory ? extractDagRuns(allHistory) : [];
  const hasRuns = dagRuns.length > 0;

  const selectedRun = dagRuns.find((r) => r.id === selectedRunId);

  const dagTasks =
    selectedRun && allHistory
      ? buildDagTasksForRun(selectedRun, allHistory)
      : !hasRuns && allHistory && allHistory.length > 0
      ? buildFlatDagTasks(allHistory)
      : [];

  return (
    <div className="p-6 flex flex-col h-full gap-4">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-100">DAG ビジュアライザ</h1>
        <p className="text-sm text-gray-500 mt-1">
          Planner が生成したタスクグラフを表示（3 秒ごとに自動更新）
        </p>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center gap-3 text-gray-400">
          <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          <span>読み込み中...</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-900/30 border border-red-500 text-red-300 px-4 py-3 rounded-lg text-sm">
          データの取得に失敗しました。バックエンドの接続を確認してください。
        </div>
      )}

      {/* Run selector — only shown when structured Planner records exist */}
      {hasRuns && (
        <div>
          <label
            htmlFor="run-select"
            className="block text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2"
          >
            DAG 実行を選択
          </label>
          <select
            id="run-select"
            value={selectedRunId}
            onChange={(e) => setSelectedRunId(e.target.value)}
            className="
              bg-gray-900 border border-gray-700 text-gray-200 text-sm
              rounded-lg px-3 py-2 w-full max-w-md
              focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent
            "
          >
            <option value="">— 実行を選択してください —</option>
            {dagRuns.map((run) => (
              <option key={run.id} value={run.id}>
                {new Date(run.createdAt).toLocaleString("ja-JP")}
                {" — "}
                {run.topology.length} タスク（Run: {run.runId.slice(0, 8)}…）
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Fallback notice when no Planner records found */}
      {!isLoading && !hasRuns && allHistory && allHistory.length > 0 && (
        <p className="text-xs text-amber-600">
          Planner の DAG レコードが見つかりません。履歴データをフラット表示しています。
        </p>
      )}

      {/* Visualizer canvas */}
      <div
        className="flex-1 rounded-xl border border-gray-800 bg-gray-900 overflow-hidden p-4"
        style={{ minHeight: 420 }}
      >
        {hasRuns && !selectedRunId ? (
          <div className="flex items-center justify-center h-full text-gray-600 text-sm">
            実行を選択するとグラフが表示されます。
          </div>
        ) : (
          <DagVisualizer tasks={dagTasks} />
        )}
      </div>

      {/* Record count hint */}
      {selectedRun && (
        <p className="text-xs text-gray-700">
          {selectedRun.topology.length} ノード（Run ID: {selectedRun.runId}）
        </p>
      )}
    </div>
  );
}
