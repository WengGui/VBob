/**
 * 视频详情弹窗。
 * 使用固定尺寸居中弹窗，封面与操作在左，基础信息、演员、标签、文件平铺在右；
 * 演员/标签/系列点击后作为列表筛选条件。详情数据由父组件按视频 ID 加载后传入。
 */
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type { Video, VideoDetail } from "../api";
import {
  censoredLabel,
  codeOf,
  durationOf,
  formatDate,
  formatDuration,
  formatSize,
  gradient,
  titleOf,
} from "../format";
import {
  EditIcon,
  HeartIcon,
  PlayIcon,
  ScanIcon,
  TrashIcon,
} from "./Icons";
import { Modal } from "./Modal";

/** 详情字段行；空值直接不渲染，避免详情区出现大量空行。 */
function Field({
  label,
  value,
  wide = false,
}: {
  label: string;
  value: ReactNode;
  wide?: boolean;
}) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div
      className={`border-b border-zinc-100 py-2.5 dark:border-white/5 ${
        wide ? "sm:col-span-2" : ""
      }`}
    >
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
  sky:
    "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:border-sky-500/20",
  neutral:
    "bg-zinc-100 text-zinc-600 border-zinc-200 dark:bg-white/5 dark:text-zinc-400 dark:border-white/10",
};

