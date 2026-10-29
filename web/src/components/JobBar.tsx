import type { Job } from "../api";
import { ScanIcon } from "./Icons";

const LABELS: Record<Job["status"], string> = {
  queued: "排队中",
  running: "扫描中",
  succeeded: "扫描完成",
  failed: "扫描失败",
  canceled: "已取消",
};

const COLORS: Record<Job["status"], string> = {
  queued: "text-sky-600 dark:text-sky-400",
  running: "text-sky-600 dark:text-sky-400",
  succeeded: "text-emerald-600 dark:text-emerald-400",
  failed: "text-red-600 dark:text-red-400",
  canceled: "text-zinc-500 dark:text-zinc-400",
};

export function JobBar({
  job,
  onCancel,
  onDismiss,
}: {
  job: Job;
  onCancel: () => void;
  onDismiss: () => void;
}) {
  const active = job.status === "queued" || job.status === "running";
  const percent = job.total > 0 ? Math.min(100, Math.round((job.done / job.total) * 100)) : null;

  return (
    <div className="border-b border-zinc-200 bg-white/80 dark:border-white/10 dark:bg-zinc-900/60">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3 px-6 py-2.5 text-sm">
        <span className={`inline-flex items-center gap-1.5 font-medium ${COLORS[job.status]}`}>
          <ScanIcon className={active ? "h-4 w-4 animate-pulse" : "h-4 w-4"} />
          {LABELS[job.status]}
        </span>
        <div className="h-1.5 min-w-32 flex-1 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
          {percent === null ? (
            <div className="h-full w-1/3 animate-pulse rounded-full bg-sky-500" />
          ) : (
            <div
              className="h-full rounded-full bg-sky-500 transition-all"
              style={{ width: `${percent}%` }}
            />
          )}
        </div>
        <span className="tabular-nums text-zinc-500 dark:text-zinc-400">
          {job.done}/{job.total}
        </span>
        <span
          className="max-w-[45%] truncate text-zinc-500 dark:text-zinc-400"
          title={job.message ?? ""}
        >
          {job.message}
        </span>
        {active ? (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-zinc-200 px-2 py-1 text-xs text-zinc-600 transition hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
          >
            取消
          </button>
        ) : (
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md border border-zinc-200 px-2 py-1 text-xs text-zinc-600 transition hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
          >
            关闭
          </button>
        )}
      </div>
    </div>
  );
}
