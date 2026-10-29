import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  api,
  type Job,
  type PlayerInfo,
  type ScanRoot,
  type Video,
  type VideoDetail,
} from "./api";

const PAGE_SIZE = 60;
type Filter = "present" | "missing" | "all";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function codeOf(video: Video): string {
  const feature = video.features.jav_code;
  return typeof feature === "string" ? feature : video.metadata?.code ?? "";
}

function titleOf(video: Video): string {
  const feature = video.features.title;
  return (
    video.metadata?.title ||
    (typeof feature === "string" ? feature : "") ||
    video.filename.replace(/\.[^.]+$/, "")
  );
}

function yearOf(video: Video): number | null {
  const feature = video.features.year;
  if (typeof feature === "number") return feature;
  return video.metadata?.year ?? null;
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDuration(seconds: number | null): string | null {
  if (!seconds) return null;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

function formatDate(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function gradient(seed: number): string {
  const hue = (seed * 47) % 360;
  return `linear-gradient(155deg, hsl(${hue} 32% 26%), hsl(${(hue + 55) % 360} 28% 11%))`;
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="border-b border-white/5 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-zinc-200">{value}</dd>
    </div>
  );
}

function VideoCard({ video, onSelect }: { video: Video; onSelect: (id: number) => void }) {
  const code = codeOf(video);
  const title = titleOf(video);
  const year = yearOf(video);
  return (
    <button
      type="button"
      onClick={() => onSelect(video.id)}
      className="group block text-left focus:outline-none"
    >
      <div className="relative aspect-[2/3] overflow-hidden rounded-xl border border-white/10 bg-zinc-900 shadow-lg shadow-black/30 transition duration-200 group-hover:-translate-y-0.5 group-hover:border-sky-400/50 group-focus-visible:ring-2 group-focus-visible:ring-sky-400">
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
          <div className="absolute inset-0 flex items-center justify-center text-4xl font-bold text-white/10">
            {code || "V"}
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/10 to-transparent" />
        <div className="absolute left-2 top-2 flex gap-1">
          {code && (
            <span className="rounded bg-sky-500/90 px-1.5 py-0.5 text-[11px] font-semibold text-white">
              {code}
            </span>
          )}
          {!video.present && (
            <span className="rounded bg-amber-400/90 px-1.5 py-0.5 text-[11px] font-semibold text-black">
              缺失
            </span>
          )}
        </div>
        <div className="absolute inset-x-0 bottom-0 p-3">
          <div className="line-clamp-2 text-sm font-medium text-white drop-shadow">{title}</div>
          <div className="mt-1 flex items-center gap-2 text-[11px] text-zinc-300">
            {year && <span>{year}</span>}
            <span>{formatSize(video.size_bytes)}</span>
          </div>
        </div>
      </div>
    </button>
  );
}

const JOB_LABELS: Record<Job["status"], string> = {
  queued: "排队中",
  running: "扫描中",
  succeeded: "已完成",
  failed: "失败",
  canceled: "已取消",
};

function JobBar({
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
    <div className="border-b border-white/10 bg-zinc-900/60">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3 px-6 py-2 text-sm">
        <span
          className={
            job.status === "failed"
              ? "font-medium text-red-400"
              : job.status === "succeeded"
                ? "font-medium text-emerald-400"
                : "font-medium text-sky-400"
          }
        >
          {JOB_LABELS[job.status]}
        </span>
        <div className="h-1.5 min-w-32 flex-1 overflow-hidden rounded-full bg-zinc-800">
          {percent === null ? (
            <div className="h-full w-1/3 animate-pulse rounded-full bg-sky-500" />
          ) : (
            <div
              className="h-full rounded-full bg-sky-500 transition-all"
              style={{ width: `${percent}%` }}
            />
          )}
        </div>
        <span className="tabular-nums text-zinc-400">
          {job.done}/{job.total}
        </span>
        <span className="max-w-[45%] truncate text-zinc-400" title={job.message ?? ""}>
          {job.message}
        </span>
        {active ? (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-white/10 px-2 py-1 text-xs text-zinc-300 hover:bg-white/5"
          >
            取消
          </button>
        ) : (
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md border border-white/10 px-2 py-1 text-xs text-zinc-300 hover:bg-white/5"
          >
            关闭
          </button>
        )}
      </div>
    </div>
  );
}

function DetailDrawer({
  detail,
  players,
  onClose,
  onPlay,
  onDelete,
  playing,
}: {
  detail: VideoDetail | null;
  players: PlayerInfo[];
  onClose: () => void;
  onPlay: () => void;
  onDelete: () => void;
  playing: boolean;
}) {
  const video = detail?.video;
  const metadata = detail?.metadata;
  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <aside
        className="h-full w-full max-w-md overflow-y-auto border-l border-white/10 bg-zinc-950 p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-white">
              {video ? titleOf({ ...video, metadata: metadata ?? null } as Video) : "加载中…"}
            </h2>
            {metadata?.original_title && (
              <p className="mt-1 text-sm text-zinc-400">{metadata.original_title}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-white/10 px-2 py-1 text-sm text-zinc-400 hover:bg-white/5"
            aria-label="关闭"
          >
            ×
          </button>
        </div>

        {!detail || !video ? (
          <p className="mt-8 text-sm text-zinc-500">正在加载详情…</p>
        ) : (
          <>
            <div className="mt-5 flex flex-wrap gap-2">
              {codeOf({ ...video, metadata: metadata ?? null } as Video) && (
                <span className="rounded bg-sky-500/15 px-2 py-1 text-xs font-medium text-sky-300">
                  {codeOf({ ...video, metadata: metadata ?? null } as Video)}
                </span>
              )}
              {metadata?.year && (
                <span className="rounded bg-white/5 px-2 py-1 text-xs text-zinc-300">
                  {metadata.year}
                </span>
              )}
              {!video.present && (
                <span className="rounded bg-amber-400/15 px-2 py-1 text-xs text-amber-300">文件缺失</span>
              )}
            </div>

            <div className="mt-6 flex flex-col gap-2">
              <button
                type="button"
                onClick={onPlay}
                disabled={playing || !video.present}
                className="rounded-lg bg-sky-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {playing ? "正在启动…" : "用本地播放器打开"}
              </button>
              <p className="text-center text-[11px] text-zinc-500">
                {players.length > 0
                  ? `已检测到：${players.map((player) => player.name).join(" / ")}`
                  : "未检测到播放器，可在 API 设置中指定路径"}
              </p>
            </div>

            <dl className="mt-6">
              <Field label="文件名" value={video.filename} />
              <Field label="番号" value={metadata?.code || String(video.features.jav_code ?? "")} />
              <Field label="大小" value={formatSize(video.size_bytes)} />
              <Field label="时长" value={formatDuration(video.duration_sec ?? metadata?.runtime_sec ?? null)} />
              <Field label="来源" value={metadata?.source_name} />
              <Field label="刮削状态" value={metadata?.scrape_status ?? "pending"} />
              <Field label="发行日期" value={metadata?.release_date} />
              <Field label="厂商" value={metadata?.studio} />
              <Field label="系列" value={metadata?.series} />
              <Field label="导演" value={metadata?.director} />
              <Field label="简介" value={metadata?.overview} />
              <Field label="路径" value={<span className="break-all text-xs text-zinc-400">{video.path}</span>} />
              <Field label="入库时间" value={formatDate(video.created_at)} />
              <Field label="最后更新" value={formatDate(video.updated_at)} />
            </dl>

            <details className="mt-4 rounded-lg border border-white/5 bg-white/[0.02] p-3">
              <summary className="cursor-pointer text-xs text-zinc-400">提取的特征</summary>
              <pre className="mt-2 overflow-x-auto text-xs text-zinc-300">
                {JSON.stringify(video.features, null, 2)}
              </pre>
            </details>

            <button
              type="button"
              onClick={onDelete}
              className="mt-8 w-full rounded-lg border border-red-500/30 px-4 py-2 text-xs text-red-400 hover:bg-red-500/10"
            >
              从库中删除记录（不删除文件）
            </button>
          </>
        )}
      </aside>
    </div>
  );
}

export default function App() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("present");
  const [roots, setRoots] = useState<ScanRoot[]>([]);
  const [players, setPlayers] = useState<PlayerInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<VideoDetail | null>(null);
  const [playing, setPlaying] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [newRoot, setNewRoot] = useState("");

  const loadRoots = useCallback(async () => {
    try {
      const data = await api.listRoots();
      setRoots(data.items);
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }, []);

  useEffect(() => {
    void loadRoots();
    api
      .listPlayers()
      .then((data) => setPlayers(data.players))
      .catch(() => setPlayers([]));
  }, [loadRoots]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    setPage(1);
  }, [debouncedQuery, filter]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .listVideos({
        page,
        pageSize: PAGE_SIZE,
        q: debouncedQuery || undefined,
        present: filter === "all" ? undefined : filter === "present",
      })
      .then((data) => {
        if (cancelled) return;
        setVideos(data.items);
        setTotal(data.total);
      })
      .catch((error) => {
        if (!cancelled) setBanner(errorMessage(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, debouncedQuery, filter, refreshKey]);

  useEffect(() => {
    if (activeJobId === null) return;
    let stopped = false;
    const poll = async () => {
      try {
        const current = await api.getJob(activeJobId);
        if (stopped) return;
        setJob(current);
        if (["succeeded", "failed", "canceled"].includes(current.status)) {
          setActiveJobId(null);
          setRefreshKey((key) => key + 1);
          void loadRoots();
        }
      } catch (error) {
        if (!stopped) {
          setBanner(errorMessage(error));
          setActiveJobId(null);
        }
      }
    };
    void poll();
    const timer = window.setInterval(poll, 700);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [activeJobId, loadRoots]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    api
      .getVideo(selectedId)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((error) => {
        if (cancelled) return;
        setBanner(errorMessage(error));
        setSelectedId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, refreshKey]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const scanning = activeJobId !== null;
  const activeFilterLabel = useMemo(() => {
    if (filter === "missing") return "缺失";
    if (filter === "all") return "全部";
    return "在库";
  }, [filter]);

  async function startScan(rootId?: number) {
    setBanner(null);
    try {
      const { job_id } = await api.createScan(rootId);
      setJob({
        id: job_id,
        type: "scan",
        status: "queued",
        total: 0,
        done: 0,
        failed: 0,
        payload: {},
        message: "任务排队中…",
        cancel_requested: false,
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
      });
      setActiveJobId(job_id);
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function cancelScan() {
    if (!job) return;
    try {
      setJob(await api.cancelJob(job.id));
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function addRoot(event: FormEvent) {
    event.preventDefault();
    const path = newRoot.trim();
    if (!path) return;
    try {
      await api.createRoot(path);
      setNewRoot("");
      await loadRoots();
      setNotice("扫描目录已添加");
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function removeRoot(root: ScanRoot) {
    if (!window.confirm(`移除扫描目录？\n${root.path}\n\n不会删除文件。`)) return;
    try {
      await api.deleteRoot(root.id);
      await loadRoots();
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function playSelected() {
    if (selectedId === null) return;
    setPlaying(true);
    try {
      const result = await api.playVideo(selectedId);
      setNotice(`已用 ${result.player} 启动播放（pid ${result.pid}）`);
    } catch (error) {
      setBanner(errorMessage(error));
    } finally {
      setPlaying(false);
    }
  }

  async function deleteSelected() {
    if (selectedId === null) return;
    if (!window.confirm("从库中删除该记录？不会删除视频文件。")) return;
    try {
      await api.deleteVideo(selectedId);
      setSelectedId(null);
      setRefreshKey((key) => key + 1);
      setNotice("记录已删除");
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="sticky top-0 z-30 border-b border-white/10 bg-zinc-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-4 px-6 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500 text-sm font-black text-white">
              V
            </div>
            <span className="text-lg font-semibold tracking-wide">VBob</span>
          </div>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题 / 文件名 / 番号"
            className="min-w-48 flex-1 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-sky-400/60 focus:outline-none"
          />
          <span className="hidden text-xs text-zinc-500 sm:block">
            {total} 个视频 · {activeFilterLabel}
          </span>
          <button
            type="button"
            onClick={() => void startScan()}
            disabled={scanning || roots.length === 0}
            className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {scanning ? "扫描中…" : "扫描"}
          </button>
        </div>
      </header>

      {job && <JobBar job={job} onCancel={() => void cancelScan()} onDismiss={() => setJob(null)} />}

      {banner && (
        <div className="mx-auto mt-4 flex max-w-[1600px] items-center justify-between gap-4 px-6">
          <div className="flex-1 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-300">
            {banner}
          </div>
          <button
            type="button"
            onClick={() => setBanner(null)}
            className="rounded-md border border-white/10 px-2 py-1 text-xs text-zinc-400 hover:bg-white/5"
          >
            关闭
          </button>
        </div>
      )}

      <div className="mx-auto flex max-w-[1600px] items-start gap-6 px-6 py-6">
        <aside className="w-64 shrink-0 space-y-5">
          <section className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <h2 className="px-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
              扫描目录
            </h2>
            <ul className="mt-2 space-y-1.5">
              {roots.length === 0 && (
                <li className="px-1 py-2 text-xs text-zinc-500">还没有扫描目录</li>
              )}
              {roots.map((root) => (
                <li
                  key={root.id}
                  className="group rounded-lg border border-white/5 bg-white/[0.02] px-2 py-1.5"
                >
                  <div className="flex items-start gap-1">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs text-zinc-300" title={root.path}>
                        {root.path}
                      </div>
                      <div className="mt-0.5 text-[10px] text-zinc-500">
                        {root.last_scan_at ? `上次扫描 ${formatDate(root.last_scan_at)}` : "尚未扫描"}
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-0.5 opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100">
                      <button
                        type="button"
                        onClick={() => void startScan(root.id)}
                        disabled={scanning}
                        title="扫描此目录"
                        aria-label="扫描此目录"
                        className="rounded px-1 text-xs text-sky-400 hover:bg-white/5 disabled:opacity-40"
                      >
                        ▶
                      </button>
                      <button
                        type="button"
                        onClick={() => void removeRoot(root)}
                        title="移除目录"
                        aria-label="移除目录"
                        className="rounded px-1 text-xs text-zinc-500 hover:bg-white/5 hover:text-red-400"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
            <form onSubmit={(event) => void addRoot(event)} className="mt-3 space-y-2">
              <input
                value={newRoot}
                onChange={(event) => setNewRoot(event.target.value)}
                placeholder="D:\Media 或 /media/videos"
                className="w-full rounded-md border border-white/10 bg-zinc-900 px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-sky-400/60 focus:outline-none"
              />
              <button
                type="submit"
                className="w-full rounded-md border border-white/10 px-2 py-1.5 text-xs text-zinc-300 hover:bg-white/5"
              >
                添加目录
              </button>
            </form>
          </section>

          <section className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <h2 className="px-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
              筛选
            </h2>
            <div className="mt-2 grid grid-cols-3 gap-1 rounded-lg bg-zinc-900 p-1">
              {(
                [
                  ["present", "在库"],
                  ["missing", "缺失"],
                  ["all", "全部"],
                ] as [Filter, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setFilter(value)}
                  className={
                    filter === value
                      ? "rounded-md bg-sky-500 px-2 py-1 text-xs font-medium text-white"
                      : "rounded-md px-2 py-1 text-xs text-zinc-400 hover:bg-white/5"
                  }
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <h2 className="px-1 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
              播放器
            </h2>
            {players.length === 0 ? (
              <p className="mt-2 px-1 text-xs text-zinc-500">
                未检测到播放器。安装 mpv / VLC / PotPlayer 后重启服务。
              </p>
            ) : (
              <ul className="mt-2 space-y-1">
                {players.map((player) => (
                  <li key={player.path} className="truncate px-1 text-xs text-zinc-300" title={player.path}>
                    {player.name}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>

        <main className="min-w-0 flex-1">
          {loading && videos.length === 0 ? (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">
              {Array.from({ length: 12 }).map((_, index) => (
                <div key={index} className="aspect-[2/3] animate-pulse rounded-xl bg-zinc-900" />
              ))}
            </div>
          ) : videos.length === 0 ? (
            <div className="rounded-xl border border-dashed border-white/10 px-6 py-24 text-center">
              <p className="text-sm text-zinc-400">
                {roots.length === 0
                  ? "先在左侧添加一个扫描目录。"
                  : debouncedQuery
                    ? "没有匹配的视频。"
                    : "这个目录里还没有扫描到视频。"}
              </p>
              {roots.length > 0 && !debouncedQuery && (
                <button
                  type="button"
                  onClick={() => void startScan()}
                  disabled={scanning}
                  className="mt-4 rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-40"
                >
                  开始扫描
                </button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">
              {videos.map((video) => (
                <VideoCard key={video.id} video={video} onSelect={setSelectedId} />
              ))}
            </div>
          )}

          {total > PAGE_SIZE && (
            <div className="mt-8 flex items-center justify-center gap-3 text-sm text-zinc-400">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1}
                className="rounded-md border border-white/10 px-3 py-1.5 hover:bg-white/5 disabled:opacity-30"
              >
                上一页
              </button>
              <span className="tabular-nums">
                {page} / {pageCount}
              </span>
              <button
                type="button"
                onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
                disabled={page >= pageCount}
                className="rounded-md border border-white/10 px-3 py-1.5 hover:bg-white/5 disabled:opacity-30"
              >
                下一页
              </button>
            </div>
          )}
        </main>
      </div>

      {selectedId !== null && (
        <DetailDrawer
          detail={detail}
          players={players}
          onClose={() => setSelectedId(null)}
          onPlay={() => void playSelected()}
          onDelete={() => void deleteSelected()}
          playing={playing}
        />
      )}

      {notice && (
        <div className="fixed bottom-6 right-6 z-50 rounded-lg border border-sky-500/30 bg-zinc-900 px-4 py-2 text-sm text-sky-200 shadow-xl">
          {notice}
        </div>
      )}
    </div>
  );
}
