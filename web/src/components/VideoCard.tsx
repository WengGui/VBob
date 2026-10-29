import type { Video } from "../api";
import {
  chipsOf,
  codeOf,
  durationOf,
  formatDuration,
  gradient,
  releaseYear,
  titleOf,
} from "../format";
import {
  CalendarIcon,
  ClockIcon,
  FilmIcon,
  InfoIcon,
  PlayIcon,
  StudioIcon,
  TrashIcon,
} from "./Icons";

const CHIP_STYLES: Record<string, string> = {
  violet:
    "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:border-violet-500/20",
  orange:
    "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/10 dark:text-orange-300 dark:border-orange-500/20",
  neutral:
    "bg-zinc-100 text-zinc-600 border-zinc-200 dark:bg-white/5 dark:text-zinc-400 dark:border-white/10",
};

export function VideoCard({
  video,
  onSelect,
  onPlay,
  onDelete,
}: {
  video: Video;
  onSelect: (id: number) => void;
  onPlay: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  const code = codeOf(video);
  const title = titleOf(video);
  const duration = formatDuration(durationOf(video));
  const year = releaseYear(video);
  const chips = chipsOf(video);

  return (
    <article className="group overflow-hidden rounded-2xl border border-zinc-200/80 bg-white shadow-sm transition duration-200 hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-xl hover:shadow-zinc-300/40 dark:border-white/10 dark:bg-zinc-900/80 dark:hover:border-sky-400/40 dark:hover:shadow-black/40">
      <button
        type="button"
        onClick={() => onSelect(video.id)}
        className="relative block aspect-[16/10] w-full overflow-hidden bg-zinc-100 text-left dark:bg-zinc-800"
      >
        <div className="absolute inset-0" style={{ background: gradient(video.id) }} />
        {video.metadata?.cover_local ? (
          <img
            src={`/api/videos/${video.id}/cover`}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
            onError={(event) => {
              event.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-white/60">
            <FilmIcon className="h-8 w-8" />
            <span className="max-w-[85%] truncate text-lg font-semibold tracking-wide text-white/85">
              {code || "VBob"}
            </span>
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/35 via-transparent to-transparent" />
        {!video.present && (
          <span className="absolute left-2.5 top-2.5 rounded-md bg-amber-400 px-2 py-0.5 text-[11px] font-semibold text-amber-950 shadow">
            文件缺失
          </span>
        )}
        <span className="absolute bottom-2.5 right-2.5 rounded-md bg-black/55 px-2 py-0.5 text-[11px] font-medium text-white backdrop-blur">
          {video.present ? "本地文件" : "未找到"}
        </span>
      </button>

      <div className="p-3.5">
        <button
          type="button"
          onClick={() => onSelect(video.id)}
          className="block w-full text-left"
        >
          <div className="flex items-baseline gap-2">
            {code && (
              <span className="shrink-0 text-sm font-bold tracking-wide text-zinc-900 dark:text-zinc-100">
                {code}
              </span>
            )}
            <span className="line-clamp-1 min-w-0 flex-1 text-sm font-medium text-zinc-700 dark:text-zinc-300">
              {title}
            </span>
          </div>
          {code && code !== title && (
            <p className="mt-1 line-clamp-1 text-[11px] text-zinc-400 dark:text-zinc-500">
              {video.filename}
            </p>
          )}
        </button>

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500 dark:text-zinc-400">
          {duration && (
            <span className="inline-flex items-center gap-1">
              <ClockIcon className="h-3.5 w-3.5" />
              {duration}
            </span>
          )}
          {year && (
            <span className="inline-flex items-center gap-1">
              <CalendarIcon className="h-3.5 w-3.5" />
              {year}
            </span>
          )}
          {video.metadata?.studio && (
            <span className="inline-flex items-center gap-1">
              <StudioIcon className="h-3.5 w-3.5" />
              {video.metadata.studio}
            </span>
          )}
          {!duration && !year && !video.metadata?.studio && (
            <span>{video.present ? "已入库" : "等待重新扫描"}</span>
          )}
        </div>

        <div className="mt-2 flex h-6 flex-wrap gap-1 overflow-hidden">
          {chips.map((chip) => (
            <span
              key={`${chip.tone}-${chip.label}`}
              className={`rounded-md border px-1.5 py-0.5 text-[10px] leading-4 ${CHIP_STYLES[chip.tone]}`}
            >
              {chip.label}
            </span>
          ))}
        </div>

        <div className="mt-3 flex items-center gap-1 border-t border-zinc-100 pt-2 dark:border-white/5">
          <button
            type="button"
            onClick={() => onPlay(video.id)}
            disabled={!video.present}
            title="用本地播放器打开"
            aria-label="播放"
            className="rounded-md p-1.5 text-zinc-500 transition hover:bg-sky-50 hover:text-sky-600 disabled:cursor-not-allowed disabled:opacity-30 dark:text-zinc-400 dark:hover:bg-sky-500/10 dark:hover:text-sky-400"
          >
            <PlayIcon className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onSelect(video.id)}
            title="查看详情"
            aria-label="查看详情"
            className="rounded-md p-1.5 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-white/5 dark:hover:text-zinc-200"
          >
            <InfoIcon className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onDelete(video.id)}
            title="从库中删除记录"
            aria-label="删除记录"
            className="ml-auto rounded-md p-1.5 text-zinc-400 transition hover:bg-red-50 hover:text-red-600 dark:text-zinc-500 dark:hover:bg-red-500/10 dark:hover:text-red-400"
          >
            <TrashIcon className="h-4 w-4" />
          </button>
        </div>
      </div>
    </article>
  );
}
