/**
 * 应用主组件。
 * 集中管理当前视图、搜索分页、任务轮询，以及详情/编辑弹窗的选中状态；
 * 子组件只上报用户操作，数据加载和操作后的刷新统一在这里完成。
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  api,
  type Actress,
  type ActressDetail,
  type Job,
  type Video,
  type VideoDetail,
  type VideoFile,
} from "./api";
import { ActressCard } from "./components/ActressCard";
import { ActressDetailDrawer } from "./components/ActressDetailDrawer";
import { ActressEditModal } from "./components/ActressEditModal";
import { DeleteVideoModal } from "./components/DeleteVideoModal";
import { VideoDetailModal } from "./components/VideoDetailModal";
import { VideoFilePicker } from "./components/VideoFilePicker";
import { JobBar } from "./components/JobBar";
import { SettingsModal } from "./components/SettingsModal";
import { VideoCard } from "./components/VideoCard";
import { VideoEditModal } from "./components/VideoEditModal";
import {
  FilmIcon,
  HeartIcon,
  MoonIcon,
  SearchIcon,
  ShuffleIcon,
  SettingsIcon,
  SunIcon,
  UserIcon,
} from "./components/Icons";
import { errorMessage } from "./format";
import { applyTheme, readTheme, type Theme } from "./theme";

const PAGE_SIZE = 60;

/** 随机排序种子，避开 0，保证后端乘法散列能打乱顺序。 */
function newRandomSeed(): number {
  return Math.floor(Math.random() * 2_147_483_646) + 1;
}
// 收藏视图复用同一套列表请求，仅额外携带 favorite 参数。
type View = "videos" | "actresses" | "favorites-videos" | "favorites-actresses";

// 排序值直接使用后端字段名，作为下拉框的 value 传给接口。
const VIDEO_SORTS = [
  ["updated_at", "加入时间：近→远"],
  ["filename", "文件名"],
  ["year", "年份"],
  ["code", "番号"],
  ["random", "随机顺序"],
] as const;
const ACTRESS_SORTS = [
  ["video_count", "作品数：多→少"],
  ["name", "姓名"],
  ["birth_date", "出生日期"],
] as const;

/** 当前筛选条件的小标签，点击 × 单独清除。 */
function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-sky-200 bg-white px-2 py-0.5 text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300">
      {label}
      <button
        type="button"
        onClick={onClear}
        className="rounded px-0.5 text-sky-500 hover:bg-sky-100 hover:text-sky-700 dark:hover:bg-sky-500/20"
        aria-label={`清除筛选：${label}`}
      >
        ×
      </button>
    </span>
  );
}

/** 侧栏导航按钮；窄屏只显示图标，indent 用于收藏类子项缩进。 */
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

/**
 * 应用根组件。
 * 负责视图切换、搜索防抖、分页加载与任务状态轮询，并协调视频详情弹窗、演员详情抽屉和编辑弹窗。
 */
