/**
 * 视频卡片：展示封面、番号、标题、日期与标签，并提供播放、详情、收藏和删除入口。
 * 仅负责展示，所有操作通过 props 回调交给 App 统一处理。
 */
import { useState } from "react";
import type { Video } from "../api";
import {
  censoredLabel,
  codeOf,
  durationOf,
  formatDay,
  formatDuration,
  gradient,
  titleOf,
} from "../format";
import {
  ClockIcon,
  FilmIcon,
  HeartIcon,
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
  sky:
    "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:border-sky-500/20",
  neutral:
    "bg-zinc-100 text-zinc-600 border-zinc-200 dark:bg-white/5 dark:text-zinc-400 dark:border-white/10",
};

const ACTOR_PREVIEW = 4;
const TAG_PREVIEW = 6;

/** 单个视频卡片；标签点击后交给父组件作为筛选条件。 */
export function VideoCard({
  video,
  onSelect,
  onPlay,
  onDelete,
  onFavorite,
  onFilterActress,
  onFilterTag,
  onFilterSeries,
  isDragging,
  isDropTarget,
  onDragStartCard,
  onDragEndCard,
  onDragOverCard,
  onDragLeaveCard,
  onDropCard,
}: {
  video: Video;
  onSelect: (id: number) => void;
  onPlay: (id: number) => void;
  onDelete: (id: number) => void;
  onFavorite: (id: number, favorite: boolean) => void;
  onFilterActress: (id: number, name: string) => void;
  onFilterTag: (tag: string) => void;
  onFilterSeries: (series: string) => void;
  isDragging: boolean;
  isDropTarget: boolean;
  onDragStartCard: () => void;
  onDragEndCard: () => void;
  onDragOverCard: () => void;
  onDragLeaveCard: () => void;
  onDropCard: (sourceId: number) => void;
}) {
  const [actorsOpen, setActorsOpen] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const code = codeOf(video);
  const title = titleOf(video);
  const duration = formatDuration(durationOf(video));
  const release = formatDay(video.metadata?.release_date ?? null);
  const censored = censoredLabel(video.metadata?.censored);

  // 演员优先使用带 id 的关联记录，才能按演员筛选；旧数据只有姓名时仅展示。
  const actors = video.actresses?.length
    ? video.actresses.map((actress) => ({ id: actress.id, name: actress.name }))
    : (video.metadata?.actresses ?? []).map((name) => ({ id: null, name }));
  // 类型和标签合并去重后作为“标签”行显示。
  const tags = Array.from(
    new Set([...(video.metadata?.genres ?? []), ...(video.metadata?.tags ?? [])]),
  );
  const series = video.metadata?.series ?? null;
  const visibleActors = actorsOpen ? actors : actors.slice(0, ACTOR_PREVIEW);
  const visibleTags = tagsOpen ? tags : tags.slice(0, TAG_PREVIEW);

  return (
    <article
      draggable
      title="拖动这张海报到另一张海报上，可合并为同一剧集"
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", String(video.id));
        event.dataTransfer.effectAllowed = "move";
        onDragStartCard();
      }}
      onDragEnd={onDragEndCard}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        onDragOverCard();
      }}
      onDragLeave={(event) => {
        // 子元素之间移动也会触发 dragleave，只有真正离开卡片时才清除高亮。
        const next = event.relatedTarget as Node | null;
        if (!next || !event.currentTarget.contains(next)) onDragLeaveCard();
      }}
      onDrop={(event) => {
        event.preventDefault();
        const sourceId = Number(event.dataTransfer.getData("text/plain"));
        if (sourceId) onDropCard(sourceId);
      }}
      className={`group relative overflow-hidden rounded-2xl border border-zinc-200/80 bg-white shadow-sm transition duration-200 hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-xl hover:shadow-zinc-300/40 dark:border-white/10 dark:bg-zinc-900/80 dark:hover:border-sky-400/40 dark:hover:shadow-black/40 ${
        isDragging ? "opacity-40" : ""
      } ${
        isDropTarget
          ? "ring-2 ring-sky-400 ring-offset-2 ring-offset-zinc-50 dark:ring-offset-zinc-950"
          : ""
      }`}
    >
      {/* 拖拽悬停时提示松手合并，避免用户不清楚当前操作。 */}
      {isDropTarget && (
        <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-sky-500/15 text-xs font-semibold text-sky-800 backdrop-blur-[1px] dark:text-sky-100">
          松手合并到该剧集
        </div>
      )}
      <button
        type="button"
        onClick={() => onSelect(video.id)}
        className="relative block aspect-[16/10] w-full overflow-hidden bg-zinc-100 text-left dark:bg-zinc-800"
      >
        <div className="absolute inset-0" style={{ background: gradient(video.id) }} />
        {video.metadata?.cover_local ? (
          <img
            // 封面由后端按 id 返回本地缓存文件，而不是直接使用远端 URL。
            src={`/api/videos/${video.id}/cover`}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
            onError={(event) => {
              // 加载失败时隐藏图片，露出底层的渐变占位，避免出现破图图标。
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
        <div className="absolute left-2.5 top-2.5 flex gap-1">
          {censored && (
            <span className="rounded-md bg-black/55 px-2 py-0.5 text-[11px] font-medium text-white backdrop-blur">
              {censored}
            </span>
          )}
          {!video.metadata?.is_complete && (
            <span className="rounded-md bg-amber-400 px-2 py-0.5 text-[11px] font-semibold text-amber-950">
              待补全
            </span>
          )}
        </div>
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
        </button>

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500 dark:text-zinc-400">
          {release && (
            <span className="inline-flex items-center gap-1">
              <ClockIcon className="h-3.5 w-3.5" />
              {release}
            </span>
          )}
          {duration && <span>{duration}</span>}
          {video.metadata?.studio && (
            <span className="inline-flex min-w-0 items-center gap-1">
              <StudioIcon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{video.metadata.studio}</span>
            </span>
          )}
          {(video.file_count ?? 1) > 1 && (
            <span className="text-sky-600 dark:text-sky-400">{video.file_count} 个文件</span>
          )}
          {!release && !duration && !video.metadata?.studio && <span>未刮削</span>}
        </div>

        <div className="mt-2 space-y-1.5">
          {actors.length > 0 && (
            <div className="flex items-start gap-1.5">
              <span className="mt-0.5 shrink-0 text-[10px] text-zinc-400 dark:text-zinc-500">
                演员
              </span>
              <div className="flex min-w-0 flex-wrap gap-1">
                {visibleActors.map((actor, index) =>
                  actor.id !== null ? (
                    <button
                      key={`${actor.id}-${index}`}
                      type="button"
                      onClick={() => onFilterActress(actor.id as number, actor.name)}
                      title={`按演员筛选：${actor.name}`}
                      className={`rounded-md border px-1.5 py-0.5 text-[10px] leading-4 transition hover:brightness-95 ${CHIP_STYLES.violet}`}
                    >
                      {actor.name}
                    </button>
                  ) : (
                    <span
                      key={`${actor.name}-${index}`}
                      className={`rounded-md border px-1.5 py-0.5 text-[10px] leading-4 ${CHIP_STYLES.violet}`}
                    >
                      {actor.name}
                    </span>
                  ),
                )}
                {actors.length > ACTOR_PREVIEW && (
                  <button
                    type="button"
                    onClick={() => setActorsOpen((open) => !open)}
                    className="rounded-md px-1 py-0.5 text-[10px] text-sky-600 hover:bg-sky-50 dark:text-sky-400 dark:hover:bg-sky-500/10"
                  >
                    {actorsOpen ? "收起" : `+${actors.length - ACTOR_PREVIEW}`}
                  </button>
                )}
              </div>
            </div>
          )}

          {(tags.length > 0 || series) && (
            <div className="flex items-start gap-1.5">
              <span className="mt-0.5 shrink-0 text-[10px] text-zinc-400 dark:text-zinc-500">
                标签
              </span>
              <div className="flex min-w-0 flex-wrap gap-1">
                {series && (
                  <button
                    type="button"
                    onClick={() => onFilterSeries(series)}
                    title={`按系列筛选：${series}`}
                    className={`rounded-md border px-1.5 py-0.5 text-[10px] leading-4 transition hover:brightness-95 ${CHIP_STYLES.sky}`}
                  >
                    {series}
                  </button>
                )}
                {visibleTags.map((tag) => (
                  <button
                    key={`tag-${tag}`}
                    type="button"
                    onClick={() => onFilterTag(tag)}
                    title={`按标签筛选：${tag}`}
                    className={`rounded-md border px-1.5 py-0.5 text-[10px] leading-4 transition hover:brightness-95 ${CHIP_STYLES.orange}`}
                  >
                    {tag}
                  </button>
                ))}
                {tags.length > TAG_PREVIEW && (
                  <button
                    type="button"
                    onClick={() => setTagsOpen((open) => !open)}
                    className="rounded-md px-1 py-0.5 text-[10px] text-sky-600 hover:bg-sky-50 dark:text-sky-400 dark:hover:bg-sky-500/10"
                  >
                    {tagsOpen ? "收起" : `+${tags.length - TAG_PREVIEW}`}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="mt-3 flex items-center gap-1 border-t border-zinc-100 pt-2 dark:border-white/5">
          {/* 文件已丢失（present=false）时禁用播放，但记录仍可查看或删除。 */}
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
            title="查看/编辑详情"
            aria-label="查看详情"
            className="rounded-md p-1.5 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-white/5 dark:hover:text-zinc-200"
          >
            <InfoIcon className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onFavorite(video.id, !video.favorite)}
            title={video.favorite ? "取消收藏" : "收藏"}
            aria-label={video.favorite ? "取消收藏" : "收藏"}
            className={`rounded-md p-1.5 transition hover:bg-rose-50 dark:hover:bg-rose-500/10 ${
              video.favorite
                ? "text-rose-500 dark:text-rose-400"
                : "text-zinc-400 dark:text-zinc-500"
            }`}
          >
            <HeartIcon filled={video.favorite} className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onDelete(video.id)}
            title="删除视频（可选择是否删除文件）"
            aria-label="删除视频"
            className="ml-auto rounded-md p-1.5 text-zinc-400 transition hover:bg-red-50 hover:text-red-600 dark:text-zinc-500 dark:hover:bg-red-500/10 dark:hover:text-red-400"
          >
            <TrashIcon className="h-4 w-4" />
          </button>
        </div>
      </div>
    </article>
  );
}
