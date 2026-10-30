import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  api,
  type Actress,
  type ActressDetail,
  type Job,
  type Video,
  type VideoDetail,
} from "./api";
import { ActressCard } from "./components/ActressCard";
import { ActressDetailDrawer } from "./components/ActressDetailDrawer";
import { ActressEditModal } from "./components/ActressEditModal";
import { DetailDrawer } from "./components/DetailDrawer";
import { JobBar } from "./components/JobBar";
import { SettingsModal } from "./components/SettingsModal";
import { VideoCard } from "./components/VideoCard";
import { VideoEditModal } from "./components/VideoEditModal";
import {
  FilmIcon,
  HeartIcon,
  MoonIcon,
  ScanIcon,
  SearchIcon,
  SettingsIcon,
  SunIcon,
  UserIcon,
} from "./components/Icons";
import { errorMessage } from "./format";
import { applyTheme, readTheme, type Theme } from "./theme";

const PAGE_SIZE = 60;
type View = "videos" | "actresses" | "favorites-videos" | "favorites-actresses";

const VIDEO_SORTS = [
  ["updated_at", "加入时间：近→远"],
  ["filename", "文件名"],
  ["year", "年份"],
  ["code", "番号"],
] as const;
const ACTRESS_SORTS = [
  ["video_count", "作品数：多→少"],
  ["name", "姓名"],
  ["birth_date", "出生日期"],
] as const;

