/**
 * 后端 API 的类型定义与统一请求封装。
 * 所有接口都经过 request()，由它补充请求头并把非 2xx 响应转换为 ApiError；
 * 各业务方法只负责前端参数到后端查询键/请求体的映射。
 */
export interface ActressBrief {
  id: number;
  name: string;
}

/** 列表和详情共用的元数据摘要，不包含仅在详情接口返回的字段。 */
export interface MetadataSummary {
  title: string | null;
  original_title: string | null;
  year: number | null;
  code: string | null;
  cover_url: string | null;
  cover_local: string | null;
  scrape_status: string | null;
  source_name: string | null;
  last_scraped_at: string | null;
  genres: string[];
  tags: string[];
  actresses: string[];
  studio: string | null;
  series: string | null;
  release_date: string | null;
  runtime_sec: number | null;
  censored: string | null;
  country: string | null;
  is_complete: boolean;
}

export interface Video {
  id: number;
  path: string;
  filename: string;
  size_bytes: number | null;
  mtime: number | null;
  duration_sec: number | null;
  screenshot: string | null;
  features: Record<string, unknown>;
  present: boolean;
  missing_since: string | null;
  scan_status: string;
  favorite: boolean;
  actresses: ActressBrief[];
  created_at: string;
  updated_at: string;
  metadata: MetadataSummary | null;
  /** 分组内仍存在的文件数；1 表示普通单文件影片。 */
  file_count?: number;
}

/** 同一部影片下的实际播放文件（A/B 分段、不同清晰度等）。 */
export interface VideoFile {
  id: number;
  path: string;
  filename: string;
  size_bytes: number | null;
  duration_sec: number | null;
  present: boolean;
  missing_since: string | null;
}

/** 详情接口返回的完整元数据，额外包含简介、手动字段和版本号。 */
export interface FullMetadata extends MetadataSummary {
  id: number;
  video_id: number;
  overview: string | null;
  director: string | null;
  matched_by: string | null;
  manual_fields: string[];
  version: number;
}

export interface VideoDetail {
  video: Omit<Video, "metadata" | "actresses">;
  metadata: FullMetadata | null;
  actresses: ActressBrief[];
  /** 按“存在优先、添加顺序”返回该影片的所有文件。 */
  files: VideoFile[];
}

/** 删除扫描目录的返回结果。 */
export interface DeleteScanRootResult {
  deleted_videos: number;
  deleted_files: number;
  failed_files: Array<{ filename: string; message: string }>;
}

/** 彻底删除文件的返回结果；部分失败时 failed_files 给出原因。 */
export interface DeleteVideoFilesResult {
  deleted_files: number;
  failed_files: Array<{ id: number; filename: string; message: string }>;
  remaining_files: number;
  record_deleted: boolean;
}

export interface Actress {
  id: number;
  name: string;
  name_key: string;
  aliases: string[];
  birth_date: string | null;
  nationality: string | null;
  cover_url: string | null;
  cover_local: string | null;
  profile_url: string | null;
  height_cm: number | null;
  bust_cm: number | null;
  waist_cm: number | null;
  hips_cm: number | null;
  cup: string | null;
  favorite: boolean;
  is_complete: boolean;
  source_name: string | null;
  manual_fields: string[];
  version: number;
  created_at: string;
  updated_at: string;
  video_count?: number;
}

// 演员作品概要来自联表查询，SQLite 的 0/1 可能直接透出，因此布尔字段兼容 number。
export interface ActressVideo {
  id: number;
  filename: string;
  path: string;
  present: number | boolean;
  favorite: number | boolean;
  updated_at: string;
  title: string | null;
  year: number | null;
  release_date: string | null;
  cover_local: string | null;
  is_complete: number | boolean;
}

export interface ActressDetail {
  actress: Actress;
  videos: ActressVideo[];
}

