import type { ReactNode } from "react";
import type { ActressDetail } from "../api";
import { formatDay, gradient } from "../format";
import {
  CloseIcon,
  EditIcon,
  HeartIcon,
  PlayIcon,
  ScanIcon,
  TrashIcon,
  UserIcon,
} from "./Icons";

export function ActressDetailDrawer({
  detail,
  onClose,
  onEdit,
  onScrape,
  onFavorite,
  onDelete,
  onSelectVideo,
}: {
  detail: ActressDetail | null;
  onClose: () => void;
  onEdit: () => void;
  onScrape: () => void;
  onFavorite: () => void;
  onDelete: () => void;
  onSelectVideo: (id: number) => void;
}) {
  const actress = detail?.actress;

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
            演员详情
          </span>
          <div className="flex items-center gap-1">
            {actress && (
              <button
                type="button"
                onClick={onFavorite}
                className={`rounded-md p-1.5 transition hover:bg-rose-50 dark:hover:bg-rose-500/10 ${
                  actress.favorite
                    ? "text-rose-500 dark:text-rose-400"
                    : "text-zinc-400 hover:text-rose-500"
                }`}
                aria-label={actress.favorite ? "取消收藏" : "收藏"}
              >
                <HeartIcon filled={actress.favorite} className="h-5 w-5" />
              </button>
            )}
            <button
              type="button"
              onClick={onScrape}
              className="rounded-md p-1.5 text-zinc-400 transition hover:bg-sky-50 hover:text-sky-600 dark:hover:bg-sky-500/10 dark:hover:text-sky-300"
              aria-label="刮削演员"
              title="用演员源补全资料"
            >
              <ScanIcon className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={onEdit}
              className="rounded-md p-1.5 text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-white/5 dark:hover:text-zinc-200"
              aria-label="编辑"
            >
              <EditIcon className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-white/5 dark:hover:text-zinc-200"
              aria-label="关闭"
            >
              <CloseIcon className="h-5 w-5" />
            </button>
          </div>
        </div>

        {!detail || !actress ? (
          <p className="px-6 py-12 text-sm text-zinc-500">正在加载详情…</p>
        ) : (
          <div className="px-6 pb-10 pt-5">
            <div className="relative aspect-[4/3] overflow-hidden rounded-xl bg-zinc-100 dark:bg-zinc-800">
              <div className="absolute inset-0" style={{ background: gradient(actress.id + 7) }} />
              {actress.cover_local ? (
                <img
                  src={`/api/actresses/${actress.id}/cover`}
                  alt=""
                  className="absolute inset-0 h-full w-full object-cover"
                  onError={(event) => {
                    event.currentTarget.style.display = "none";
                  }}
                />
              ) : (
                <div className="absolute inset-0 flex items-center justify-center gap-2 text-white/80">
                  <UserIcon className="h-10 w-10" />
                  <span className="text-2xl font-semibold">{actress.name}</span>
                </div>
              )}
            </div>

            <div className="mt-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold text-zinc-900 dark:text-white">
                  {actress.name}
                </h2>
                <p className="mt-1 text-sm text-zinc-500">
                  {actress.video_count ?? 0} 部作品
                </p>
              </div>
              <span
                className={`shrink-0 rounded-md px-2 py-1 text-[11px] font-medium ${
                  actress.is_complete
                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                    : "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                }`}
              >
                {actress.is_complete ? "资料完整" : "待补全"}
              </span>
            </div>

            <dl className="mt-5 grid grid-cols-2 gap-x-5">
              <Field label="出生日期" value={formatDay(actress.birth_date)} />
              <Field label="国籍" value={actress.nationality} />
              <Field label="身高" value={actress.height_cm ? `${actress.height_cm} cm` : null} />
              <Field label="罩杯" value={actress.cup} />
              <Field
                label="三围"
                value={
                  actress.bust_cm || actress.waist_cm || actress.hips_cm
                    ? `${actress.bust_cm ?? "—"}-${actress.waist_cm ?? "—"}-${actress.hips_cm ?? "—"}`
                    : null
                }
              />
              <Field label="别名" value={actress.aliases?.join(" / ")} />
            </dl>

            <h3 className="mt-6 text-sm font-semibold text-zinc-800 dark:text-zinc-200">
              收录作品
            </h3>
            <ul className="mt-2 divide-y divide-zinc-100 dark:divide-white/5">
              {detail.videos.length === 0 && (
                <li className="py-4 text-sm text-zinc-500">还没有关联作品</li>
              )}
              {detail.videos.map((video) => (
                <li key={video.id}>
                  <button
                    type="button"
                    onClick={() => onSelectVideo(video.id)}
                    className="flex w-full items-center gap-3 py-2 text-left transition hover:bg-zinc-50 dark:hover:bg-white/5"
                  >
                    <span className="flex h-10 w-16 shrink-0 items-center justify-center overflow-hidden rounded-md bg-zinc-100 dark:bg-zinc-800">
                      {video.cover_local ? (
                        <img
                          src={`/api/videos/${video.id}/cover`}
                          alt=""
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <PlayIcon className="h-4 w-4 text-zinc-400" />
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-zinc-700 dark:text-zinc-200">
                        {video.title || video.filename}
                      </span>
                      <span className="block text-[11px] text-zinc-500">
                        {video.release_date || (video.year ? String(video.year) : "—")}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>

            <button
              type="button"
              onClick={onDelete}
              className="mt-8 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-red-200 px-4 py-2 text-xs text-red-600 hover:bg-red-50 dark:border-red-500/20 dark:text-red-400 dark:hover:bg-red-500/10"
            >
              <TrashIcon className="h-4 w-4" />
              删除演员
            </button>
          </div>
        )}
      </aside>
    </div>
  );
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  if (!value) return null;
  return (
    <div className="border-b border-zinc-100 py-2 dark:border-white/5">
      <dt className="text-[11px] uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm text-zinc-700 dark:text-zinc-200">{value}</dd>
    </div>
  );
}
