import type { ReactNode } from "react";
import type { Video, VideoDetail } from "../api";
import {
  chipsOf,
  codeOf,
  durationOf,
  formatDate,
  formatDuration,
  formatSize,
  gradient,
  titleOf,
} from "../format";
import { CloseIcon, PlayIcon, TrashIcon } from "./Icons";

function Field({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="border-b border-zinc-100 py-2 dark:border-white/5">
      <dt className="text-[11px] uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        {label}
      </dt>
      <dd className="mt-0.5 break-words text-sm text-zinc-700 dark:text-zinc-200">{value}</dd>
    </div>
  );
}

const CHIP_STYLES: Record<string, string> = {
  violet:
    "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:border-violet-500/20",
  orange:
    "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/10 dark:text-orange-300 dark:border-orange-500/20",
  neutral:
    "bg-zinc-100 text-zinc-600 border-zinc-200 dark:bg-white/5 dark:text-zinc-400 dark:border-white/10",
};

export function DetailDrawer({
  detail,
  onClose,
  onPlay,
  onDelete,
  playing,
}: {
  detail: VideoDetail | null;
  onClose: () => void;
  onPlay: () => void;
  onDelete: () => void;
  playing: boolean;
}) {
  const video = detail?.video;
  const metadata = detail?.metadata ?? null;
  const view: Video | null = video ? { ...video, metadata } : null;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/40 backdrop-blur-sm dark:bg-black/70"
      onClick={onClose}
      role="presentation"
    >
      <aside
        className="h-full w-full max-w-lg overflow-y-auto border-l border-zinc-200 bg-white shadow-2xl dark:border-white/10 dark:bg-zinc-950"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-zinc-100 bg-white/90 px-6 py-3 backdrop-blur dark:border-white/10 dark:bg-zinc-950/90">
          <span className="text-xs font-medium uppercase tracking-wider text-zinc-400">
            视频详情
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-white/5 dark:hover:text-zinc-200"
            aria-label="关闭"
          >
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>

        {!view ? (
          <p className="px-6 py-12 text-sm text-zinc-500">正在加载详情…</p>
        ) : (
          <div className="px-6 pb-10 pt-5">
            <div className="relative aspect-[16/9] overflow-hidden rounded-xl bg-zinc-100 dark:bg-zinc-800">
              <div className="absolute inset-0" style={{ background: gradient(view.id) }} />
              {metadata?.cover_local ? (
                <img
                  src={`/api/videos/${view.id}/cover`}
                  alt=""
                  className="absolute inset-0 h-full w-full object-cover"
                  onError={(event) => {
                    event.currentTarget.style.display = "none";
                  }}
                />
              ) : (
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-3xl font-bold tracking-wider text-white/80">
                    {codeOf(view) || "VBob"}
                  </span>
                </div>
              )}
              {!view.present && (
                <span className="absolute left-3 top-3 rounded-md bg-amber-400 px-2 py-0.5 text-[11px] font-semibold text-amber-950">
                  文件缺失
                </span>
              )}
            </div>

            <h2 className="mt-4 text-xl font-semibold text-zinc-900 dark:text-white">
              {titleOf(view)}
            </h2>
            {metadata?.original_title && (
              <p className="mt-1 text-sm text-zinc-500">{metadata.original_title}</p>
            )}

            <div className="mt-3 flex flex-wrap gap-1.5">
              {chipsOf(view).map((chip) => (
                <span
                  key={`${chip.tone}-${chip.label}`}
                  className={`rounded-md border px-2 py-0.5 text-[11px] ${CHIP_STYLES[chip.tone]}`}
                >
                  {chip.label}
                </span>
              ))}
            </div>

            <div className="mt-5 flex gap-2">
              <button
                type="button"
                onClick={onPlay}
                disabled={playing || !view.present}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-sky-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <PlayIcon className="h-4 w-4" />
                {playing ? "正在启动…" : "用本地播放器打开"}
              </button>
              <button
                type="button"
                onClick={onDelete}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 px-4 py-2.5 text-sm text-red-600 transition hover:bg-red-50 dark:border-red-500/20 dark:text-red-400 dark:hover:bg-red-500/10"
              >
                <TrashIcon className="h-4 w-4" />
                删除记录
              </button>
            </div>

            <dl className="mt-6">
              <Field label="番号" value={codeOf(view)} />
              <Field label="文件名" value={view.filename} />
              <Field label="大小" value={formatSize(view.size_bytes)} />
              <Field label="时长" value={formatDuration(durationOf(view))} />
              <Field label="发行日期" value={metadata?.release_date} />
              <Field label="厂商" value={metadata?.studio} />
              <Field label="系列" value={metadata?.series} />
              <Field label="导演" value={metadata?.director} />
              <Field label="类型" value={metadata?.genres?.join(" / ")} />
              <Field label="标签" value={metadata?.tags?.join(" / ")} />
              <Field label="演员" value={metadata?.actresses?.join(" / ")} />
              <Field label="简介" value={metadata?.overview} />
              <Field label="刮削来源" value={metadata?.source_name} />
              <Field label="刮削状态" value={metadata?.scrape_status ?? "pending"} />
              <Field
                label="入库时间"
                value={formatDate(view.created_at)}
              />
              <Field label="路径" value={<span className="break-all text-xs">{view.path}</span>} />
            </dl>

            <details className="mt-5 rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-white/10 dark:bg-white/[0.02]">
              <summary className="cursor-pointer text-xs font-medium text-zinc-500 dark:text-zinc-400">
                提取的特征
              </summary>
              <pre className="mt-2 overflow-x-auto text-xs text-zinc-600 dark:text-zinc-300">
                {JSON.stringify(view.features, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </aside>
    </div>
  );
}
