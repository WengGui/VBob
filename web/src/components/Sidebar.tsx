/**
 * 左侧导航栏：视频（可折叠媒体分类）、演员、收藏分组，底部固定主题与设置。
 * 组件只负责展示和上报点击，视图状态仍由 App 管理。
 */
import { CATEGORY_LABELS } from "../api";
import type { Theme } from "../theme";
import type { View } from "../view";
import {
  FilmIcon,
  HeartIcon,
  MoonIcon,
  SettingsIcon,
  SunIcon,
  UserIcon,
} from "./Icons";
import { NavButton } from "./NavButton";

export function Sidebar({
  view,
  videoCategory,
  categoryCounts,
  videosOpen,
  favoritesOpen,
  theme,
  settingsOpen,
  onSelectView,
  onSelectCategory,
  onToggleVideos,
  onToggleFavorites,
  onToggleTheme,
  onOpenSettings,
}: {
  view: View;
  /** 当前视频分类；all 表示全部。 */
  videoCategory: string;
  categoryCounts: Record<string, number>;
  videosOpen: boolean;
  favoritesOpen: boolean;
  theme: Theme;
  settingsOpen: boolean;
  onSelectView: (view: View) => void;
  onSelectCategory: (category: string) => void;
  onToggleVideos: () => void;
  onToggleFavorites: () => void;
  onToggleTheme: () => void;
  onOpenSettings: () => void;
}) {
  return (
    <aside className="sticky top-0 flex h-screen w-16 shrink-0 flex-col border-r border-zinc-200 bg-white px-2 py-4 lg:w-60 lg:px-3 dark:border-white/10 dark:bg-zinc-900/70">
      <div className="flex items-center gap-2 px-1.5 py-1">
        <img
          src="/icon-192.png"
          alt="VBob"
          className="h-9 w-9 shrink-0 rounded-xl shadow-md shadow-sky-500/20"
        />
        <div className="hidden min-w-0 lg:block">
          <div className="truncate text-sm font-semibold tracking-wide">VBob</div>
          <div className="text-[10px] text-zinc-500">本地视频库</div>
        </div>
      </div>

      <nav className="mt-6 space-y-1">
        <NavButton
          icon={<FilmIcon className="h-4 w-4" />}
          label="视频"
          active={view === "videos" && videoCategory === "all"}
          count={categoryCounts.all}
          expanded={videosOpen}
          onClick={onToggleVideos}
        />
        {/* 媒体分类折叠在「视频」下，与目录/源的类型一致。 */}
        {videosOpen && (
          <div className="space-y-0.5">
            {CATEGORY_LABELS.map((item) => (
              <NavButton
                key={item.value}
                icon={<span className="h-1.5 w-1.5 rounded-full bg-current opacity-50" />}
                label={item.label}
                active={view === "videos" && videoCategory === item.value}
                count={categoryCounts[item.value]}
                indent
                onClick={() => onSelectCategory(item.value)}
              />
            ))}
          </div>
        )}
        <NavButton
          icon={<UserIcon className="h-4 w-4" />}
          label="演员"
          active={view === "actresses"}
          onClick={() => onSelectView("actresses")}
        />
        <NavButton
          icon={<HeartIcon className="h-4 w-4" />}
          label="收藏"
          active={view.startsWith("favorites")}
          expanded={favoritesOpen}
          onClick={onToggleFavorites}
        />
        {favoritesOpen && (
          <div className="space-y-1">
            <NavButton
              icon={<FilmIcon className="h-3.5 w-3.5" />}
              label="收藏的视频"
              active={view === "favorites-videos"}
              onClick={() => onSelectView("favorites-videos")}
              indent
            />
            <NavButton
              icon={<UserIcon className="h-3.5 w-3.5" />}
              label="收藏的演员"
              active={view === "favorites-actresses"}
              onClick={() => onSelectView("favorites-actresses")}
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
          onClick={onToggleTheme}
        />
        <NavButton
          icon={<SettingsIcon className="h-4 w-4" />}
          label="设置"
          active={settingsOpen}
          onClick={onOpenSettings}
        />
      </div>
    </aside>
  );
}
