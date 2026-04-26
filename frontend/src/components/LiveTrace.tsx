"use client";

import { useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TraceEvent {
  id: string;
  run_id: string | null;
  task_id: string;
  role: string;
  result: Record<string, unknown> | null;
  progress: Record<string, unknown> | null;
  created_at: string;
}

interface LogLine {
  id: string;
  timestamp: string;
  role: string;
  task_id: string;
  message: string;
  type: "progress" | "result" | "error";
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractMessage(event: TraceEvent): { message: string; type: LogLine["type"] } {
  // Phase 6 Step 3 req: show agent thoughts (progress) first; fall back to result.
  if (event.progress) {
    const prog = event.progress as { thought?: string; message?: string };
    const thought =
      prog.thought ?? prog.message ?? JSON.stringify(event.progress).slice(0, 300);
    return { message: thought, type: "progress" };
  }
  if (event.result) {
    // Evaluate named lifecycle states first so stage-specific payloads that
    // also carry an "error" field are rendered with their precise label
    // rather than falling through to the generic error branch below.
    const lifecycleStatus = (event.result as { status?: string }).status;
    if (lifecycleStatus === "queued") {
      return {
        message: "⏳ キューに追加されました — プランナー起動を待機中",
        type: "progress",
      };
    }
    if (lifecycleStatus === "planner-started") {
      return {
        message: "⚙️ プランナーが起動しました — 推論中…",
        type: "progress",
      };
    }
    if (lifecycleStatus === "enqueue_failed") {
      return {
        message: "ERROR: タスクのキュー追加に失敗しました",
        type: "error",
      };
    }
    if (lifecycleStatus === "planner-failed") {
      const result = event.result as { error?: string; error_type?: string };
      const errMsg = result.error ?? "";
      const isConnectivity = result.error_type === "connectivity";
      const hint = isConnectivity
        ? " ／ 推論バックエンドの起動と疎通を確認してください（ワーカー管理画面を参照）"
        : "";
      return {
        message: `ERROR: プランナーが失敗しました${errMsg ? ` — ${errMsg}` : ""}${hint}`,
        type: "error",
      };
    }
    if (lifecycleStatus === "orchestration-failed") {
      const errMsg = (event.result as { error?: string }).error ?? "";
      return {
        message: `ERROR: オーケストレーションが失敗しました${errMsg ? ` — ${errMsg}` : ""}`,
        type: "error",
      };
    }
    // Generic fallback: non-lifecycle rows that carry an error field.
    if ((event.result as { error?: unknown }).error) {
      const err = (event.result as { error: unknown }).error;
      return {
        message: `ERROR: ${typeof err === "string" ? err : JSON.stringify(err)}`,
        type: "error",
      };
    }
    const res = event.result as { summary?: string; output?: string };
    const summary = res.summary ?? res.output ?? JSON.stringify(event.result).slice(0, 300);
    return { message: `✓ ${summary}`, type: "result" };
  }
  return { message: "(記録あり — コンテンツなし)", type: "progress" };
}

function toTimestamp(iso: string): string {
  const d = new Date(iso);
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");
}

function toLogLine(event: TraceEvent): LogLine {
  const { message, type } = extractMessage(event);
  return {
    id: event.id,
    timestamp: toTimestamp(event.created_at),
    role: event.role,
    task_id: event.task_id,
    message,
    type,
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface LiveTraceProps {
  /** The run_id to stream. Changing this value reconnects the EventSource. */
  runId: string;
}

export default function LiveTrace({ runId }: LiveTraceProps) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [connected, setConnected] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const seenIds = useRef<Set<string>>(new Set());

  // Connect / reconnect whenever runId changes.
  useEffect(() => {
    if (!runId) return;

    setLines([]);
    setConnected(false);
    seenIds.current.clear();

    const url = `/api/stream/progress?run_id=${encodeURIComponent(runId)}`;
    const es = new EventSource(url);

    es.onopen = () => setConnected(true);

    es.onmessage = (evt) => {
      try {
        const event: TraceEvent = JSON.parse(evt.data as string);
        if (seenIds.current.has(event.id)) return;
        seenIds.current.add(event.id);
        setLines((prev) => [...prev, toLogLine(event)]);
      } catch {
        // Ignore malformed SSE frames (e.g. heartbeat comments reach here
        // only if the browser mistakenly fires onmessage for comment lines,
        // which the spec forbids — safe to silently discard).
      }
    };

    es.onerror = () => {
      // Do NOT call es.close() — let EventSource auto-reconnect at its default
      // retry interval (~3 s).  We only show a transient "reconnecting" status.
      setConnected(false);
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [runId]);

  // Auto-scroll to the bottom when new lines arrive.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  const lineColor = (type: LogLine["type"]) => {
    if (type === "error") return "text-red-400";
    if (type === "result") return "text-emerald-400";
    return "text-green-400";
  };

  return (
    <div className="bg-black rounded-lg border border-gray-700 h-full flex flex-col overflow-hidden">
      {/* Status bar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800 text-xs shrink-0">
        <span
          className={`w-2 h-2 rounded-full ${
            connected ? "bg-green-400 animate-pulse" : "bg-gray-600"
          }`}
        />
        <span className={connected ? "text-green-400" : "text-yellow-400"}>
          {connected ? "接続中" : "再接続中…"}
        </span>
        <span className="text-gray-600 ml-2 font-mono truncate">{runId}</span>
        <span className="ml-auto text-gray-700">{lines.length} イベント</span>
      </div>

      {/* Terminal body */}
      <div className="flex-1 overflow-y-auto p-4 font-mono text-sm leading-relaxed">
        {lines.length === 0 && (
          <p className="text-gray-600">
            {connected
              ? "エージェントからのイベントを待機中…"
              : "接続を確立しています…"}
          </p>
        )}

        {lines.map((line) => (
          <div key={line.id} className="flex gap-2 flex-wrap">
            <span className="text-gray-600 shrink-0">[{line.timestamp}]</span>
            <span className="text-yellow-400 shrink-0">{line.role}</span>
            <span className="text-gray-500 shrink-0">/{line.task_id}</span>
            <span className={lineColor(line.type)}>{line.message}</span>
          </div>
        ))}



        {/* Sentinel element for auto-scroll */}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
