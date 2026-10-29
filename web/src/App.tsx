import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, type Job, type Video, type VideoDetail } from "./api";
import { DetailDrawer } from "./components/DetailDrawer";
import { JobBar } from "./components/JobBar";
import { SettingsPage } from "./components/SettingsPage";
import { VideoCard } from "./components/VideoCard";
import {
  DatabaseIcon,
  FilmIcon,
  MissingIcon,
  MoonIcon,
  ScanIcon,
  SearchIcon,
  SettingsIcon,
  SunIcon,
} from "./components/Icons";
import { errorMessage } from "./format";
import { applyTheme, readTheme, type Theme } from "./theme";

const PAGE_SIZE = 60;
type Filter = "present" | "missing" | "all";
type View = "library" | "settings";

const SORT_OPTIONS = [
  ["updated_at", "加入时间：近→远"],
  ["filename", "文件名"],
  ["year", "年份"],
  ["code", "番号"],
] as const;

function NavButton({
  icon,
  label,
  active,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
        active
          ? "bg-sky-50 font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-300"
          : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5"
      }`}
    >
      {icon}
      <span className="hidden lg:inline">{label}</span>
    </button>
  );
}

function initialView(): View {
  const requested = new URLSearchParams(window.location.search).get("view");
  return requested === "settings" ? "settings" : "library";
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [view, setView] = useState<View>(initialView);
  const [filter, setFilter] = useState<Filter>("present");
  const [sort, setSort] = useState<string>("updated_at");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [videos, setVideos] = useState<Video[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<VideoDetail | null>(null);
  const [playing, setPlaying] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    setPage(1);
  }, [debouncedQuery, filter, sort]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .listVideos({
        page,
        pageSize: PAGE_SIZE,
        q: debouncedQuery || undefined,
        present: filter === "all" ? undefined : filter === "present",
        sort,
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
  }, [page, debouncedQuery, filter, sort, refreshKey]);

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
  }, [activeJobId]);

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

  const startScan = useCallback(async (rootId?: number) => {
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
  }, []);

  async function cancelScan() {
    if (!job) return;
    try {
      setJob(await api.cancelJob(job.id));
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function playVideo(id: number) {
    try {
      const result = await api.playVideo(id);
      setNotice(`已用 ${result.player} 启动播放（pid ${result.pid}）`);
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function playSelected() {
    if (selectedId === null) return;
    setPlaying(true);
    try {
      await playVideo(selectedId);
    } finally {
      setPlaying(false);
    }
  }

  async function removeVideo(id: number) {
    if (!window.confirm("从库中删除该记录？不会删除视频文件。")) return;
    try {
      await api.deleteVideo(id);
      if (selectedId === id) setSelectedId(null);
      setRefreshKey((key) => key + 1);
      setNotice("记录已删除");
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  function openLibrary(nextFilter: Filter) {
    setFilter(nextFilter);
    setView("library");
  }

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const scanning = activeJobId !== null;
  const title =
    filter === "missing" ? "缺失文件" : filter === "all" ? "全部视频" : "视频库";

  return (
    <div className="flex min-h-screen bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <aside className="sticky top-0 flex h-screen w-16 shrink-0 flex-col border-r border-zinc-200 bg-white px-2 py-4 lg:w-60 lg:px-3 dark:border-white/10 dark:bg-zinc-900/70">
        <div className="flex items-center gap-2 px-1.5 py-1">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-indigo-500 text-sm font-black text-white shadow-md shadow-sky-500/20">
            V
          </div>
          <div className="hidden min-w-0 lg:block">
            <div className="truncate text-sm font-semibold tracking-wide">VBob</div>
            <div className="text-[10px] text-zinc-500">本地视频库</div>
          </div>
        </div>

        <nav className="mt-6 space-y-1">
          <NavButton
            icon={<FilmIcon className="h-4 w-4" />}
            label="视频库"
            active={view === "library" && filter === "present"}
            onClick={() => openLibrary("present")}
          />
          <NavButton
            icon={<MissingIcon className="h-4 w-4" />}
            label="缺失文件"
            active={view === "library" && filter === "missing"}
            onClick={() => openLibrary("missing")}
          />
          <NavButton
            icon={<DatabaseIcon className="h-4 w-4" />}
            label="全部视频"
            active={view === "library" && filter === "all"}
            onClick={() => openLibrary("all")}
          />
        </nav>

        <div className="mt-auto space-y-1 border-t border-zinc-100 pt-3 dark:border-white/5">
          <NavButton
            icon={
              theme === "dark" ? (
                <SunIcon className="h-4 w-4" />
              ) : (
                <MoonIcon className="h-4 w-4" />
              )
            }
            label={theme === "dark" ? "浅色主题" : "深色主题"}
            active={false}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          />
          <NavButton
            icon={<SettingsIcon className="h-4 w-4" />}
            label="设置"
            active={view === "settings"}
            onClick={() => setView("settings")}
          />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {job && (
          <JobBar job={job} onCancel={() => void cancelScan()} onDismiss={() => setJob(null)} />
        )}

        {banner && (
          <div className="flex items-center gap-3 border-b border-red-200 bg-red-50 px-6 py-2 text-sm text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
            <span className="min-w-0 flex-1 truncate">{banner}</span>
            <button
              type="button"
              onClick={() => setBanner(null)}
              className="shrink-0 text-xs underline-offset-2 hover:underline"
            >
              关闭
            </button>
          </div>
        )}

        {view === "library" ? (
          <>
            <header className="sticky top-0 z-30 border-b border-zinc-200 bg-zinc-50/90 backdrop-blur dark:border-white/10 dark:bg-zinc-950/85">
              <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3 px-6 py-3">
                <div className="mr-2 min-w-24">
                  <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
                  <p className="text-[11px] text-zinc-500">{total} 项</p>
                </div>

                <div className="relative min-w-48 flex-1">
                  <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="搜索标题 / 文件名 / 番号"
                    className="w-full rounded-lg border border-zinc-200 bg-white py-2 pl-9 pr-3 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-600"
                  />
                </div>

                <select
                  value={sort}
                  onChange={(event) => setSort(event.target.value)}
                  className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-600 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-300"
                >
                  {SORT_OPTIONS.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>

                <button
                  type="button"
                  onClick={() => void startScan()}
                  disabled={scanning}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ScanIcon className="h-4 w-4" />
                  {scanning ? "扫描中…" : "扫描"}
                </button>
              </div>
            </header>

            <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-6">
              {loading && videos.length === 0 ? (
                <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                  {Array.from({ length: 8 }).map((_, index) => (
                    <div
                      key={index}
                      className="h-80 animate-pulse rounded-2xl bg-zinc-200/70 dark:bg-zinc-900"
                    />
                  ))}
                </div>
              ) : videos.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-300 px-6 py-24 text-center dark:border-white/10">
                  <FilmIcon className="h-10 w-10 text-zinc-300 dark:text-zinc-700" />
                  <p className="mt-4 text-sm text-zinc-500">
                    {debouncedQuery
                      ? "没有匹配的视频"
                      : filter === "missing"
                        ? "没有缺失文件"
                        : "还没有扫描到视频"}
                  </p>
                  {!debouncedQuery && filter !== "missing" && (
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
                <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                  {videos.map((video) => (
                    <VideoCard
                      key={video.id}
                      video={video}
                      onSelect={setSelectedId}
                      onPlay={(id) => void playVideo(id)}
                      onDelete={(id) => void removeVideo(id)}
                    />
                  ))}
                </div>
              )}

              {total > PAGE_SIZE && (
                <div className="mt-8 flex items-center justify-center gap-3 text-sm text-zinc-500">
                  <button
                    type="button"
                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                    disabled={page <= 1}
                    className="rounded-md border border-zinc-200 px-3 py-1.5 transition hover:bg-white disabled:opacity-30 dark:border-white/10 dark:hover:bg-white/5"
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
                    className="rounded-md border border-zinc-200 px-3 py-1.5 transition hover:bg-white disabled:opacity-30 dark:border-white/10 dark:hover:bg-white/5"
                  >
                    下一页
                  </button>
                </div>
              )}
            </main>
          </>
        ) : (
          <SettingsPage
            theme={theme}
            onThemeChange={setTheme}
            onStartScan={(rootId) => void startScan(rootId)}
            scanning={scanning}
            refreshKey={refreshKey}
          />
        )}
      </div>

      {selectedId !== null && (
        <DetailDrawer
          detail={detail}
          onClose={() => setSelectedId(null)}
          onPlay={() => void playSelected()}
          onDelete={() => void removeVideo(selectedId)}
          playing={playing}
        />
      )}

      {notice && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl border border-sky-200 bg-white px-4 py-2.5 text-sm text-sky-700 shadow-xl dark:border-sky-500/30 dark:bg-zinc-900 dark:text-sky-300">
          {notice}
        </div>
      )}
    </div>
  );
}