export interface ScanRoot {
  id: number;
  path: string;
  path_key: string;
  enabled: boolean;
  scan_interval_minutes: number;
  scanned_count?: number;
  /** 目录内的实际文件数（同一部影片可能有多个文件）。 */
  file_count?: number;
  scraped_count?: number;
  last_scan_at: string | null;
  last_scan_started_at: string | null;
  last_scan_finished_at: string | null;
  last_scan_status: string | null;
  last_scan_duration_ms: number | null;
  // 设置页直接读取目录内嵌的活动任务，避免为每个目录单独轮询任务接口。
  active_job: {
    id: string;
    type: string;
    status: string;
    done: number;
    total: number;
    message: string | null;
  } | null;
  created_at: string;
}

export interface Job {
  id: string;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  total: number;
  done: number;
  failed: number;
  payload: Record<string, unknown>;
  message: string | null;
  cancel_requested: boolean;
  root_id: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface PlayerInfo {
  name: string;
  path: string;
  source: string;
}

/** 设置中保存的播放器；args 为参数模板，支持 {path} / {seek}。 */
export interface PlayerConfig {
  name: string;
  path: string;
  args: string[];
}

/** 设置接口返回的完整结构，本模块只关心 playback.player。 */
export interface AppSettings {
  playback: { player: PlayerConfig | null };
  [key: string]: unknown;
}

export interface Source {
  id: number;
  name: string;
  enabled: boolean;
  priority: number;
  version: number;
  builtin: boolean;
  config: Record<string, unknown>;
  last_test_at: string | null;
  created_at: string;
  updated_at: string;
}

/** 统一的后端错误类型，保留业务错误码和 HTTP 状态，供界面区分处理。 */
export class ApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

/**
 * 通用 JSON 请求封装。
 * 仅对非 FormData 请求自动设置 Content-Type；上传文件时交给浏览器生成 multipart 边界。
 * 错误响应优先读取后端约定的 { error: { message, code } }，解析失败则退回状态文本。
 */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const response = await fetch(url, {
    ...init,
    headers: {
      ...(init?.body && !isForm ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = response.statusText;
    let code = `http_${response.status}`;
    try {
      const body = await response.json();
      message = body?.error?.message ?? message;
      code = body?.error?.code ?? code;
    } catch {
      // ignore non-JSON errors
    }
    throw new ApiError(message, code, response.status);
  }
  // 删除等无内容接口返回 204，不能继续调用 response.json()。
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** 后端接口集合；组件通过这里发起请求，不直接拼 URL。 */
export const api = {
  listVideos(params: {
    page?: number;
    pageSize?: number;
    q?: string;
    sort?: string;
    complete?: boolean;
    favorite?: boolean;
    actressId?: number;
    tag?: string;
    series?: string;
    /** true 只看刮削成功，false 只看未成功（no_match/failed/未尝试）。 */
    scraped?: boolean;
    /** sort=random 时的随机种子；相同种子翻页顺序稳定。 */
    seed?: number;
  }): Promise<{ items: Video[]; total: number; page: number; page_size: number }> {
    // 前端使用 camelCase 参数，这里转换成后端约定的 snake_case 查询键。
    const search = new URLSearchParams();
    search.set("page", String(params.page ?? 1));
    search.set("page_size", String(params.pageSize ?? 60));
    if (params.q) search.set("q", params.q);
    if (params.sort) search.set("sort", params.sort);
    if (params.complete !== undefined) search.set("complete", String(params.complete));
    if (params.favorite !== undefined) search.set("favorite", String(params.favorite));
    if (params.actressId !== undefined) search.set("actress_id", String(params.actressId));
    if (params.tag) search.set("tag", params.tag);
    if (params.series) search.set("series", params.series);
    if (params.scraped !== undefined) search.set("scraped", String(params.scraped));
    if (params.seed !== undefined) search.set("seed", String(params.seed));
    return request(`/api/videos?${search.toString()}`);
  },

  getVideo(id: number): Promise<VideoDetail> {
    return request(`/api/videos/${id}`);
  },

  updateVideoMetadata(
    id: number,
    payload: Record<string, unknown>,
  ): Promise<VideoDetail> {
    return request(`/api/videos/${id}/metadata`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  setVideoFavorite(id: number, favorite: boolean): Promise<VideoDetail> {
    return request(`/api/videos/${id}/favorite`, {
      method: "PATCH",
      body: JSON.stringify({ favorite }),
    });
  },

  deleteVideo(id: number): Promise<void> {
    return request(`/api/videos/${id}`, { method: "DELETE" });
  },

  /** 把文件移出剧集，各自拆分为独立视频。 */
  detachVideoFiles(
    id: number,
    fileIds: number[],
  ): Promise<{ detached: number[]; video: VideoDetail }> {
    return request(`/api/videos/${id}/detach-files`, {
      method: "POST",
      body: JSON.stringify({ file_ids: fileIds }),
    });
  },

  /** 把源视频合并到目标视频，返回合并后的目标详情。 */
  mergeVideos(id: number, sourceIds: number[]): Promise<VideoDetail> {
    return request(`/api/videos/${id}/merge`, {
      method: "POST",
      body: JSON.stringify({ source_ids: sourceIds }),
    });
  },

  /** 彻底删除分组中的指定文件；全部删除后后端会同时移除记录。 */
  deleteVideoFiles(id: number, fileIds: number[]): Promise<DeleteVideoFilesResult> {
    return request(`/api/videos/${id}/delete-files`, {
      method: "POST",
      body: JSON.stringify({ file_ids: fileIds }),
    });
  },

  // 封面上传使用 FormData，request() 会跳过 JSON Content-Type 以保留 multipart 边界。
  uploadVideoCover(id: number, file: File): Promise<VideoDetail> {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/videos/${id}/cover`, { method: "POST", body: form });
  },

  setVideoCoverUrl(id: number, url: string): Promise<VideoDetail> {
    return request(`/api/videos/${id}/cover`, {
      method: "PUT",
      body: JSON.stringify({ url }),
    });
  },

  // 手动刮削默认 force=true 以允许重新抓取；overwrite_manual 默认关闭，
  // 避免自动结果覆盖用户在编辑弹窗中填写的字段。
  scrapeVideo(
    id: number,
    force = true,
    overwriteManual = false,
  ): Promise<{ job_id: string }> {
    return request(`/api/videos/${id}/scrape`, {
      method: "POST",
      body: JSON.stringify({ force, overwrite_manual: overwriteManual }),
    });
  },

  scrapeActress(id: number, force = true): Promise<{ job_id: string }> {
    return request(`/api/actresses/${id}/scrape`, {
      method: "POST",
      body: JSON.stringify({ force, overwrite_manual: false }),
    });
  },

  // 目录批量刮削默认只补缺失数据，避免整库重复抓取；手动触发单条时才强制刷新。
  scrapeRoot(rootId: number, force = false): Promise<{ job_id: string }> {
    return request("/api/scrapes", {
      method: "POST",
      body: JSON.stringify({ root_id: rootId, force }),
    });
  },

  getScrapeLogs(
    videoId: number,
    limit = 50,
  ): Promise<{ items: Array<Record<string, unknown>> }> {
    return request(`/api/videos/${videoId}/scrape-logs?limit=${limit}`);
  },

  playVideo(
    id: number,
    fileId?: number,
  ): Promise<{ ok: boolean; player: string; pid: number }> {
    return request(`/api/videos/${id}/play`, {
      method: "POST",
      body: JSON.stringify(fileId === undefined ? {} : { file_id: fileId }),
    });
  },

  listActresses(params: {
    page?: number;
    pageSize?: number;
    q?: string;
    complete?: boolean;
    favorite?: boolean;
    sort?: string;
  }): Promise<{ items: Actress[]; total: number; page: number; page_size: number }> {
    // 演员列表参数映射与视频列表一致，可选条件为空时不写入查询串。
    const search = new URLSearchParams();
    search.set("page", String(params.page ?? 1));
    search.set("page_size", String(params.pageSize ?? 60));
    if (params.q) search.set("q", params.q);
    if (params.complete !== undefined) search.set("complete", String(params.complete));
    if (params.favorite !== undefined) search.set("favorite", String(params.favorite));
    if (params.sort) search.set("sort", params.sort);
    return request(`/api/actresses?${search.toString()}`);
  },

  getActress(id: number): Promise<ActressDetail> {
    return request(`/api/actresses/${id}`);
  },

  createActress(name: string): Promise<Actress> {
    return request("/api/actresses", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  },

  updateActress(id: number, payload: Record<string, unknown>): Promise<Actress> {
    return request(`/api/actresses/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  deleteActress(id: number): Promise<void> {
    return request(`/api/actresses/${id}`, { method: "DELETE" });
  },

  setActressFavorite(id: number, favorite: boolean): Promise<Actress> {
    return request(`/api/actresses/${id}/favorite`, {
      method: "PATCH",
      body: JSON.stringify({ favorite }),
    });
  },

  uploadActressCover(id: number, file: File): Promise<Actress> {
    const form = new FormData();
    form.append("file", file);
    return request(`/api/actresses/${id}/cover`, { method: "POST", body: form });
  },

  setActressCoverUrl(id: number, url: string): Promise<Actress> {
    return request(`/api/actresses/${id}/cover`, {
      method: "PUT",
      body: JSON.stringify({ url }),
    });
  },

  listPlayers(): Promise<{ players: PlayerInfo[] }> {
    return request("/api/players");
  },

  /** 由后端弹出本机文件选择框；用户取消时 path 为 null。 */
  pickPlayer(): Promise<{ path: string | null; name: string | null }> {
    return request("/api/players/pick", { method: "POST" });
  },

  getSettings(): Promise<AppSettings> {
    return request("/api/settings");
  },

  updateSettings(patch: Record<string, unknown>): Promise<AppSettings> {
    return request("/api/settings", {
      method: "PUT",
      body: JSON.stringify(patch),
    });
  },

  listRoots(): Promise<{ items: ScanRoot[] }> {
    return request("/api/scan-roots");
  },

  createRoot(path: string, scanIntervalMinutes = 0): Promise<ScanRoot> {
    return request("/api/scan-roots", {
      method: "POST",
      body: JSON.stringify({ path, scan_interval_minutes: scanIntervalMinutes }),
    });
  },

  updateRoot(
    id: number,
    patch: { path?: string; scan_interval_minutes?: number; enabled?: boolean },
  ): Promise<ScanRoot> {
    return request(`/api/scan-roots/${id}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    });
  },

  deleteRoot(id: number): Promise<void> {
    return request(`/api/scan-roots/${id}`, { method: "DELETE" });
  },

  /** 删除目录及其影片数据；deleteFiles 为 true 时同时删除磁盘文件。 */
  deleteRootData(id: number, deleteFiles: boolean): Promise<DeleteScanRootResult> {
    return request(`/api/scan-roots/${id}/delete`, {
      method: "POST",
      body: JSON.stringify({ delete_files: deleteFiles }),
    });
  },

  // 不传 rootId 时后端会扫描所有已启用的目录。
  createScan(rootId?: number): Promise<{ job_id: string }> {
    return request("/api/scans", {
      method: "POST",
      body: JSON.stringify(rootId === undefined ? {} : { root_id: rootId }),
    });
  },

  getJob(id: string): Promise<Job> {
    return request(`/api/jobs/${id}`);
  },

  cancelJob(id: string): Promise<Job> {
    return request(`/api/jobs/${id}/cancel`, { method: "POST", body: "{}" });
  },

  listSources(): Promise<{ items: Source[] }> {
    return request("/api/sources");
  },

  /** 补齐被删除的默认源；同名源保持用户现有配置。 */
  restoreDefaultSources(): Promise<{ items: Source[] }> {
    return request("/api/sources/restore-defaults", { method: "POST" });
  },

  createSource(config: Record<string, unknown>): Promise<Source> {
    return request("/api/sources", {
      method: "POST",
      body: JSON.stringify(config),
    });
  },

  updateSource(id: number, config: Record<string, unknown>): Promise<Source> {
    return request(`/api/sources/${id}`, {
      method: "PUT",
      body: JSON.stringify(config),
    });
  },

  updateSourceState(
    id: number,
    patch: { enabled?: boolean; priority?: number },
  ): Promise<Source> {
    return request(`/api/sources/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  },

  deleteSource(id: number): Promise<void> {
    return request(`/api/sources/${id}`, { method: "DELETE" });
  },
};
