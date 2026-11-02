/**
 * 播放文件选择弹窗。
 * 同一部影片可能包含多个本地文件，点击播放时先选择具体文件；
 * 每个选项展示文件名、大小、时长与存在状态，缺失文件不可选。
 */
import type { VideoFile } from "../api";
import { formatDuration, formatSize } from "../format";
import { FilmIcon, PlayIcon } from "./Icons";
import { Modal } from "./Modal";

export function VideoFilePicker({
  title,
  files,
  onClose,
  onSelect,
}: {
  /** 影片标题，作为弹窗副标题。 */
  title: string;
  files: VideoFile[];
  onClose: () => void;
  onSelect: (fileId: number) => void;
}) {
  return (
    <Modal
      title="选择播放文件"
      subtitle={title}
      onClose={onClose}
      footer={
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-zinc-200 px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
        >
          取消
        </button>
      }
    >
      <ul className="space-y-2">
        {files.map((file) => {
          const duration = formatDuration(file.duration_sec);
          return (
            <li key={file.id}>
              <button
                type="button"
                disabled={!file.present}
                onClick={() => onSelect(file.id)}
                className="flex w-full items-center gap-3 rounded-xl border border-zinc-200 p-3 text-left transition hover:border-sky-300 hover:bg-sky-50/60 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-zinc-200 disabled:hover:bg-transparent dark:border-white/10 dark:hover:border-sky-500/40 dark:hover:bg-sky-500/5 dark:disabled:hover:border-white/10 dark:disabled:hover:bg-transparent"
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-500 dark:bg-white/5 dark:text-zinc-400">
                  <FilmIcon className="h-5 w-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
                    {file.filename}
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[11px] text-zinc-500">
                    <span>{formatSize(file.size_bytes)}</span>
                    {duration && <span>{duration}</span>}
                    <span
                      className={
                        file.present
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-red-500 dark:text-red-400"
                      }
                    >
                      {file.present ? "文件存在" : "文件缺失"}
                    </span>
                  </span>
                  <span className="mt-1 block truncate text-[10px] text-zinc-400 dark:text-zinc-500">
                    {file.path}
                  </span>
                </span>
                <PlayIcon className="h-4 w-4 shrink-0 text-sky-500" />
              </button>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-[11px] text-zinc-500">
        选择后会立即用当前设置的本地播放器打开。
      </p>
    </Modal>
  );
}
