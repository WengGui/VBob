/**
 * 主题读写工具。
 * 主题以根节点 .dark 类驱动 Tailwind 暗色变体，选择结果持久化到 localStorage。
 */
export type Theme = "light" | "dark";

const STORAGE_KEY = "vbob-theme";

/** 读取初始主题：URL 参数 > 本地存储 > 系统偏好，便于用 ?theme=dark 强制预览。 */
export function readTheme(): Theme {
  const forced = new URLSearchParams(window.location.search).get("theme");
  if (forced === "light" || forced === "dark") return forced;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // localStorage may be unavailable
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** 应用主题并持久化；存储不可用时（隐私模式等）仍只更新 DOM。 */
export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // ignore storage failures
  }
}
