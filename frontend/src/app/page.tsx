"use client";

import useSWR from "swr";

// HistoryRecord mirrors the HistoryResponse schema from the backend
interface HistoryRecord {
  id: string;
  task_id: string;
  role: string;
  result: Record<string, unknown> | null;
  progress: Record<string, unknown> | null;
  created_at: string;
}

const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

export default function DashboardPage() {
  // Fetch from /api/history/ which is proxied by Next.js to the FastAPI backend
  const { data, error, isLoading } = useSWR<HistoryRecord[]>(
    "/api/history",
    fetcher,
    { refreshInterval: 5000 }
  );

  return (
    <div className="p-6">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-100">実行履歴</h1>
        <p className="text-sm text-gray-500 mt-1">
          エージェントタスクの実行ログ（5秒ごとに自動更新）
        </p>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center gap-3 text-gray-400 py-8">
          <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          <span>読み込み中...</span>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="bg-red-900/30 border border-red-500 text-red-300 px-4 py-3 rounded-lg text-sm">
          データの取得に失敗しました。バックエンドの接続を確認してください。
        </div>
      )}

      {/* History table */}
      {data && (
        <div className="overflow-x-auto rounded-xl border border-gray-800">
          <table className="w-full text-sm text-left">
            <thead className="bg-gray-900 border-b border-gray-800">
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
                    className="bg-gray-950 hover:bg-gray-900 transition-colors"
                  >
                    {/* Task ID */}
                    <td className="px-4 py-3 max-w-[180px]">
                      <span
                        className="font-mono text-xs text-indigo-300 block truncate"
                        title={record.task_id}
                      >
                        {record.task_id}
                      </span>
                    </td>

                    {/* Role badge */}
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-900/50 text-indigo-300 border border-indigo-700/60">
                        {record.role}
                      </span>
                    </td>

                    {/* Result preview */}
                    <td className="px-4 py-3 max-w-[340px]">
                      <span
                        className="font-mono text-xs text-gray-500 block truncate"
                        title={record.result ? JSON.stringify(record.result) : undefined}
                      >
                        {record.result
                          ? JSON.stringify(record.result).slice(0, 120)
                          : <span className="text-gray-700">—</span>}
                      </span>
                    </td>

                    {/* Timestamp */}
                    <td className="px-4 py-3 text-xs text-gray-600 whitespace-nowrap">
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
        <p className="mt-3 text-xs text-gray-700">
          {data.length} 件のレコード
        </p>
      )}
    </div>
  );
}
