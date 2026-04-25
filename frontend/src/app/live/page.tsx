"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import LiveTrace from "../../components/LiveTrace";

function LivePageContent() {
  const searchParams = useSearchParams();
  const runIdFromQuery = searchParams.get("run_id")?.trim() ?? "";

  const [inputRunId, setInputRunId] = useState(runIdFromQuery);
  const [activeRunId, setActiveRunId] = useState(runIdFromQuery);

  useEffect(() => {
    if (!runIdFromQuery) {
      return;
    }

    setInputRunId(runIdFromQuery);
    setActiveRunId(runIdFromQuery);
  }, [runIdFromQuery]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = inputRunId.trim();
    if (trimmed) setActiveRunId(trimmed);
  };

  return (
    <div className="flex flex-col h-screen p-6 gap-4">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white">ライブトレース</h1>
        <p className="text-sm text-gray-500 mt-1">
          run_id を指定してエージェントの思考プロセスをリアルタイムで追跡します
        </p>
      </div>

      {/* run_id input */}
      <form onSubmit={handleSubmit} className="flex gap-2 shrink-0">
        <input
          type="text"
          value={inputRunId}
          onChange={(e) => setInputRunId(e.target.value)}
          placeholder="run_id を入力…"
          className="flex-1 bg-gray-900 border border-gray-700 text-gray-100 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono placeholder-gray-600"
        />
        <button
          type="submit"
          disabled={!inputRunId.trim()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
        >
          接続
        </button>
      </form>

      {/* Terminal area — fills remaining vertical space */}
      <div className="flex-1 min-h-0">
        {activeRunId ? (
          <LiveTrace runId={activeRunId} />
        ) : (
          <div className="bg-black rounded-lg border border-gray-700 h-full flex items-center justify-center">
            <p className="text-gray-600 font-mono text-sm">
              run_id を入力して接続してください
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function LivePage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center p-6 text-sm text-gray-500">
          ライブトレースを読み込み中...
        </div>
      }
    >
      <LivePageContent />
    </Suspense>
  );
}
