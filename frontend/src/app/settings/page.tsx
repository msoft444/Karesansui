"use client";

import { useState } from "react";
import useSWR from "swr";

// SettingRecord mirrors the SettingResponse schema from the backend
interface SettingRecord {
  key: string;
  value: unknown;
  updated_at: string;
}

const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

export default function SettingsPage() {
  // Fetch from /api/settings/ which is proxied by Next.js to the FastAPI backend
  const { data, error, isLoading, mutate } = useSWR<SettingRecord[]>(
    "/api/settings/",
    fetcher
  );

  // draft values keyed by setting.key; absent means "not edited yet"
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  /** Returns the display value for a setting row — draft first, then server value */
  function displayValue(record: SettingRecord): string {
    return record.key in drafts
      ? drafts[record.key]
      : JSON.stringify(record.value);
  }

  function handleChange(settingKey: string, raw: string) {
    setDrafts((prev) => ({ ...prev, [settingKey]: raw }));
    setFieldErrors((prev) => ({ ...prev, [settingKey]: "" }));
  }

  async function handleSave(settingKey: string) {
    const raw = drafts[settingKey];
    if (raw === undefined) return;

    // Validate JSON before sending
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      setFieldErrors((prev) => ({
        ...prev,
        [settingKey]: "JSON 形式で入力してください（例: 5、true、\"text\"）",
      }));
      return;
    }

    setSaving((prev) => ({ ...prev, [settingKey]: true }));
    try {
      const res = await fetch(`/api/settings/${encodeURIComponent(settingKey)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: parsed }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Clear draft and refresh the cached data
      await mutate();
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[settingKey];
        return next;
      });
    } catch {
      setFieldErrors((prev) => ({
        ...prev,
        [settingKey]: "保存に失敗しました。再度お試しください。",
      }));
    } finally {
      setSaving((prev) => ({ ...prev, [settingKey]: false }));
    }
  }

  return (
    <div className="p-6 max-w-3xl">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-100">グローバル設定</h1>
        <p className="text-sm text-gray-500 mt-1">
          システム全体の動作パラメータを管理します。値は JSON 形式で保存されます。
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
          設定の取得に失敗しました。バックエンドの接続を確認してください。
        </div>
      )}

      {/* Settings cards */}
      {data && (
        <div className="space-y-4">
          {data.length === 0 ? (
            <p className="text-sm text-gray-600 py-8 text-center">
              設定データがありません。
            </p>
          ) : (
            data.map((record) => {
              const isDirty = record.key in drafts;
              const isSaving = !!saving[record.key];

              return (
                <div
                  key={record.key}
                  className={`rounded-xl border p-4 transition-colors ${
                    isDirty
                      ? "bg-gray-900 border-indigo-700/60"
                      : "bg-gray-900 border-gray-800"
                  }`}
                >
                  {/* Setting header */}
                  <div className="flex items-center justify-between mb-3">
                    <span className="font-mono text-sm font-semibold text-indigo-300">
                      {record.key}
                    </span>
                    <span className="text-xs text-gray-700">
                      最終更新: {new Date(record.updated_at).toLocaleString("ja-JP")}
                    </span>
                  </div>

                  {/* Input row */}
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={displayValue(record)}
                      onChange={(e) => handleChange(record.key, e.target.value)}
                      className="flex-1 bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg px-3 py-2 font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-colors"
                      aria-label={`${record.key} の値`}
                    />
                    <button
                      type="button"
                      onClick={() => handleSave(record.key)}
                      disabled={!isDirty || isSaving}
                      className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-800 disabled:text-gray-600 disabled:cursor-default text-white text-sm font-medium rounded-lg transition-colors whitespace-nowrap"
                    >
                      {isSaving ? "保存中..." : "保存"}
                    </button>
                  </div>

                  {/* Inline error */}
                  {fieldErrors[record.key] && (
                    <p className="mt-2 text-xs text-red-400">
                      {fieldErrors[record.key]}
                    </p>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