/** 视频详情弹窗；所有操作都是回调，关闭后由父组件卸载以复位日志状态。 */
export function VideoDetailModal({
  detail,
  onClose,
  onPlay,
  onDelete,
  onEdit,
  onScrape,
  onFavorite,
  onFilterActress,
  onFilterTag,
  onFilterSeries,
  onDeleteFile,
  playing,
}: {
  detail: VideoDetail | null;
  onClose: () => void;
  onPlay: () => void;
  onDelete: () => void;
  onEdit: () => void;
  onScrape: () => void;
  onFavorite: () => void;
  /** 演员/标签/系列点击后作为列表筛选条件，父组件会关闭详情。 */
  onFilterActress: (id: number, name: string) => void;
  onFilterTag: (tag: string) => void;
  onFilterSeries: (series: string) => void;
  /** 删除指定文件；父组件会打开与“删除视频”相同的确认弹窗。 */
  onDeleteFile: (fileId: number) => void;
  playing: boolean;
}) {
  const video = detail?.video;
  const metadata = detail?.metadata ?? null;
  const actresses = detail?.actresses ?? [];
  const files = detail?.files ?? [];
  // 详情接口把字段拆在 video/metadata/actresses 三处，这里临时还原成 Video，
  // 以复用列表卡片的 codeOf/titleOf/durationOf 等取值逻辑。
  const view: Video | null = video ? { ...video, metadata, actresses } : null;
  const [logs, setLogs] = useState<
    Array<{
      id: number;
      source_name: string;
      success: number;
      message: string;
      created_at: string;
    }>
  >([]);
  const videoId = detail?.video.id;
  const lastScraped = detail?.metadata?.last_scraped_at ?? "";

  // videoId 变化（切换详情）或 lastScraped 变化（重新刮削）时重载日志。
  useEffect(() => {
    if (videoId === undefined) return;
    let cancelled = false;
    api
      .getScrapeLogs(videoId)
      .then((data) => {
        if (!cancelled) setLogs(data.items as typeof logs);
      })
      .catch(() => {
        if (!cancelled) setLogs([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId, lastScraped]);

  const tags = Array.from(new Set([...(metadata?.genres ?? []), ...(metadata?.tags ?? [])]));
  const series = metadata?.series ?? null;

  return (
    <Modal
      title="视频详情"
      subtitle={view ? codeOf(view) || view.filename : "正在加载…"}
      onClose={onClose}
      wide
      tall
      headerActions={
        view && (
          <>
            <button
              type="button"
              onClick={onFavorite}
              className={`rounded-md p-1.5 transition hover:bg-rose-50 dark:hover:bg-rose-500/10 ${
                view.favorite
                  ? "text-rose-500 dark:text-rose-400"
                  : "text-zinc-400 hover:text-rose-500"
              }`}
              aria-label={view.favorite ? "取消收藏" : "收藏"}
            >
              <HeartIcon filled={view.favorite} className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={onScrape}
              className="rounded-md p-1.5 text-zinc-400 transition hover:bg-sky-50 hover:text-sky-600 dark:hover:bg-sky-500/10 dark:hover:text-sky-300"
              aria-label="刮削"
              title="重新刮削（保留已填写的手动字段，空字段会补全）"
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
          </>
        )
      }
    >
      {!view ? (
        <p className="py-16 text-center text-sm text-zinc-500">正在加载详情…</p>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          {/* 左栏：封面与主要操作，滚动时保持和右侧 tab 内容同一视觉层级。 */}
          <div>
            <div className="relative aspect-[16/10] overflow-hidden rounded-xl bg-zinc-100 dark:bg-zinc-800">
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
            </div>

            <div className="mt-4 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-lg font-semibold leading-snug text-zinc-900 dark:text-white">
                  {titleOf(view)}
                </h2>
                {metadata?.original_title && (
                  <p className="mt-1 text-sm text-zinc-500">{metadata.original_title}</p>
                )}
              </div>
              <span
                className={`shrink-0 rounded-md px-2 py-1 text-[11px] font-medium ${
                  metadata?.is_complete
                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                    : "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                }`}
              >
                {metadata?.is_complete ? "资料完整" : "待补全"}
              </span>
            </div>

            <div className="mt-3 flex flex-wrap gap-1.5">
              {codeOf(view) && (
                <span className={`rounded-md border px-2 py-0.5 font-mono text-[11px] ${CHIP_STYLES.neutral}`}>
                  {codeOf(view)}
                </span>
              )}
              {censoredLabel(metadata?.censored) && (
                <span className={`rounded-md border px-2 py-0.5 text-[11px] ${CHIP_STYLES.neutral}`}>
                  {censoredLabel(metadata?.censored)}
                </span>
              )}
              <span className={`rounded-md border px-2 py-0.5 text-[11px] ${CHIP_STYLES.neutral}`}>
                {view.present ? "文件存在" : "文件缺失"}
              </span>
              {files.length > 1 && (
                <span className={`rounded-md border px-2 py-0.5 text-[11px] ${CHIP_STYLES.neutral}`}>
                  {files.filter((file) => file.present).length}/{files.length} 个文件
                </span>
              )}
            </div>

            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={onPlay}
                disabled={playing || !view.present}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-sky-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <PlayIcon className="h-4 w-4" />
                {playing ? "正在启动…" : "播放"}
              </button>
              <button
                type="button"
                onClick={onDelete}
                className="inline-flex items-center justify-center rounded-lg border border-red-200 px-3 py-2.5 text-red-600 transition hover:bg-red-50 dark:border-red-500/20 dark:text-red-400 dark:hover:bg-red-500/10"
                aria-label="删除视频"
                title="删除视频（可选择是否删除文件）"
              >
                <TrashIcon className="h-4 w-4" />
              </button>
            </div>

          </div>

          {/* 右栏：固定高度内平铺全部信息，演员/标签/系列点击后触发筛选。 */}
          <div className="min-w-0 space-y-5">
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                基础信息
              </h3>
              <dl className="mt-1 grid gap-x-6 sm:grid-cols-2">
                <Field label="番号" value={codeOf(view)} />
                <Field label="发行日期" value={metadata?.release_date} />
                <Field label="时长" value={formatDuration(durationOf(view))} />
                <Field label="是否有码" value={censoredLabel(metadata?.censored)} />
                <Field label="国家/地区" value={metadata?.country} />
                <Field label="厂商" value={metadata?.studio} />
                <Field label="导演" value={metadata?.director} />
                <Field label="刮削来源" value={metadata?.source_name} />
                <Field label="入库时间" value={formatDate(view.created_at)} />
                <Field
                  label="简介"
                  wide
                  value={
                    metadata?.overview ? (
                      <span className="whitespace-pre-line leading-relaxed">
                        {metadata.overview}
                      </span>
                    ) : null
                  }
                />
              </dl>
            </section>

            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                演员{actresses.length > 0 ? `（${actresses.length}）` : ""}
              </h3>
              {actresses.length === 0 ? (
                <p className="mt-2 text-xs text-zinc-500">还没有关联演员。</p>
              ) : (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {actresses.map((actress) => (
                    <button
                      key={actress.id}
                      type="button"
                      onClick={() => onFilterActress(actress.id, actress.name)}
                      title={`按演员筛选：${actress.name}`}
                      className={`rounded-md border px-2.5 py-1 text-xs transition hover:brightness-95 ${CHIP_STYLES.violet}`}
                    >
                      {actress.name}
                    </button>
                  ))}
                </div>
              )}
            </section>

            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">标签</h3>
              {tags.length === 0 && !series ? (
                <p className="mt-2 text-xs text-zinc-500">还没有标签。</p>
              ) : (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {series && (
                    <button
                      type="button"
                      onClick={() => onFilterSeries(series)}
                      title={`按系列筛选：${series}`}
                      className={`rounded-md border px-2.5 py-1 text-xs transition hover:brightness-95 ${CHIP_STYLES.sky}`}
                    >
                      系列 · {series}
                    </button>
                  )}
                  {tags.map((tag) => (
                    <button
                      key={`tag-${tag}`}
                      type="button"
                      onClick={() => onFilterTag(tag)}
                      title={`按标签筛选：${tag}`}
                      className={`rounded-md border px-2.5 py-1 text-xs transition hover:brightness-95 ${CHIP_STYLES.orange}`}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              )}
            </section>

            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                文件{files.length > 0 ? `（${files.length}）` : ""}
              </h3>
              {files.length === 0 ? (
                <p className="mt-2 text-xs text-zinc-500">暂无文件记录。</p>
              ) : (
                <ul className="mt-1 divide-y divide-zinc-100 dark:divide-white/5">
                  {files.map((file) => (
                    <li key={file.id} className="py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 break-all text-sm text-zinc-800 dark:text-zinc-100">
                          {file.filename}
                        </span>
                        <span className="shrink-0 text-[10px] text-zinc-400">
                          {formatSize(file.size_bytes)}
                        </span>
                        <span
                          className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${
                            file.present
                              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                              : "bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-300"
                          }`}
                        >
                          {file.present ? "存在" : "缺失"}
                        </span>
                        <button
                          type="button"
                          onClick={() => onDeleteFile(file.id)}
                          className="shrink-0 rounded p-1 text-zinc-400 transition hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
                          aria-label={`删除 ${file.filename}`}
                          title="删除此文件"
                        >
                          <TrashIcon className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="mt-1 break-all font-mono text-[10px] text-zinc-400 dark:text-zinc-500">
                        {file.path}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* 原始特征和刮削日志默认折叠，排障时展开查看。 */}
            <details className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-white/10 dark:bg-white/[0.02]">
              <summary className="cursor-pointer text-xs font-medium text-zinc-500 dark:text-zinc-400">
                提取的特征
              </summary>
              <pre className="mt-2 overflow-x-auto text-xs text-zinc-600 dark:text-zinc-300">
                {JSON.stringify(view.features, null, 2)}
              </pre>
            </details>

            <details className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-white/10 dark:bg-white/[0.02]">
              <summary className="cursor-pointer text-xs font-medium text-zinc-500 dark:text-zinc-400">
                刮削日志{logs.length > 0 ? `（${logs.length}）` : ""}
              </summary>
              {logs.length === 0 ? (
                <p className="mt-2 text-xs text-zinc-500">暂无刮削记录。</p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {logs.map((entry) => (
                    <li key={entry.id} className="rounded-lg border border-zinc-100 p-2.5 text-xs dark:border-white/5">
                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                            entry.success
                              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                              : "bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-300"
                          }`}
                        >
                          {entry.success ? "成功" : "失败"}
                        </span>
                        <span className="font-medium text-zinc-700 dark:text-zinc-200">
                          {entry.source_name}
                        </span>
                        <span className="ml-auto text-[10px] text-zinc-400">
                          {formatDate(entry.created_at)}
                        </span>
                      </div>
                      <p className="mt-1 break-words leading-relaxed text-zinc-600 dark:text-zinc-300">
                        {entry.message}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </details>
          </div>
        </div>
      )}
    </Modal>
  );
}
