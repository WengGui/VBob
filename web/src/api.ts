export interface ActressBrief {
  id: number;
  name: string;
}

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
}

export interface FullMetadata extends MetadataSummary {
  id: number;
  video_id: number;
  overview: string | null;
  series: string | null;
  director: string | null;
  matched_by: string | null;
  manual_fields: string[];
  version: number;
}

export interface VideoDetail {
  video: Omit<Video, "metadata" | "actresses">;
  metadata: FullMetadata | null;
  actresses: ActressBrief[];
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
  scraped_count?: number;
  last_scan_at: string | null;
  last_scan_started_at: string | null;
  last_scan_finished_at: string | null;
  last_scan_status: string | null;
  last_scan_duration_ms: number | null;
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

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

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
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

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
  }): Promise<{ items: Video[]; total: number; page: number; page_size: number }> {
    const search = new URLSearchParams();
    search.set("page", String(params.page ?? 1));
    search.set("page_size", String(params.pageSize ?? 60));
    if (params.q) search.set("q", params.q);
    if (params.sort) search.set("sort", params.sort);
    if (params.complete !== undefined) search.set("complete", String(params.complete));
    if (params.favorite !== undefined) search.set("favorite", String(params.favorite));
    if (params.actressId !== undefined) search.set("actress_id", String(params.actressId));
    if (params.tag) search.set("tag", params.tag);
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

  playVideo(id: number): Promise<{ ok: boolean; player: string; pid: number }> {
    return request(`/api/videos/${id}/play`, {
      method: "POST",
      body: JSON.stringify({}),
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
