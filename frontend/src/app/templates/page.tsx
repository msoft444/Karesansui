"use client";

import { Fragment, useState } from "react";
import useSWR from "swr";

// RoleTemplate mirrors the RoleTemplateResponse schema from the backend
interface RoleTemplate {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  tools: string[];
  default_params: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface FormState {
  name: string;
  description: string;
  system_prompt: string;
  tools: string; // comma-separated string for the text input
  default_params: string; // raw JSON string for the textarea
}

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  system_prompt: "",
  tools: "",
  default_params: "{}",
};

const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

export default function TemplatesPage() {
  const { data, error, isLoading, mutate } = useSWR<RoleTemplate[]>(
    "/api/templates",
    fetcher
  );

  // --- Create modal state ---
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<FormState>(EMPTY_FORM);
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  // --- Inline edit state (row-level) ---
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<FormState>(EMPTY_FORM);
  const [editError, setEditError] = useState("");
  const [saving, setSaving] = useState(false);

  // --- Delete state ---
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // ---- Handlers ----

  function openCreate() {
    setCreateForm(EMPTY_FORM);
    setCreateError("");
    setCreateOpen(true);
  }

  function startEdit(template: RoleTemplate) {
    setEditingId(template.id);
    setEditForm({
      name: template.name,
      description: template.description,
      system_prompt: template.system_prompt,
      tools: template.tools.join(", "),
      default_params: JSON.stringify(template.default_params, null, 2),
    });
    setEditError("");
  }

  function cancelEdit() {
    setEditingId(null);
    setEditError("");
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError("");
    let parsedParams: Record<string, unknown>;
    try {
      parsedParams = JSON.parse(createForm.default_params);
    } catch {
      setCreateError("デフォルトパラメータは有効な JSON 形式で入力してください。");
      return;
    }
    const payload = {
      name: createForm.name.trim(),
      description: createForm.description.trim(),
      system_prompt: createForm.system_prompt.trim(),
      tools: createForm.tools
        .split(",")
        .map((t) => t.trim())
        .filter((t) => t.length > 0),
      default_params: parsedParams,
    };
    if (!payload.name) {
      setCreateError("テンプレート名は必須です。");
      return;
    }
    setCreating(true);
    try {
      const res = await fetch("/api/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `HTTP ${res.status}`
        );
      }
      await mutate();
      setCreateOpen(false);
      setCreateForm(EMPTY_FORM);
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "作成に失敗しました。再度お試しください。"
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleSaveEdit(id: string) {
    setEditError("");
    let parsedParams: Record<string, unknown>;
    try {
      parsedParams = JSON.parse(editForm.default_params);
    } catch {
      setEditError("デフォルトパラメータは有効な JSON 形式で入力してください。");
      return;
    }
    const payload = {
      name: editForm.name.trim(),
      description: editForm.description.trim(),
      system_prompt: editForm.system_prompt.trim(),
      tools: editForm.tools
        .split(",")
        .map((t) => t.trim())
        .filter((t) => t.length > 0),
      default_params: parsedParams,
    };
    if (!payload.name) {
      setEditError("テンプレート名は必須です。");
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(`/api/templates/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `HTTP ${res.status}`
        );
      }
      await mutate();
      setEditingId(null);
    } catch (err) {
      setEditError(
        err instanceof Error ? err.message : "保存に失敗しました。再度お試しください。"
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (
      !window.confirm(
        "このテンプレートを削除しますか？この操作は元に戻せません。"
      )
    )
      return;
    setDeletingId(id);
    try {
      const res = await fetch(`/api/templates/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (editingId === id) setEditingId(null);
      await mutate();
    } catch {
      alert("削除に失敗しました。再度お試しください。");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="p-6 max-w-6xl">
      {/* ページヘッダー */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">役割テンプレート</h1>
          <p className="text-sm text-gray-500 mt-1">
            プランナーが DAG 構築時に使用するエージェントの役割テンプレートを管理します。
          </p>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 4.5v15m7.5-7.5h-15"
            />
          </svg>
          新規作成
        </button>
      </div>

      {/* 読み込み中 */}
      {isLoading && (
        <div className="flex items-center gap-3 text-gray-400 py-8">
          <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          <span>読み込み中...</span>
        </div>
      )}

      {/* エラー */}
      {error && (
        <div className="bg-red-900/30 border border-red-500 text-red-300 px-4 py-3 rounded-lg text-sm">
          テンプレートの取得に失敗しました。バックエンドの接続を確認してください。
        </div>
      )}

      {/* テンプレート一覧テーブル */}
      {data && (
        <div className="overflow-x-auto">
          {data.length === 0 ? (
            <p className="text-sm text-gray-600 py-8 text-center">
              テンプレートがありません。「新規作成」から追加してください。
            </p>
          ) : (
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-gray-700">
                  <th className="text-left px-4 py-2 text-gray-400 font-medium w-36">
                    名前
                  </th>
                  <th className="text-left px-4 py-2 text-gray-400 font-medium">
                    説明
                  </th>
                  <th className="text-left px-4 py-2 text-gray-400 font-medium w-36">
                    ツール
                  </th>
                  <th className="text-left px-4 py-2 text-gray-400 font-medium w-52">
                    デフォルトパラメータ
                  </th>
                  <th className="text-right px-4 py-2 text-gray-400 font-medium w-28">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.map((template) => (
                  <Fragment key={template.id}>
                    {/* --- 表示行 --- */}
                    <tr
                      className={`border-b border-gray-800 transition-colors ${
                        editingId === template.id
                          ? "bg-gray-800/60"
                          : "hover:bg-gray-800/40"
                      }`}
                    >
                      <td className="px-4 py-3 font-mono text-indigo-300 whitespace-nowrap align-top">
                        {template.name}
                      </td>
                      <td className="px-4 py-3 text-gray-300 align-top">
                        <span className="line-clamp-2">
                          {template.description || (
                            <span className="text-gray-600">—</span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-3 align-top">
                        {template.tools.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {template.tools.map((t) => (
                              <span
                                key={t}
                                className="px-2 py-0.5 text-xs bg-gray-700 text-gray-300 rounded"
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-gray-600 text-xs">なし</span>
                        )}
                      </td>
                      <td className="px-4 py-3 align-top">
                        {Object.keys(template.default_params).length > 0 ? (
                          <pre className="text-xs text-gray-400 font-mono whitespace-pre-wrap break-all max-h-16 overflow-y-auto bg-gray-800/50 rounded p-1">
                            {JSON.stringify(template.default_params, null, 1)}
                          </pre>
                        ) : (
                          <span className="text-gray-600 text-xs">なし</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right whitespace-nowrap align-top">
                        {editingId === template.id ? (
                          <span className="text-xs text-indigo-400">編集中</span>
                        ) : (
                          <>
                            <button
                              onClick={() => startEdit(template)}
                              className="px-3 py-1 text-xs text-indigo-300 hover:text-indigo-100 border border-indigo-800 hover:border-indigo-600 rounded transition-colors mr-2"
                            >
                              編集
                            </button>
                            <button
                              onClick={() => handleDelete(template.id)}
                              disabled={deletingId === template.id}
                              className="px-3 py-1 text-xs text-red-400 hover:text-red-200 border border-red-900 hover:border-red-600 rounded transition-colors disabled:opacity-50"
                            >
                              {deletingId === template.id ? "削除中..." : "削除"}
                            </button>
                          </>
                        )}
                      </td>
                    </tr>

                    {/* --- インライン編集行（該当行の直下に展開） --- */}
                    {editingId === template.id && (
                      <tr className="border-b border-indigo-800/40 bg-gray-800/30">
                        <td colSpan={5} className="px-4 py-4">
                          {editError && (
                            <div className="mb-3 bg-red-900/30 border border-red-500 text-red-300 px-4 py-2 rounded-lg text-xs">
                              {editError}
                            </div>
                          )}
                          <div className="grid grid-cols-2 gap-3">
                            {/* テンプレート名 */}
                            <div>
                              <label className="block text-xs text-gray-400 mb-1">
                                テンプレート名{" "}
                                <span className="text-red-400">*</span>
                              </label>
                              <input
                                type="text"
                                value={editForm.name}
                                onChange={(e) =>
                                  setEditForm((p) => ({
                                    ...p,
                                    name: e.target.value,
                                  }))
                                }
                                className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-indigo-500"
                              />
                            </div>
                            {/* 説明 */}
                            <div>
                              <label className="block text-xs text-gray-400 mb-1">
                                説明
                              </label>
                              <input
                                type="text"
                                value={editForm.description}
                                onChange={(e) =>
                                  setEditForm((p) => ({
                                    ...p,
                                    description: e.target.value,
                                  }))
                                }
                                className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-indigo-500"
                              />
                            </div>
                            {/* システムプロンプト */}
                            <div className="col-span-2">
                              <label className="block text-xs text-gray-400 mb-1">
                                システムプロンプト
                              </label>
                              <textarea
                                value={editForm.system_prompt}
                                onChange={(e) =>
                                  setEditForm((p) => ({
                                    ...p,
                                    system_prompt: e.target.value,
                                  }))
                                }
                                rows={3}
                                className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-indigo-500 resize-y font-mono"
                              />
                            </div>
                            {/* ツール */}
                            <div>
                              <label className="block text-xs text-gray-400 mb-1">
                                ツール{" "}
                                <span className="text-gray-600">
                                  （カンマ区切り）
                                </span>
                              </label>
                              <input
                                type="text"
                                value={editForm.tools}
                                onChange={(e) =>
                                  setEditForm((p) => ({
                                    ...p,
                                    tools: e.target.value,
                                  }))
                                }
                                className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-indigo-500"
                              />
                            </div>
                            {/* デフォルトパラメータ */}
                            <div>
                              <label className="block text-xs text-gray-400 mb-1">
                                デフォルトパラメータ{" "}
                                <span className="text-gray-600">（JSON）</span>
                              </label>
                              <textarea
                                value={editForm.default_params}
                                onChange={(e) =>
                                  setEditForm((p) => ({
                                    ...p,
                                    default_params: e.target.value,
                                  }))
                                }
                                rows={3}
                                className="w-full bg-gray-900 border border-gray-600 rounded px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-indigo-500 resize-y font-mono"
                              />
                            </div>
                          </div>
                          {/* インライン編集ボタン */}
                          <div className="flex justify-end gap-2 mt-3">
                            <button
                              type="button"
                              onClick={cancelEdit}
                              className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 border border-gray-700 rounded transition-colors"
                            >
                              キャンセル
                            </button>
                            <button
                              type="button"
                              onClick={() => handleSaveEdit(template.id)}
                              disabled={saving}
                              className="px-3 py-1.5 text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white rounded transition-colors disabled:opacity-50"
                            >
                              {saving ? "保存中..." : "保存"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* 新規作成モーダル */}
      {createOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
          <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700 shrink-0">
              <h2 className="text-lg font-semibold text-gray-100">
                新規テンプレートを作成
              </h2>
              <button
                onClick={() => setCreateOpen(false)}
                className="text-gray-500 hover:text-gray-300 transition-colors"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="w-5 h-5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>
            <form
              onSubmit={handleCreate}
              className="flex-1 overflow-y-auto px-6 py-4 space-y-4"
            >
              {createError && (
                <div className="bg-red-900/30 border border-red-500 text-red-300 px-4 py-3 rounded-lg text-sm">
                  {createError}
                </div>
              )}
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  テンプレート名 <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={createForm.name}
                  onChange={(e) =>
                    setCreateForm((p) => ({ ...p, name: e.target.value }))
                  }
                  placeholder="例: Data_Gatherer"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">説明</label>
                <input
                  type="text"
                  value={createForm.description}
                  onChange={(e) =>
                    setCreateForm((p) => ({
                      ...p,
                      description: e.target.value,
                    }))
                  }
                  placeholder="例: 情報収集エージェント"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  システムプロンプト
                </label>
                <textarea
                  value={createForm.system_prompt}
                  onChange={(e) =>
                    setCreateForm((p) => ({
                      ...p,
                      system_prompt: e.target.value,
                    }))
                  }
                  rows={4}
                  placeholder="例: You are a research agent..."
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500 resize-y font-mono"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  ツール{" "}
                  <span className="text-gray-600 text-xs">
                    （カンマ区切りで複数入力）
                  </span>
                </label>
                <input
                  type="text"
                  value={createForm.tools}
                  onChange={(e) =>
                    setCreateForm((p) => ({ ...p, tools: e.target.value }))
                  }
                  placeholder="例: search, summarize, translate"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  デフォルトパラメータ{" "}
                  <span className="text-gray-600 text-xs">（JSON 形式）</span>
                </label>
                <textarea
                  value={createForm.default_params}
                  onChange={(e) =>
                    setCreateForm((p) => ({
                      ...p,
                      default_params: e.target.value,
                    }))
                  }
                  rows={3}
                  placeholder='例: {"temperature": 0.7, "locale": "ja"}'
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500 resize-y font-mono"
                />
              </div>
              <div className="flex justify-end gap-3 pt-2 pb-1">
                <button
                  type="button"
                  onClick={() => setCreateOpen(false)}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 border border-gray-700 rounded-lg transition-colors"
                >
                  キャンセル
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
                >
                  {creating ? "作成中..." : "作成"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
