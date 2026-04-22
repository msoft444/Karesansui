"use client";

import { Fragment, useCallback, useRef, useState } from "react";
import useSWR from "swr";

// ---------------------------------------------------------------------------
// Types — mirror backend schemas
// ---------------------------------------------------------------------------

interface SectionSummary {
  id: string;
  section_title: string;
  level: number;
  start_page: number;
  end_page: number;
}

interface KnowledgeDocument {
  id: string;
  filename: string;
  status: string;
  error_message: string | null;
  page_count: number | null;
  chunk_count: number | null;
  github_path: string | null;
  created_at: string;
  updated_at: string;
  sections: SectionSummary[];
}

interface ChunkResult {
  id: string;
  source_pdf: string;
  section_title: string;
  level: number;
  start_page: number;
  end_page: number;
  content: string;
  distance: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const IN_PROGRESS_STATUSES = new Set([
  "uploading",
  "splitting",
  "converting",
  "vectorizing",
  "syncing",
]);

const STATUS_LABEL: Record<string, string> = {
  uploading: "アップロード中",
  splitting: "分割中",
  converting: "変換中",
  vectorizing: "ベクトル化中",
  syncing: "同期中",
  completed: "完了",
  failed: "失敗",
};

const STATUS_COLOR: Record<string, string> = {
  uploading: "bg-blue-900 text-blue-300",
  splitting: "bg-yellow-900 text-yellow-300",
  converting: "bg-orange-900 text-orange-300",
  vectorizing: "bg-purple-900 text-purple-300",
  syncing: "bg-cyan-900 text-cyan-300",
  completed: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
};

// ---------------------------------------------------------------------------
// Fetcher
// ---------------------------------------------------------------------------

const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const colorClass = STATUS_COLOR[status] ?? "bg-gray-800 text-gray-300";
  const label = STATUS_LABEL[status] ?? status;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colorClass}`}
    >
      {IN_PROGRESS_STATUSES.has(status) && (
        <span className="mr-1 inline-block w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
      )}
      {label}
    </span>
  );
}

function ExpandableChunk({ chunk }: { chunk: ChunkResult }) {
  const [open, setOpen] = useState(false);
  const score = (1 - chunk.distance).toFixed(3);
  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left text-sm hover:bg-gray-800 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-gray-500 text-xs w-6 text-right shrink-0">
            {"　".repeat(Math.max(0, chunk.level - 1))}
          </span>
          <span className="font-medium text-gray-200 truncate">
            {chunk.section_title}
          </span>
          <span className="text-gray-500 text-xs shrink-0">
            p.{chunk.start_page}–{chunk.end_page}
          </span>
        </div>
        <div className="flex items-center gap-3 shrink-0 ml-2">
          <span className="text-green-400 text-xs">スコア {score}</span>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className={`w-4 h-4 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="m19.5 8.25-7.5 7.5-7.5-7.5"
            />
          </svg>
        </div>
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1 border-t border-gray-700 bg-gray-900">
          <pre className="text-xs text-gray-300 whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto">
            {chunk.content}
          </pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function KnowledgePage() {
  // --- SWR: document list ---
  // Poll every 3 s while any document is still being processed.
  const {
    data: documents,
    error: listError,
    isLoading: listLoading,
    mutate: mutateList,
  } = useSWR<KnowledgeDocument[]>("/api/knowledge/", fetcher, {
    refreshInterval: (docs) => {
      if (!docs) return 3000;
      const hasInProgress = docs.some((d) => IN_PROGRESS_STATUSES.has(d.status));
      return hasInProgress ? 3000 : 0;
    },
  });

  // --- Upload state ---
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");

  // --- Delete state ---
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // --- Section expand state ---
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null);
  function toggleExpand(id: string) {
    setExpandedDocId((prev) => (prev === id ? null : id));
  }

  // --- Search state ---
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTopK, setSearchTopK] = useState(5);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchResults, setSearchResults] = useState<ChunkResult[] | null>(null);

  // ---- Upload helpers ----

  async function uploadFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUploadError("PDF ファイルのみアップロードできます。");
      return;
    }
    setUploadError("");
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/knowledge/upload", {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `HTTP ${res.status}`
        );
      }
      await mutateList();
    } catch (err) {
      setUploadError(
        err instanceof Error
          ? err.message
          : "アップロードに失敗しました。再度お試しください。"
      );
    } finally {
      setUploading(false);
    }
  }

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) uploadFile(file);
      // Reset input so the same file can be re-selected if needed.
      e.target.value = "";
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) uploadFile(file);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Delete handler ----

  async function handleDelete(id: string, filename: string) {
    if (
      !window.confirm(
        `「${filename}」を削除しますか？\nベクトルデータ・GitHub ファイル・ローカルデータがすべて削除されます。この操作は元に戻せません。`
      )
    )
      return;
    setDeletingId(id);
    try {
      const res = await fetch(`/api/knowledge/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await mutateList();
    } catch {
      alert("削除に失敗しました。再度お試しください。");
    } finally {
      setDeletingId(null);
    }
  }

  // ---- Search handler ----

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearchError("");
    setSearchLoading(true);
    setSearchResults(null);
    try {
      const res = await fetch("/api/knowledge/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: searchQuery.trim(), top_k: searchTopK }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `HTTP ${res.status}`
        );
      }
      const data = await res.json();
      setSearchResults((data as { results: ChunkResult[] }).results);
    } catch (err) {
      setSearchError(
        err instanceof Error
          ? err.message
          : "検索に失敗しました。再度お試しください。"
      );
    } finally {
      setSearchLoading(false);
    }
  }

  // ---- Render helpers ----

  function formatDate(iso: string) {
    try {
      return new Date(iso).toLocaleString("ja-JP", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  // ---- Render ----

  return (
    <main className="p-6 space-y-8 max-w-6xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-white">ナレッジベース</h1>
        <p className="text-sm text-gray-500 mt-1">
          PDF ドキュメントのアップロード・管理・セマンティック検索
        </p>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Upload Area                                                          */}
      {/* ------------------------------------------------------------------ */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
          ドキュメントのアップロード
        </h2>

        <div
          role="button"
          tabIndex={0}
          onClick={() => !uploading && fileInputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ")
              !uploading && fileInputRef.current?.click();
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`relative border-2 border-dashed rounded-xl p-10 text-center transition-colors cursor-pointer select-none
            ${dragOver ? "border-blue-500 bg-blue-950/30" : "border-gray-700 hover:border-gray-600"}
            ${uploading ? "opacity-60 cursor-not-allowed" : ""}`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,application/pdf"
            className="hidden"
            onChange={handleFileChange}
            disabled={uploading}
          />
          <div className="flex flex-col items-center gap-3">
            {uploading ? (
              <>
                <svg
                  className="w-10 h-10 text-blue-400 animate-spin"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v8z"
                  />
                </svg>
                <p className="text-sm text-blue-400">アップロード中...</p>
              </>
            ) : (
              <>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className={`w-10 h-10 ${dragOver ? "text-blue-400" : "text-gray-600"} transition-colors`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
                  />
                </svg>
                <div>
                  <p className="text-sm text-gray-300">
                    ここにファイルをドラッグ＆ドロップ
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    または クリックして PDF を選択（PDF のみ）
                  </p>
                </div>
              </>
            )}
          </div>
        </div>

        {uploadError && (
          <p className="mt-2 text-sm text-red-400">{uploadError}</p>
        )}
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Document Library                                                     */}
      {/* ------------------------------------------------------------------ */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
          ドキュメントライブラリ
        </h2>

        {listLoading && (
          <p className="text-sm text-gray-500">読み込み中...</p>
        )}
        {listError && !listLoading && (
          <p className="text-sm text-red-400">
            一覧の取得に失敗しました: {listError.message}
          </p>
        )}

        {!listLoading && documents !== undefined && documents.length === 0 && (
          <p className="text-sm text-gray-600">
            登録されたドキュメントはありません。
          </p>
        )}

        {documents && documents.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left">
                  <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">
                    ファイル名
                  </th>
                  <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">
                    ステータス
                  </th>
                  <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">
                    ページ数
                  </th>
                  <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">
                    チャンク数
                  </th>
                  <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">
                    アップロード日時
                  </th>
                  <th className="px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {documents.map((doc) => {
                  const isExpanded = expandedDocId === doc.id;
                  const hasSections = doc.sections.length > 0;
                  return (
                    <Fragment key={doc.id}>
                      <tr className="hover:bg-gray-900/40 transition-colors">
                        <td className="px-4 py-3 text-gray-200 max-w-xs">
                          <div className="flex items-start gap-2">
                            {hasSections ? (
                              <button
                                type="button"
                                onClick={() => toggleExpand(doc.id)}
                                className="mt-0.5 shrink-0 text-gray-500 hover:text-gray-300 transition-colors"
                                aria-label={isExpanded ? "セクションを閉じる" : "セクションを開く"}
                              >
                                <svg
                                  xmlns="http://www.w3.org/2000/svg"
                                  className={`w-4 h-4 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                                  fill="none"
                                  viewBox="0 0 24 24"
                                  stroke="currentColor"
                                  strokeWidth={1.5}
                                >
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    d="m8.25 4.5 7.5 7.5-7.5 7.5"
                                  />
                                </svg>
                              </button>
                            ) : (
                              <span className="w-4 shrink-0" />
                            )}
                            <div className="min-w-0">
                              <div className="truncate">{doc.filename}</div>
                              {doc.error_message && (
                                <div className="mt-0.5 text-xs text-red-400 truncate">
                                  {doc.error_message}
                                </div>
                              )}
                              {doc.github_path && (
                                <div className="mt-0.5 text-xs text-gray-600 truncate">
                                  GitHub: {doc.github_path}
                                </div>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={doc.status} />
                        </td>
                        <td className="px-4 py-3 text-gray-400 text-right">
                          {doc.page_count ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-gray-400 text-right">
                          {doc.chunk_count ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                          {formatDate(doc.created_at)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleDelete(doc.id, doc.filename)}
                            disabled={deletingId === doc.id}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-400 border border-red-900 rounded-lg hover:bg-red-950 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {deletingId === doc.id ? (
                              "削除中..."
                            ) : (
                              <>
                                <svg
                                  xmlns="http://www.w3.org/2000/svg"
                                  className="w-3.5 h-3.5"
                                  fill="none"
                                  viewBox="0 0 24 24"
                                  stroke="currentColor"
                                  strokeWidth={1.5}
                                >
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
                                  />
                                </svg>
                                削除
                              </>
                            )}
                          </button>
                        </td>
                      </tr>
                      {isExpanded && hasSections && (
                        <tr className="bg-gray-900/60">
                          <td colSpan={6} className="px-6 pb-4 pt-2">
                            <p className="text-xs text-gray-500 mb-2">
                              章・節 ({doc.sections.length} 件)
                            </p>
                            <ul className="space-y-1">
                              {doc.sections.map((section) => (
                                <li
                                  key={section.id}
                                  className="flex items-baseline gap-2 text-xs"
                                  style={{
                                    paddingLeft: `${(section.level - 1) * 16}px`,
                                  }}
                                >
                                  <span className="text-gray-600 shrink-0">└</span>
                                  <span className="text-gray-300 truncate">
                                    {section.section_title}
                                  </span>
                                  <span className="text-gray-600 shrink-0 whitespace-nowrap">
                                    p.{section.start_page}–{section.end_page}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Search Panel                                                         */}
      {/* ------------------------------------------------------------------ */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">
          セマンティック検索
        </h2>

        <form onSubmit={handleSearch} className="flex gap-3 items-start">
          <div className="flex-1">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="検索クエリを入力..."
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-gray-500"
              disabled={searchLoading}
            />
          </div>
          <div className="flex items-center gap-2">
            <label
              htmlFor="top-k"
              className="text-xs text-gray-500 whitespace-nowrap"
            >
              件数
            </label>
            <select
              id="top-k"
              value={searchTopK}
              onChange={(e) => setSearchTopK(Number(e.target.value))}
              disabled={searchLoading}
              className="bg-gray-900 border border-gray-700 rounded-lg px-2 py-2.5 text-sm text-gray-200 focus:outline-none focus:border-gray-500"
            >
              {[3, 5, 10, 20].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={searchLoading || !searchQuery.trim()}
            className="px-4 py-2.5 text-sm bg-blue-700 text-white rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {searchLoading ? "検索中..." : "検索"}
          </button>
        </form>

        {searchError && (
          <p className="mt-2 text-sm text-red-400">{searchError}</p>
        )}

        {searchResults !== null && (
          <div className="mt-4 space-y-2">
            {searchResults.length === 0 ? (
              <p className="text-sm text-gray-600">
                該当するチャンクが見つかりませんでした。
              </p>
            ) : (
              <>
                <p className="text-xs text-gray-500">
                  {searchResults.length} 件の結果
                </p>
                {searchResults.map((chunk) => (
                  <ExpandableChunk key={chunk.id} chunk={chunk} />
                ))}
              </>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
