/**
 * 演员卡片：展示头像、作品数、基础资料和完整度，点击可打开详情或切换收藏。
 */
import type { Actress } from "../api";
import { formatDay, gradient } from "../format";
import { HeartIcon, InfoIcon, UserIcon } from "./Icons";

/** 单个演员卡片；onFavorite 传入取反后的目标状态，实际请求由父组件完成。 */
export function ActressCard({
  actress,
  onSelect,
  onFavorite,
}: {
  actress: Actress;
  onSelect: (id: number) => void;
  onFavorite: (id: number, favorite: boolean) => void;
}) {
  return (
    <article className="group overflow-hidden rounded-2xl border border-zinc-200/80 bg-white shadow-sm transition duration-200 hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-xl dark:border-white/10 dark:bg-zinc-900/80 dark:hover:border-sky-400/40">
      <button
        type="button"
        onClick={() => onSelect(actress.id)}
        className="relative block aspect-[3/4] w-full overflow-hidden bg-zinc-100 dark:bg-zinc-800"
      >
        <div className="absolute inset-0" style={{ background: gradient(actress.id + 7) }} />
        {actress.cover_local ? (
          <img
            // 与视频封面相同，走后端本地封面接口，失败时回退到渐变姓名占位。
            src={`/api/actresses/${actress.id}/cover`}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
            onError={(event) => {
              event.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white/70">
            <UserIcon className="h-10 w-10" />
            <span className="max-w-[85%] truncate text-lg font-semibold text-white/90">
              {actress.name}
            </span>
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/55 via-transparent to-transparent" />
        <span className="absolute left-2.5 top-2.5 rounded-md bg-black/55 px-2 py-0.5 text-[11px] font-medium text-white backdrop-blur">
          {actress.video_count ?? 0} 部
        </span>
        {!actress.is_complete && (
          <span className="absolute right-2.5 top-2.5 rounded-md bg-amber-400 px-2 py-0.5 text-[11px] font-semibold text-amber-950">
            待补全
          </span>
        )}
        <div className="absolute inset-x-0 bottom-0 p-3">
          <div className="truncate text-base font-semibold text-white drop-shadow">
            {actress.name}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 text-[11px] text-zinc-200">
            {actress.birth_date && <span>{formatDay(actress.birth_date)}</span>}
            {actress.nationality && <span>{actress.nationality}</span>}
            {!actress.birth_date && !actress.nationality && <span>资料不完整</span>}
          </div>
        </div>
      </button>

      <div className="flex items-center gap-1 px-3 py-2">
        <button
          type="button"
          onClick={() => onSelect(actress.id)}
          className="inline-flex flex-1 items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-white/5 dark:hover:text-zinc-200"
        >
          <InfoIcon className="h-4 w-4" />
          详情
        </button>
        <button
          type="button"
          onClick={() => onFavorite(actress.id, !actress.favorite)}
          title={actress.favorite ? "取消收藏" : "收藏"}
          aria-label={actress.favorite ? "取消收藏" : "收藏"}
          className={`rounded-md p-1.5 transition hover:bg-rose-50 dark:hover:bg-rose-500/10 ${
            actress.favorite ? "text-rose-500 dark:text-rose-400" : "text-zinc-400 dark:text-zinc-500"
          }`}
        >
          <HeartIcon filled={actress.favorite} className="h-4 w-4" />
        </button>
      </div>
    </article>
  );
}
