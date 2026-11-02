/**
 * 展示层格式化工具。
 * 统一处理视频/演员字段的取值优先级、日期与容量显示，供各类卡片和详情复用。
 */
import type { Video } from "./api";

/** 把任意异常转换为可显示文本；ApiError 会直接使用后端返回的 message。 */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** 番号优先使用元数据（用户可修正），缺失时回退到文件名提取结果。 */
export function codeOf(video: Video): string {
  if (video.metadata?.code) return video.metadata.code;
  const feature = video.features.jav_code;
  return typeof feature === "string" ? feature : "";
}

/** 标题优先使用刮削结果，未刮削时退回特征或去掉扩展名的文件名。 */
export function titleOf(video: Video): string {
  const feature = video.features.title;
  return (
    video.metadata?.title ||
    (typeof feature === "string" ? feature : "") ||
    video.filename.replace(/\.[^.]+$/, "")
  );
}

/** 年份先看特征中的数值，缺失时使用元数据。 */
export function yearOf(video: Video): number | null {
  const feature = video.features.year;
  if (typeof feature === "number") return feature;
  return video.metadata?.year ?? null;
}

/** 文件实际时长优先，未探测到时使用元数据中的片长。 */
export function durationOf(video: Video): number | null {
  return video.duration_sec ?? video.metadata?.runtime_sec ?? null;
}

/** 按 1024 进制格式化文件大小；0 或空值显示破折号。 */
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

/** 秒数转为 m:ss 或 h:mm:ss；不足 1 小时时省略小时段。 */
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

/** 格式化为本地日期时间；无法解析时保留原始字符串，避免显示 Invalid Date。 */
export function formatDate(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

/** 只显示年月日，用于发行日期、生日等不需要具体时刻的字段。 */
export function formatDay(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

/** 用固定 id 生成稳定的占位渐变，保证无封面卡片每次渲染颜色一致。 */
export function gradient(seed: number): string {
  const hue = (seed * 47) % 360;
  return `linear-gradient(155deg, hsl(${hue} 34% 34%), hsl(${(hue + 55) % 360} 30% 16%))`;
}

/** 发行年份优先从完整发行日期的前四位解析，失败时回退到普通年份字段。 */
export function releaseYear(video: Video): number | null {
  const meta = video.metadata?.release_date;
  if (meta) {
    const parsed = Number(meta.slice(0, 4));
    if (!Number.isNaN(parsed)) return parsed;
  }
  return yearOf(video);
}

/** 将后端的编码状态转换为界面文案，未知值不显示角标。 */
export function censoredLabel(value: string | null | undefined): string | null {
  if (value === "censored") return "有码";
  if (value === "uncensored") return "无码";
  return null;
}
