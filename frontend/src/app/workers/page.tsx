"use client";

import useSWR from "swr";
import { useState } from "react";

const fetcher = async (url: string) => {
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

type Worker = {
  name: string;
  status?: string;
  active_task_count?: number;
  active_tasks?: any[];
  last_heartbeat?: string | null;
  stats?: Record<string, any>;
};

type TaskItem = {
  id: string;
  name?: string;
  args?: any;
  kwargs?: any;
  worker?: string;
};

type TasksResponse = {
  active?: TaskItem[];
  reserved?: TaskItem[];
};

export default function WorkersPage() {
  const { data: workers, error: workersError, isLoading: workersLoading, mutate: mutateWorkers } = useSWR<Worker[]>(
    "/api/workers",
    fetcher,
    { refreshInterval: 5000 }
  );

  const { data: tasksData, error: tasksError, isLoading: tasksLoading, mutate: mutateTasks } = useSWR<TasksResponse>(
    "/api/workers/tasks",
    fetcher,
    { refreshInterval: 3000 }
  );

  const [revoking, setRevoking] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const revokeTask = async (taskId: string) => {
    if (!confirm("タスクを停止しますか？（強制終了）")) return;
    setRevoking(taskId);
    setMessage(null);
    try {
      const res = await fetch(`/api/workers/tasks/${taskId}/revoke`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      setMessage(`停止完了: ${payload.task_id ?? taskId}`);
      mutateTasks();
      mutateWorkers();
    } catch (e) {
      setMessage(`エラー: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRevoking(null);
    }
  };

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-100">ワーカー管理</h1>
        <p className="text-sm text-gray-500 mt-1">ワーカーの状態と実行中のタスクを確認・制御します（ポーリング）</p>
      </div>

      {message && (
        <div className="mb-4 px-4 py-3 rounded-lg text-sm bg-gray-900 border border-gray-800 text-gray-200">
          {message}
        </div>
      )}

      {/* Workers list */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold text-gray-100 mb-3">ワーカー</h2>
        {workersLoading && <div className="text-gray-400">読み込み中...</div>}
        {workersError && <div className="bg-red-900/30 border border-red-500 text-red-300 px-4 py-3 rounded-lg text-sm">ワーカー情報の取得に失敗しました。</div>}
        {workers && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {workers.map((w) => (
              <div key={w.name} className="p-4 bg-gray-950 border border-gray-800 rounded-lg">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-gray-200">{w.name}</div>
                    <div className="text-xs text-gray-500 mt-1">状態: <span className="font-mono text-xs text-indigo-300">{w.status ?? "不明"}</span></div>
                  </div>
                  <div className="text-sm text-gray-400">
                    アクティブ: <span className="font-mono text-xs text-indigo-300">{w.active_task_count ?? (w.active_tasks?.length ?? 0)}</span>
                  </div>
                </div>
                <div className="mt-3 text-xs text-gray-500 space-y-0.5">
                  {w.stats && (
                    <>
                      <div>ホスト: {w.stats.hostname ?? "-"}</div>
                      <div>プロセス: {w.stats.pid ?? "-"}</div>
                    </>
                  )}
                  <div>最終ハートビート: {
                    w.last_heartbeat
                      ? new Date(w.last_heartbeat).toLocaleString("ja-JP")
                      : "-"
                  }</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Tasks */}
      <section>
        <h2 className="text-lg font-semibold text-gray-100 mb-3">タスク</h2>
        {tasksLoading && <div className="text-gray-400">読み込み中...</div>}
        {tasksError && <div className="bg-red-900/30 border border-red-500 text-red-300 px-4 py-3 rounded-lg text-sm">タスク情報の取得に失敗しました。</div>}
        {tasksData && (
          <div className="overflow-x-auto rounded-xl border border-gray-800">
            <table className="w-full text-sm text-left">
              <thead className="bg-gray-900 border-b border-gray-800">
                <tr>
                  {['タスク ID', '状態', 'ワーカー', '詳細', '操作'].map((h) => (
                    <th key={h} className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-gray-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {(['active','reserved'] as const).map((category) => {
                  const label = category === 'active' ? '実行中' : '予約済み';
                  const rows = (tasksData as any)[category] || [];
                  return rows.length === 0 ? null : rows.map((t: any) => (
                    <tr key={t.id} className="bg-gray-950 hover:bg-gray-900 transition-colors">
                      <td className="px-4 py-3 max-w-[220px]">
                        <span className="font-mono text-xs text-indigo-300 block truncate" title={t.id}>{t.id}</span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400">{label}</td>
                      <td className="px-4 py-3 text-xs text-gray-300">{t.worker ?? "-"}</td>
                      <td className="px-4 py-3 text-xs text-gray-500 max-w-[420px]">{t.name ?? (t.args ? JSON.stringify(t.args) : "-")}</td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <button
                          className="inline-flex items-center px-3 py-1.5 text-xs font-medium bg-red-800 text-red-100 rounded-lg hover:bg-red-700 disabled:opacity-60"
                          onClick={() => revokeTask(t.id)}
                          disabled={!!revoking}
                        >
                          {revoking === t.id ? "停止中..." : "停止"}
                        </button>
                      </td>
                    </tr>
                  ));
                })}
                {((tasksData.active?.length ?? 0) + (tasksData.reserved?.length ?? 0)) === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-sm text-gray-600">実行中/予約中のタスクはありません。</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
