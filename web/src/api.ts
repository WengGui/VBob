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
  video: Omit<Video, "metadata">;
  metadata: FullMetadata | null;
}

export interface ScanRoot {
  id: number;
  path: string;
  path_key: string;
  enabled: boolean;
  last_scan_at: string | null;
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
  const response = await fetch(url, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
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
    present?: boolean;
    sort?: string;
  }): Promise<{ items: Video[]; total: number; page: number; page_size: number }> {
    const search = new URLSearchParams();
    search.set("page", String(params.page ?? 1));
    search.set("page_size", String(params.pageSize ?? 60));
    if (params.q) search.set("q", params.q);
    if (params.present !== undefined) search.set("present", String(params.present));
    if (params.sort) search.set("sort", params.sort);
    return request(`/api/videos?${search.toString()}`);
  },

  getVideo(id: number): Promise<VideoDetail> {
    return request(`/api/videos/${id}`);
  },

  deleteVideo(id: number): Promise<void> {
    return request(`/api/videos/${id}`, { method: "DELETE" });
  },

  playVideo(id: number): Promise<{ ok: boolean; player: string; pid: number }> {
    return request(`/api/videos/${id}/play`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  listPlayers(): Promise<{ players: PlayerInfo[] }> {
    return request("/api/players");
  },

  listRoots(): Promise<{ items: ScanRoot[] }> {
    return request("/api/scan-roots");
  },

  createRoot(path: string): Promise<ScanRoot> {
    return request("/api/scan-roots", {
      method: "POST",
      body: JSON.stringify({ path }),
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
