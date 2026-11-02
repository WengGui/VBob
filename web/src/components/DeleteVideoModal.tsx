/**
 * 删除视频弹窗。
 * 提供“只删记录”和“连同磁盘文件一起删除”两种方式；
 * 彻底删除时可勾选要删除的文件，未勾选的文件和影片记录会保留。
 */
import { useEffect, useState } from "react";
import { api, type VideoDetail } from "../api";
import { errorMessage, formatSize } from "../format";
import { TrashIcon } from "./Icons";
import { Modal } from "./Modal";

export interface DeleteVideoOutcome {
  recordDeleted: boolean;
  deletedFiles: number;
  remainingFiles: number;
  failed: Array<{ id: number; filename: string; message: string }>;
}

export function DeleteVideoModal({
  videoId,
  title,
  initialFileIds,
  defaultMode = "record",
  onClose,
  onDeleted,
}: {
  videoId: number;
  title: string;
  /** 从某个文件的删除按钮打开时，只预选这些文件。 */
  initialFileIds?: number[];
  defaultMode?: "record" | "files";
  onClose: () => void;
  onDeleted: (outcome: DeleteVideoOutcome) => void;
}) {
  const [detail, setDetail] = useState<VideoDetail | null>(null);
  const [mode, setMode] = useState<"record" | "files">(defaultMode);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 始终读取一次最新详情，避免使用列表里可能过期的文件信息。
  useEffect(() => {
    let cancelled = false;
    api
      .getVideo(videoId)
      .then((data) => {
        if (cancelled) return;
        setDetail(data);
        const preferred = initialFileIds?.length
          ? data.files.filter((file) => initialFileIds.includes(file.id))
          : data.files;
        setSelected(new Set(preferred.map((file) => file.id)));
      })
      .catch((loadError) => {
        if (!cancelled) setError(errorMessage(loadError));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // initialFileIds 只在打开时决定初选，后续变化不应重置用户勾选。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  const files = detail?.files ?? [];
  const allSelected = files.length > 0 && selected.size === files.length;
  const selectedSize = files
    .filter((file) => selected.has(file.id))
    .reduce((sum, file) => sum + (file.size_bytes ?? 0), 0);

  function toggle(fileId: number) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  }

  async function deleteRecord() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteVideo(videoId);
      onDeleted({ recordDeleted: true, deletedFiles: 0, remainingFiles: 0, failed: [] });
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    } finally {
      setBusy(false);
    }
  }

  async function deleteFiles() {
    if (selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.deleteVideoFiles(videoId, [...selected]);
      onDeleted({
        recordDeleted: result.record_deleted,
        deletedFiles: result.deleted_files,
        remainingFiles: result.remaining_files,
        failed: result.failed_files,
      });
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="删除视频"
      subtitle={title}
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
          {/* 只保留一个确认按钮，避免在“删除记录”模式下误点彻底删除。 */}
          <button
            type="button"
            onClick={() => void (mode === "record" ? deleteRecord() : deleteFiles())}
            disabled={busy || loading || (mode === "files" && selected.size === 0)}
            className="rounded-lg bg-red-500 px-4 py-2 text-sm font-semibold text-white hover:bg-red-400 disabled:opacity-40"
          >
            {busy
              ? "处理中…"
              : mode === "record"
                ? "删除记录"
                : `彻底删除${selected.size ? `（${selected.size}）` : ""}`}
          </button>
        </>
      }
    >
      {loading ? (
        <p className="py-12 text-center text-sm text-zinc-500">正在读取文件信息…</p>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl bg-zinc-50 p-3 text-sm dark:bg-white/[0.03]">
            <div className="font-medium text-zinc-800 dark:text-zinc-100">{title}</div>
            <div className="mt-1 flex flex-wrap gap-x-4 text-[11px] text-zinc-500">
              <span>共 {files.length} 个文件</span>
              <span>已勾选 {selected.size} 个，合计 {formatSize(selectedSize)}</span>
            </div>
          </div>

          {/* 两种删除方式用选项卡片呈现，默认选中更安全的“删除记录”。 */}
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => setMode("record")}
              className={`rounded-xl border p-3 text-left transition ${
                mode === "record"
                  ? "border-sky-300 bg-sky-50/60 dark:border-sky-500/40 dark:bg-sky-500/5"
                  : "border-zinc-200 hover:bg-zinc-50 dark:border-white/10 dark:hover:bg-white/5"
              }`}
            >
              <div className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                删除记录
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
                只从 VBoB 移除影片和文件记录，磁盘上的视频不会删除。
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
                彻底删除
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
                从磁盘删除勾选的文件，无法恢复；未勾选的文件和记录会保留。
              </p>
            </button>
          </div>

          {mode === "files" && (
            <div className="rounded-xl border border-zinc-200 dark:border-white/10">
              <div className="flex items-center justify-between border-b border-zinc-100 px-3 py-2 dark:border-white/5">
                <label className="inline-flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() =>
                      setSelected(
                        allSelected ? new Set() : new Set(files.map((file) => file.id)),
                      )
                    }
                    className="h-4 w-4 rounded border-zinc-300"
                  />
                  全选
                </label>
                <span className="text-[11px] text-zinc-500">
                  勾选 {selected.size}/{files.length} 个文件
                </span>
              </div>
              <ul className="divide-y divide-zinc-100 dark:divide-white/5">
                {files.map((file) => (
                  <li key={file.id} className="flex items-start gap-3 px-3 py-2.5">
                    <input
                      type="checkbox"
                      checked={selected.has(file.id)}
                      onChange={() => toggle(file.id)}
                      className="mt-0.5 h-4 w-4 shrink-0 rounded border-zinc-300"
                      aria-label={`选择 ${file.filename}`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2 text-sm text-zinc-800 dark:text-zinc-100">
                        <span className="break-all">{file.filename}</span>
                        <span className="text-[10px] text-zinc-400">
                          {formatSize(file.size_bytes)}
                        </span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] ${
                            file.present
                              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                              : "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                          }`}
                        >
                          {file.present ? "文件存在" : "文件缺失"}
                        </span>
                      </div>
                      <div className="mt-0.5 break-all font-mono text-[10px] text-zinc-400">
                        {file.path}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="border-t border-zinc-100 px-3 py-2 text-[11px] text-zinc-500 dark:border-white/5">
                {allSelected
                  ? "所选文件全部删除后，影片记录也会移除。"
                  : "只删除勾选的文件；未勾选的文件会保留，影片记录继续存在。"}
              </p>
            </div>
          )}

          {mode === "record" && (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
              删除记录后，磁盘文件仍然存在；下次扫描会被重新收录（元数据需重新刮削）。
            </p>
          )}

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
              {error}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
