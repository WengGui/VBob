import type { Video } from "./api";

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function codeOf(video: Video): string {
  const feature = video.features.jav_code;
  return typeof feature === "string" ? feature : video.metadata?.code ?? "";
}

export function titleOf(video: Video): string {
  const feature = video.features.title;
  return (
    video.metadata?.title ||
    (typeof feature === "string" ? feature : "") ||
    video.filename.replace(/\.[^.]+$/, "")
  );
}

export function yearOf(video: Video): number | null {
  const feature = video.features.year;
  if (typeof feature === "number") return feature;
  return video.metadata?.year ?? null;
}

export function durationOf(video: Video): number | null {
  return video.duration_sec ?? video.metadata?.runtime_sec ?? null;
}

export function formatSize(bytes: number | null): string {
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

export function formatDuration(seconds: number | null): string | null {
  if (!seconds) return null;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

export function formatDate(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function formatDay(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

export function gradient(seed: number): string {
  const hue = (seed * 47) % 360;
  return `linear-gradient(155deg, hsl(${hue} 34% 34%), hsl(${(hue + 55) % 360} 30% 16%))`;
}

export function releaseYear(video: Video): number | null {
  const meta = video.metadata?.release_date;
  if (meta) {
    const parsed = Number(meta.slice(0, 4));
    if (!Number.isNaN(parsed)) return parsed;
  }
  return yearOf(video);
}

export interface TagChip {
  label: string;
  tone: "violet" | "orange" | "neutral";
}

export function chipsOf(video: Video): TagChip[] {
  const metadata = video.metadata;
  const chips: TagChip[] = [];
  const actresses = video.actresses?.length
    ? video.actresses.map((actress) => actress.name)
    : metadata?.actresses ?? [];
  for (const actress of actresses) {
    chips.push({ label: actress, tone: "violet" });
  }
  for (const tag of [...(metadata?.genres ?? []), ...(metadata?.tags ?? [])]) {
    chips.push({ label: tag, tone: "orange" });
  }
  if (chips.length === 0) {
    chips.push({
      label: metadata?.is_complete ? "已刮削" : "未刮削",
      tone: "neutral",
    });
  }
  return chips.slice(0, 8);
}

export function censoredLabel(value: string | null | undefined): string | null {
  if (value === "censored") return "有码";
  if (value === "uncensored") return "无码";
  return null;
}