export default function App() {
  // 初始主题只读取一次，后续由 setTheme 触发 applyTheme 同步 DOM 与 localStorage。
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [view, setView] = useState<View>("videos");
  const [favoritesOpen, setFavoritesOpen] = useState(true);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [videoSort, setVideoSort] = useState<string>("updated_at");
  // 随机排序使用固定种子，翻页时顺序保持一致；点击“随机”会换一个种子。
  const [randomSeed, setRandomSeed] = useState(0);
  const [actressSort, setActressSort] = useState<string>("video_count");
  // 点击演员/标签/系列后的筛选条件，可叠加使用。
  const [filterActress, setFilterActress] = useState<{ id: number; name: string } | null>(null);
  const [filterTag, setFilterTag] = useState<string | null>(null);
  const [filterSeries, setFilterSeries] = useState<string | null>(null);
  // 只看待补全（资料不完整）或未刮削（未成功）的视频。
  const [incompleteOnly, setIncompleteOnly] = useState(false);
  const [unscrapedOnly, setUnscrapedOnly] = useState(false);
  const [videos, setVideos] = useState<Video[]>([]);
  const [actresses, setActresses] = useState<Actress[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  // banner 显示可关闭的持久错误，notice 是自动消失的轻提示。
  const [banner, setBanner] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // job 保存当前任务快照，activeJobId 非空时持续轮询；refreshKey 用于触发列表和详情重新加载。
  const [job, setJob] = useState<Job | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // 视频与演员详情各自只保留一个选中项，打开其中一个时会关闭另一个。
  const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null);
  const [videoDetail, setVideoDetail] = useState<VideoDetail | null>(null);
  const [editingVideo, setEditingVideo] = useState(false);
  // 多文件影片播放前先选文件；videoId/title 用于选择后发起播放。
  const [filePicker, setFilePicker] = useState<{
    videoId: number;
    title: string;
    files: VideoFile[];
  } | null>(null);
  // 删除确认弹窗：fileIds 非空表示从某个文件的删除按钮进入。
  const [deleteTarget, setDeleteTarget] = useState<{
    videoId: number;
    title: string;
    fileIds?: number[];
    defaultMode: "record" | "files";
  } | null>(null);
  const [selectedActressId, setSelectedActressId] = useState<number | null>(null);
  const [actressDetail, setActressDetail] = useState<ActressDetail | null>(null);
  // 海报墙拖拽合并：记录正在拖动的卡片和当前悬停的卡片。
  const [draggingVideoId, setDraggingVideoId] = useState<number | null>(null);
  const [dragOverVideoId, setDragOverVideoId] = useState<number | null>(null);
  const [editingActress, setEditingActress] = useState(false);
  const [playing, setPlaying] = useState(false);

  const isVideoView = view === "videos" || view === "favorites-videos";

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // 输入停顿 300ms 后才发起查询，避免每次按键都请求后端。
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  // 切换视图、搜索词、排序或筛选后回到第一页，防止沿用旧页码导致空列表。
  useEffect(() => {
    setPage(1);
  }, [
    view,
    debouncedQuery,
    videoSort,
    actressSort,
    filterActress,
    filterTag,
    filterSeries,
    incompleteOnly,
    unscrapedOnly,
  ]);

  // 按当前视图加载视频或演员列表；清理函数用于丢弃切换视图后返回的旧响应。
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
            seed: videoSort === "random" ? randomSeed : undefined,
            favorite: view === "favorites-videos" ? true : undefined,
            complete: incompleteOnly ? false : undefined,
            scraped: unscrapedOnly ? false : undefined,
            actressId: filterActress?.id,
            tag: filterTag ?? undefined,
            series: filterSeries ?? undefined,
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
  }, [
    view,
    page,
    debouncedQuery,
    videoSort,
    randomSeed,
    actressSort,
    refreshKey,
    isVideoView,
    filterActress,
    filterTag,
    filterSeries,
    incompleteOnly,
    unscrapedOnly,
  ]);

  // 任务轮询：700ms 一次以较平滑地更新进度；任务结束后递增 refreshKey，
  // 让列表、当前详情和设置面板感知到后台数据变化。
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

  // 打开详情时按 id 拉取完整数据；refreshKey 变化（保存、刮削完成等）会重新拉取。
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

  // 演员详情与视频详情一样，在选中项或全局刷新标记变化时重新加载。
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

  // 轻提示自动消失；连续新提示会重置计时器。
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  // 创建扫描任务后先构造一个排队中的 Job 快照，让进度条立即出现，
  // 随后的轮询会用后端真实状态覆盖它。
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

  // 各类刮削任务共用的任务跟踪入口：先乐观展示排队状态，再交给轮询同步。
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

  // 真正调用播放接口；fileId 用于多文件影片。
  async function startPlayback(id: number, fileId?: number) {
    try {
      const result = await api.playVideo(id, fileId);
      setNotice(`已用 ${result.player} 启动播放（pid ${result.pid}）`);
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  // 海报墙快捷播放：分组包含多个文件时先拉取详情并弹出文件选择。
  async function playVideo(id: number) {
    const item = videos.find((video) => video.id === id);
    if ((item?.file_count ?? 1) > 1) {
      try {
        const detail = await api.getVideo(id);
        setFilePicker({
          videoId: id,
          title: detail.metadata?.title || detail.video.filename,
          files: detail.files,
        });
      } catch (error) {
        setBanner(errorMessage(error));
      }
      return;
    }
    await startPlayback(id);
  }

  async function playSelected() {
    if (selectedVideoId === null) return;
    const files = videoDetail?.files ?? [];
    const present = files.filter((file) => file.present);
    // 详情已加载时直接复用文件列表，避免第二次请求。
    if (present.length > 1) {
      setFilePicker({
        videoId: selectedVideoId,
        title: videoDetail?.metadata?.title || videoDetail?.video.filename || "选择文件",
        files,
      });
      return;
    }
    setPlaying(true);
    try {
      await startPlayback(selectedVideoId, present[0]?.id);
    } finally {
      setPlaying(false);
    }
  }

  // 打开删除弹窗；从详情/海报墙进入默认删记录，从某个文件进入默认预选该文件。
  function removeVideo(id: number, fileIds?: number[]) {
    const item = videos.find((video) => video.id === id);
    const title =
      videoDetail?.video.id === id
        ? videoDetail.metadata?.title || videoDetail.video.filename
        : item?.metadata?.title || item?.filename || "视频";
    setDeleteTarget({
      videoId: id,
      title,
      fileIds,
      defaultMode: fileIds?.length ? "files" : "record",
    });
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

  // 收藏操作以后端返回值为准：成功后同步列表项与详情；
  // 在“收藏的视频”视图中取消收藏会让当前项消失，因此额外触发列表刷新。
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

  // 新建演员后立即刷新列表并打开详情，方便继续补充资料。
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

  // 演员收藏同样只在请求成功后更新本地缓存，并保持已打开的详情同步。
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

  // 从演员详情里的作品列表打开视频时，先关闭演员抽屉，避免两个详情叠加。
  function openVideo(id: number) {
    setSelectedActressId(null);
    setSelectedVideoId(id);
  }

  /** 随机按钮和排序下拉共用：选择随机时换一个种子，重新打乱顺序。 */
  function chooseVideoSort(value: string) {
    setVideoSort(value);
    if (value === "random") {
      setRandomSeed(newRandomSeed());
    }
  }

  function shuffleVideos() {
    setVideoSort("random");
    setRandomSeed(newRandomSeed());
    setPage(1);
  }

  // 点击卡片/详情里的标签时，关闭详情并在视频列表中叠加筛选条件。
  function applyVideoFilter(patch: {
    actress?: { id: number; name: string };
    tag?: string;
    series?: string;
  }) {
    if (!isVideoView) setView("videos");
    if (patch.actress !== undefined) setFilterActress(patch.actress);
    if (patch.tag !== undefined) setFilterTag(patch.tag);
    if (patch.series !== undefined) setFilterSeries(patch.series);
    setSelectedVideoId(null);
    setSelectedActressId(null);
    setPage(1);
  }

  function clearVideoFilters() {
    setFilterActress(null);
    setFilterTag(null);
    setFilterSeries(null);
    setIncompleteOnly(false);
    setUnscrapedOnly(false);
    setPage(1);
  }

  // 把文件移出剧集，恢复为独立视频；用于撤销误合并。
  async function detachVideoFile(videoId: number, fileId: number) {
    try {
      await api.detachVideoFiles(videoId, [fileId]);
      setRefreshKey((key) => key + 1);
      setNotice("已移出剧集，文件恢复为独立视频");
    } catch (error) {
      setBanner(errorMessage(error));
    }
  }

  // 把一个视频的文件合并到目标视频，两个海报变为一个剧集分组。
  async function mergeVideoGroups(targetId: number, sourceId: number) {
    if (targetId === sourceId) return;
    try {
      const detail = await api.mergeVideos(targetId, [sourceId]);
      setRefreshKey((key) => key + 1);
      if (selectedVideoId === sourceId) setSelectedVideoId(null);
      setNotice(`已合并为同一剧集：${detail.metadata?.title || detail.video.filename}`);
    } catch (error) {
      setBanner(errorMessage(error));
    } finally {
      setDraggingVideoId(null);
      setDragOverVideoId(null);
    }
  }

  // 即使没有数据也保留 1 页，页码显示不会出现 0/0。
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
      {/* 左侧固定导航：收藏分组可折叠，主题切换和设置固定在底部。 */}
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
        {/* 后台任务条与错误提示放在内容区上方，滚动时仍保持全局可见。 */}
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
              <p className="text-[11px] text-zinc-500">
                {total} 项{isVideoView ? " · 拖动海报可合并为剧集" : ""}
              </p>
            </div>
            <div className="relative min-w-48 flex-1">
              <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={isVideoView ? "搜索标题 / 文件名 / 番号 / 系列 / 演员" : "搜索演员姓名"}
                className="w-full rounded-lg border border-zinc-200 bg-white py-2 pl-9 pr-3 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-600"
              />
            </div>
            <select
              value={sortValue}
              onChange={(event) =>
                isVideoView
                  ? chooseVideoSort(event.target.value)
                  : setActressSort(event.target.value)
              }
              className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-600 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-300"
            >
              {sortOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            {isVideoView && (
              <button
                type="button"
                onClick={() => setIncompleteOnly((value) => !value)}
                title="只显示资料不完整、待补全的视频"
                className={`rounded-lg border px-3 py-2 text-sm font-medium transition ${
                  incompleteOnly
                    ? "border-amber-300 bg-amber-100 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/15 dark:text-amber-300"
                    : "border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-white/5"
                }`}
              >
                待补全
              </button>
            )}
            {isVideoView && (
              <button
                type="button"
                onClick={() => setUnscrapedOnly((value) => !value)}
                title="只显示尚未刮削成功的视频（no_match / failed / 未尝试）"
                className={`rounded-lg border px-3 py-2 text-sm font-medium transition ${
                  unscrapedOnly
                    ? "border-rose-300 bg-rose-100 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/15 dark:text-rose-300"
                    : "border-zinc-200 bg-white text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-white/5"
                }`}
              >
                未刮削
              </button>
            )}
            {isVideoView ? (
              <button
                type="button"
                onClick={shuffleVideos}
                disabled={total === 0}
                className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
                  videoSort === "random"
                    ? "bg-sky-500 text-white hover:bg-sky-400"
                    : "border border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-100 dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-white/5"
                }`}
                title="随机打乱海报墙顺序"
              >
                <ShuffleIcon className="h-4 w-4" />
                随机
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
          {/* 当前筛选条件：演员/标签/系列可叠加，随时单独清除或全部清除。 */}
          {isVideoView && (
            filterActress || filterTag || filterSeries || incompleteOnly || unscrapedOnly
          ) && (
            <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-sky-200 bg-sky-50/60 px-3 py-2 text-xs dark:border-sky-500/20 dark:bg-sky-500/[0.06]">
              <span className="text-zinc-500">筛选条件</span>
              {filterActress && (
                <FilterChip
                  label={`演员：${filterActress.name}`}
                  onClear={() => setFilterActress(null)}
                />
              )}
              {filterTag && (
                <FilterChip label={`标签：${filterTag}`} onClear={() => setFilterTag(null)} />
              )}
              {filterSeries && (
                <FilterChip label={`系列：${filterSeries}`} onClear={() => setFilterSeries(null)} />
              )}
              {incompleteOnly && (
                <FilterChip
                  label="只看待补全"
                  onClear={() => setIncompleteOnly(false)}
                />
              )}
              {unscrapedOnly && (
                <FilterChip
                  label="只看未刮削"
                  onClear={() => setUnscrapedOnly(false)}
                />
              )}
              <button
                type="button"
                onClick={clearVideoFilters}
                className="ml-auto text-[11px] text-zinc-500 underline-offset-2 hover:text-zinc-800 hover:underline dark:hover:text-zinc-200"
              >
                清除全部
              </button>
            </div>
          )}

          {/* 仅首次加载或切换后列表为空时显示骨架屏，已有数据时刷新不闪烁。 */}
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
                    : incompleteOnly
                      ? "没有待补全的视频"
                      : unscrapedOnly
                        ? "没有未刮削的视频"
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
                    onFilterActress={(id, name) => applyVideoFilter({ actress: { id, name } })}
                    onFilterTag={(tag) => applyVideoFilter({ tag })}
                    onFilterSeries={(series) => applyVideoFilter({ series })}
                    isDragging={draggingVideoId === video.id}
                    isDropTarget={
                      dragOverVideoId === video.id && draggingVideoId !== video.id
                    }
                    onDragStartCard={() => {
                      setDraggingVideoId(video.id);
                      setDragOverVideoId(null);
                    }}
                    onDragEndCard={() => {
                      setDraggingVideoId(null);
                      setDragOverVideoId(null);
                    }}
                    onDragOverCard={() => setDragOverVideoId(video.id)}
                    onDragLeaveCard={() =>
                      setDragOverVideoId((current) =>
                        current === video.id ? null : current,
                      )
                    }
                    onDropCard={(sourceId) => void mergeVideoGroups(video.id, sourceId)}
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

      {/* 视频详情弹窗、演员详情抽屉、编辑弹窗与设置面板都由选中状态控制挂载，关闭即卸载以复位内部状态。 */}
      {selectedVideoId !== null && (
        <VideoDetailModal
          detail={videoDetail}
          onClose={() => setSelectedVideoId(null)}
          onPlay={() => void playSelected()}
          onDelete={() => void removeVideo(selectedVideoId)}
          onEdit={() => setEditingVideo(true)}
          onScrape={() => void startVideoScrape(selectedVideoId)}
          onFavorite={() =>
            void toggleVideoFavorite(selectedVideoId, !(videoDetail?.video.favorite ?? false))
          }
          onFilterActress={(id, name) => applyVideoFilter({ actress: { id, name } })}
          onFilterTag={(tag) => applyVideoFilter({ tag })}
          onFilterSeries={(series) => applyVideoFilter({ series })}
          onDeleteFile={(fileId) => removeVideo(selectedVideoId, [fileId])}
          onDetachFile={(fileId) => void detachVideoFile(selectedVideoId, fileId)}
          playing={playing}
        />
      )}

      {/* 多文件影片的文件选择；选择后立即关闭并播放。 */}
      {filePicker && (
        <VideoFilePicker
          title={filePicker.title}
          files={filePicker.files}
          onClose={() => setFilePicker(null)}
          onSelect={(fileId) => {
            const current = filePicker;
            setFilePicker(null);
            void startPlayback(current.videoId, fileId);
          }}
        />
      )}

      {/* 删除确认：支持只删记录或彻底删除所选文件。 */}
      {deleteTarget && (
        <DeleteVideoModal
          videoId={deleteTarget.videoId}
          title={deleteTarget.title}
          initialFileIds={deleteTarget.fileIds}
          defaultMode={deleteTarget.defaultMode}
          onClose={() => setDeleteTarget(null)}
          onDeleted={(outcome) => {
            setDeleteTarget(null);
            setRefreshKey((key) => key + 1);
            if (outcome.failed.length > 0) {
              setBanner(
                `有 ${outcome.failed.length} 个文件删除失败：${outcome.failed
                  .map((file) => `${file.filename}（${file.message}）`)
                  .join("；")}`,
              );
            }
            if (outcome.recordDeleted) {
              setSelectedVideoId(null);
              setNotice(
                outcome.deletedFiles > 0
                  ? `已删除 ${outcome.deletedFiles} 个文件并移除记录`
                  : "视频记录已删除",
              );
            } else if (outcome.deletedFiles > 0) {
              setNotice(`已删除 ${outcome.deletedFiles} 个文件，影片记录保留`);
            } else {
              setNotice("没有文件被删除");
            }
          }}
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
          onMerged={() => {
            setEditingVideo(false);
            setSelectedVideoId(null);
            setRefreshKey((key) => key + 1);
            setNotice("已合并为同一剧集");
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

/** 列表为空时的占位视图，具体文案由调用方根据搜索/收藏状态决定。 */
function Empty({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-300 px-6 py-24 text-center dark:border-white/10">
      {icon}
      <p className="mt-4 text-sm text-zinc-500">{text}</p>
    </div>
  );
}
