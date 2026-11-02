/**
 * 删除扫描目录弹窗。
 * 提供“仅删除数据”和“删除视频及数据”两种方式；后者会同时删除磁盘文件。
 * 演员资料作为独立实体保留，只清理该目录下的影片记录。
 */
import { useState } from "react";
import { api, type DeleteScanRootResult, type ScanRoot } from "../api";
import { errorMessage } from "../format";
import { TrashIcon } from "./Icons";
import { Modal } from "./Modal";

export function RootDeleteModal({
  root,
  onClose,
  onDeleted,
}: {
  root: ScanRoot;
  onClose: () => void;
  onDeleted: (result: DeleteScanRootResult) => void;
}) {
  const [mode, setMode] = useState<"data" | "files">("data");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.deleteRootData(root.id, mode === "files");
      onDeleted(result);
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="删除扫描目录"
      subtitle={root.path}
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg border border-zinc-200 px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100 disabled:opacity-40 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void remove()}
            disabled={busy}
            className="rounded-lg bg-red-500 px-4 py-2 text-sm font-semibold text-white hover:bg-red-400 disabled:opacity-40"
          >
            {busy ? "删除中…" : mode === "data" ? "删除数据" : "删除视频及数据"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="rounded-xl bg-zinc-50 p-3 text-sm dark:bg-white/[0.03]">
          <div className="break-all font-medium text-zinc-800 dark:text-zinc-100">
            {root.path}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 text-[11px] text-zinc-500">
            <span>已收录 {root.scanned_count ?? 0} 部</span>
            <span>文件 {root.file_count ?? root.scanned_count ?? 0} 个</span>
            <span>已刮削 {root.scraped_count ?? 0}</span>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => setMode("data")}
            className={`rounded-xl border p-3 text-left transition ${
              mode === "data"
                ? "border-sky-300 bg-sky-50/60 dark:border-sky-500/40 dark:bg-sky-500/5"
                : "border-zinc-200 hover:bg-zinc-50 dark:border-white/10 dark:hover:bg-white/5"
            }`}
          >
            <div className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
              仅删除数据
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
              移除目录配置和影片记录，磁盘上的视频文件保留；重新添加目录后需要重新刮削。
            </p>
          </button>
          <button
            type="button"
            onClick={() => setMode("files")}
            className={`rounded-xl border p-3 text-left transition ${
              mode === "files"
                ? "border-red-300 bg-red-50/60 dark:border-red-500/40 dark:bg-red-500/5"
                : "border-zinc-200 hover:bg-zinc-50 dark:border-white/10 dark:hover:bg-white/5"
            }`}
          >
            <div className="flex items-center gap-1.5 text-sm font-semibold text-red-600 dark:text-red-400">
              <TrashIcon className="h-3.5 w-3.5" />
              删除视频及数据
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
              删除目录配置、影片记录，并永久删除该目录中已收录的视频文件，无法恢复。
            </p>
          </button>
        </div>

        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
          只处理数据库中已收录的文件；演员资料会保留，作品数随记录减少。
          {mode === "files" && " 删除前请确认文件没有被播放器占用。"}
        </p>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
            {error}
          </div>
        )}
      </div>
    </Modal>
  );
}