function NavButton({
  icon,
  label,
  active,
  onClick,
  indent = false,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  indent?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={`flex w-full items-center gap-3 rounded-lg py-2 text-sm transition ${
        indent ? "pl-6 pr-3" : "px-3"
      } ${
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

export default function App() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [view, setView] = useState<View>("videos");
  const [favoritesOpen, setFavoritesOpen] = useState(true);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [videoSort, setVideoSort] = useState<string>("updated_at");
  const [actressSort, setActressSort] = useState<string>("video_count");
  const [videos, setVideos] = useState<Video[]>([]);
  const [actresses, setActresses] = useState<Actress[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null);
  const [videoDetail, setVideoDetail] = useState<VideoDetail | null>(null);
  const [editingVideo, setEditingVideo] = useState(false);
  const [selectedActressId, setSelectedActressId] = useState<number | null>(null);
  const [actressDetail, setActressDetail] = useState<ActressDetail | null>(null);
  const [editingActress, setEditingActress] = useState(false);
  const [playing, setPlaying] = useState(false);

  const isVideoView = view === "videos" || view === "favorites-videos";

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    setPage(1);
  }, [view, debouncedQuery, videoSort, actressSort]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const request = isVideoView
      ? api
          .listVideos({
            page,
            pageSize: PAGE_SIZE,
            q: debouncedQuery || undefined,
            sort: videoSort,
            favorite: view === "favorites-videos" ? true : undefined,
          })
          .then((data) => {
            if (cancelled) return;
            setVideos(data.items);
            setTotal(data.total);
          })
      : api
          .listActresses({
            page,
            pageSize: PAGE_SIZE,
            q: debouncedQuery || undefined,
            sort: actressSort,
            favorite: view === "favorites-actresses" ? true : undefined,
          })
          .then((data) => {
            if (cancelled) return;
            setActresses(data.items);
            setTotal(data.total);
          });
    request
      .catch((error) => {
        if (!cancelled) setBanner(errorMessage(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, page, debouncedQuery, videoSort, actressSort, refreshKey, isVideoView]);

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
    if (selectedVideoId === null) {
      setVideoDetail(null);
      return;
    }
    let cancelled = false;
    api
      .getVideo(selectedVideoId)
      .then((data) => {
        if (!cancelled) setVideoDetail(data);
      })
      .catch((error) => {
        if (!cancelled) {
          setBanner(errorMessage(error));
          setSelectedVideoId(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedVideoId, refreshKey]);

  useEffect(() => {
    if (selectedActressId === null) {
      setActressDetail(null);
      return;
    }
    let cancelled = false;
    api
      .getActress(selectedActressId)
      .then((data) => {
        if (!cancelled) setActressDetail(data);
      })
      .catch((error) => {
        if (!cancelled) {
          setBanner(errorMessage(error));
          setSelectedActressId(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedActressId, refreshKey]);

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
        root_id: rootId ?? null,
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

  function trackJob(jobId: string, type: string, rootId: number | null) {
    setJob({
      id: jobId,
      type,
      status: "queued",
      total: 0,
      done: 0,
      failed: 0,
      payload: {},
      message: "任务排队中…",
      cancel_requested: false,
      root_id: rootId,
      created_at: new Date().toISOString(),
      started_at: null,
      finished_at: null,
    });
    setActiveJobId(jobId);
  }

  async function startVideoScrape(videoId: number) {
    setBanner(null);
    try {
      const { job_id } = await api.scrapeVideo(videoId, true);
      trackJob(job_id, "scrape_one", null);
      setNotice("刮削任务已开始");
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function startRootScrape(rootId: number) {
    setBanner(null);
    try {
      const { job_id } = await api.scrapeRoot(rootId);
      trackJob(job_id, "scrape_batch", rootId);
      setNotice("批量刮削任务已开始");
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function startActressScrape(actressId: number) {
    setBanner(null);
    try {
      const { job_id } = await api.scrapeActress(actressId, true);
      trackJob(job_id, "scrape_actress", null);
      setNotice("演员刮削任务已开始");
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
    if (selectedVideoId === null) return;
    setPlaying(true);
    try {
      await playVideo(selectedVideoId);
    } finally {
      setPlaying(false);
    }
  }

  async function removeVideo(id: number) {
    if (!window.confirm("从库中删除该记录？不会删除视频文件。")) return;
    try {
      await api.deleteVideo(id);
      setSelectedVideoId(null);
      setRefreshKey((key) => key + 1);
      setNotice("记录已删除");
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function removeActress(id: number) {
    if (!window.confirm("删除该演员？有关联视频时无法删除。")) return;
    try {
      await api.deleteActress(id);
      setSelectedActressId(null);
      setRefreshKey((key) => key + 1);
      setNotice("演员已删除");
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function toggleVideoFavorite(id: number, favorite: boolean) {
    try {
      const updated = await api.setVideoFavorite(id, favorite);
      setVideos((current) =>
        current.map((video) =>
          video.id === id ? { ...video, favorite: updated.video.favorite } : video,
        ),
      );
      if (selectedVideoId === id) setVideoDetail(updated);
      if (view === "favorites-videos") setRefreshKey((key) => key + 1);
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function addActress() {
    const name = window.prompt("新增演员姓名");
    if (!name || !name.trim()) return;
    try {
      const created = await api.createActress(name.trim());
      setRefreshKey((key) => key + 1);
      setSelectedActressId(created.id);
      setNotice("演员已创建，请补充资料");
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  async function toggleActressFavorite(id: number, favorite: boolean) {
    try {
      const updated = await api.setActressFavorite(id, favorite);
      setActresses((current) =>
        current.map((actress) =>
          actress.id === id ? { ...actress, favorite: updated.favorite } : actress,
        ),
      );
      if (selectedActressId === id && actressDetail) {
        setActressDetail({ ...actressDetail, actress: updated });
      }
      if (view === "favorites-actresses") setRefreshKey((key) => key + 1);
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  function openVideo(id: number) {
    setSelectedActressId(null);
    setSelectedVideoId(id);
  }

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const scanning = activeJobId !== null;
  const title =
    view === "videos"
      ? "视频"
      : view === "actresses"
        ? "演员"
        : view === "favorites-videos"
          ? "收藏的视频"
          : "收藏的演员";

  const sortOptions = isVideoView ? VIDEO_SORTS : ACTRESS_SORTS;
  const sortValue = isVideoView ? videoSort : actressSort;

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
            label="视频"
            active={view === "videos"}
            onClick={() => setView("videos")}
          />
          <NavButton
            icon={<UserIcon className="h-4 w-4" />}
            label="演员"
            active={view === "actresses"}
            onClick={() => setView("actresses")}
          />
          <NavButton
            icon={<HeartIcon className="h-4 w-4" />}
            label="收藏"
            active={view.startsWith("favorites")}
            onClick={() => setFavoritesOpen((open) => !open)}
          />
          {favoritesOpen && (
            <div className="space-y-1">
              <NavButton
                icon={<FilmIcon className="h-3.5 w-3.5" />}
                label="收藏的视频"
                active={view === "favorites-videos"}
                onClick={() => setView("favorites-videos")}
                indent
              />
              <NavButton
                icon={<UserIcon className="h-3.5 w-3.5" />}
                label="收藏的演员"
                active={view === "favorites-actresses"}
                onClick={() => setView("favorites-actresses")}
                indent
              />
            </div>
          )}
        </nav>

        <div className="mt-auto space-y-1 border-t border-zinc-100 pt-3 dark:border-white/5">
          <NavButton
            icon={theme === "dark" ? <SunIcon className="h-4 w-4" /> : <MoonIcon className="h-4 w-4" />}
            label={theme === "dark" ? "浅色主题" : "深色主题"}
            active={false}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          />
          <NavButton
            icon={<SettingsIcon className="h-4 w-4" />}
            label="设置"
            active={settingsOpen}
            onClick={() => setSettingsOpen(true)}
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
                placeholder={isVideoView ? "搜索标题 / 文件名 / 番号 / 演员" : "搜索演员姓名"}
                className="w-full rounded-lg border border-zinc-200 bg-white py-2 pl-9 pr-3 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-600"
              />
            </div>
            <select
              value={sortValue}
              onChange={(event) =>
                isVideoView ? setVideoSort(event.target.value) : setActressSort(event.target.value)
              }
              className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-600 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-300"
            >
              {sortOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            {isVideoView ? (
              <button
                type="button"
                onClick={() => void startScan()}
                disabled={scanning}
                className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ScanIcon className="h-4 w-4" />
                {scanning ? "扫描中…" : "扫描"}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void addActress()}
                className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400"
              >
                新增演员
              </button>
            )}
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-6">
          {loading && ((isVideoView && videos.length === 0) || (!isVideoView && actresses.length === 0)) ? (
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {Array.from({ length: 8 }).map((_, index) => (
                <div
                  key={index}
                  className="h-80 animate-pulse rounded-2xl bg-zinc-200/70 dark:bg-zinc-900"
                />
              ))}
            </div>
          ) : isVideoView ? (
            videos.length === 0 ? (
              <Empty
                icon={<FilmIcon className="h-10 w-10 text-zinc-300 dark:text-zinc-700" />}
                text={
                  debouncedQuery
                    ? "没有匹配的视频"
                    : view === "favorites-videos"
                      ? "还没有收藏的视频"
                      : "还没有扫描到视频"
                }
              />
            ) : (
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {videos.map((video) => (
                  <VideoCard
                    key={video.id}
                    video={video}
                    onSelect={openVideo}
                    onPlay={(id) => void playVideo(id)}
                    onDelete={(id) => void removeVideo(id)}
                    onFavorite={(id, favorite) => void toggleVideoFavorite(id, favorite)}
                  />
                ))}
              </div>
            )
          ) : actresses.length === 0 ? (
            <Empty
              icon={<UserIcon className="h-10 w-10 text-zinc-300 dark:text-zinc-700" />}
              text={
                debouncedQuery
                  ? "没有匹配的演员"
                  : view === "favorites-actresses"
                    ? "还没有收藏的演员"
                    : "还没有演员资料，刮削或编辑视频后会自动建立"
              }
            />
          ) : (
            <div className="grid grid-cols-2 gap-5 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
              {actresses.map((actress) => (
                <ActressCard
                  key={actress.id}
                  actress={actress}
                  onSelect={setSelectedActressId}
                  onFavorite={(id, favorite) => void toggleActressFavorite(id, favorite)}
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
      </div>

      {selectedVideoId !== null && (
        <DetailDrawer
          detail={videoDetail}
          onClose={() => setSelectedVideoId(null)}
          onPlay={() => void playSelected()}
          onDelete={() => void removeVideo(selectedVideoId)}
          onEdit={() => setEditingVideo(true)}
          onScrape={() => void startVideoScrape(selectedVideoId)}
          onFavorite={() =>
            void toggleVideoFavorite(selectedVideoId, !(videoDetail?.video.favorite ?? false))
          }
          playing={playing}
        />
      )}

      {editingVideo && videoDetail && (
        <VideoEditModal
          detail={videoDetail}
          onClose={() => setEditingVideo(false)}
          onSaved={() => {
            setEditingVideo(false);
            setRefreshKey((key) => key + 1);
            setNotice("视频信息已保存");
          }}
        />
      )}

      {selectedActressId !== null && (
        <ActressDetailDrawer
          detail={actressDetail}
          onClose={() => setSelectedActressId(null)}
          onEdit={() => setEditingActress(true)}
          onScrape={() => void startActressScrape(selectedActressId)}
          onFavorite={() =>
            void toggleActressFavorite(
              selectedActressId,
              !(actressDetail?.actress.favorite ?? false),
            )
          }
          onDelete={() => void removeActress(selectedActressId)}
          onSelectVideo={openVideo}
        />
      )}

      {editingActress && actressDetail && (
        <ActressEditModal
          detail={actressDetail}
          onClose={() => setEditingActress(false)}
          onSaved={() => {
            setEditingActress(false);
            setRefreshKey((key) => key + 1);
            setNotice("演员资料已保存");
          }}
        />
      )}

      {settingsOpen && (
        <SettingsModal
          onClose={() => setSettingsOpen(false)}
          onStartScan={(rootId) => void startScan(rootId)}
          onScrape={(rootId) => void startRootScrape(rootId)}
          onChanged={() => setRefreshKey((key) => key + 1)}
          scanning={scanning}
          refreshKey={refreshKey}
        />
      )}

      {notice && (
        <div className="fixed bottom-6 right-6 z-[60] rounded-xl border border-sky-200 bg-white px-4 py-2.5 text-sm text-sky-700 shadow-xl dark:border-sky-500/30 dark:bg-zinc-900 dark:text-sky-300">
          {notice}
        </div>
      )}
    </div>
  );
}

function Empty({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-300 px-6 py-24 text-center dark:border-white/10">
      {icon}
      <p className="mt-4 text-sm text-zinc-500">{text}</p>
    </div>
  );
}
