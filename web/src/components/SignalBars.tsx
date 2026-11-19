/**
 * 手机信号式的 5 格信号条。
 * 由低到高的 5 根竖线按等级亮起，用来表示刮削源到站点的网络质量；
 * level 为 null 表示尚未检测，全部灰显。
 */
const BAR_HEIGHTS = [5, 8, 11, 14, 17];
const BAR_WIDTH = 3;

/** 等级越高颜色越“健康”：4-5 格翠绿、3 格天蓝、2 格琥珀、1 格橙、0 格红。 */
function levelColor(level: number): string {
  if (level >= 4) return "bg-emerald-500";
  if (level === 3) return "bg-sky-500";
  if (level === 2) return "bg-amber-500";
  if (level === 1) return "bg-orange-500";
  return "bg-red-500";
}

export function SignalBars({
  level,
  busy = false,
  className = "",
}: {
  /** 0-5 的信号格数；null 表示从未检测。 */
  level: number | null;
  /** 检测中：整体脉冲，不展示旧的亮暗状态。 */
  busy?: boolean;
  className?: string;
}) {
  const lit = Math.max(0, Math.min(5, level ?? 0));
  const color = levelColor(lit);
  return (
    <span
      className={`inline-flex items-end gap-[2px] ${className}`}
      role="img"
      aria-label={level === null ? "未检测网络连通性" : `网络信号 ${lit}/5 格`}
    >
      {BAR_HEIGHTS.map((height, index) => (
        <span
          key={height}
          style={{ height, width: BAR_WIDTH }}
          className={`rounded-[1px] transition-colors ${
            busy
              ? "animate-pulse bg-sky-400/60"
              : index < lit
                ? color
                : "bg-zinc-300 dark:bg-zinc-700"
          }`}
        />
      ))}
    </span>
  );
}
