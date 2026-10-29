import { useCallback, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api, type PlayerInfo, type ScanRoot, type Source } from "../api";
import { errorMessage, formatDate } from "../format";
import type { Theme } from "../theme";
import {
  DatabaseIcon,
  FolderIcon,
  MoonIcon,
  PlusIcon,
  ScanIcon,
  SunIcon,
  TrashIcon,
} from "./Icons";
import { SourceEditor } from "./SourceEditor";

function Section({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm dark:border-white/10 dark:bg-zinc-900/70">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-100 px-5 py-4 dark:border-white/5">
        <div>
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{title}</h2>
          <p className="mt-0.5 text-xs text-zinc-500">{description}</p>
        </div>
        {action}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

function sourceType(source: Source): string {
  return source.config.type === "query" ? "query" : "feature";
}

function sourceSummary(source: Source): string {
  if (sourceType(source) === "feature") {
    const feature = source.config.feature;
    return `特征 ${typeof feature === "string" && feature ? feature : "—"}`;
  }
  return "按标题搜索";
}

function sourceUrl(source: Source): string {
  const request = source.config.request;
  if (request && typeof request === "object") {
    const url = (request as Record<string, unknown>).url;
    if (typeof url === "string") return url;
  }
  return "";
}

export function SettingsPage({
  theme,
  onThemeChange,
  onStartScan,
  scanning,
  refreshKey,
}: {
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  onStartScan: (rootId?: number) => void;
  scanning: boolean;
  refreshKey: number;
}) {
  const [roots, setRoots] = useState<ScanRoot[]>([]);
  const [players, setPlayers] = useState<PlayerInfo[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [newRoot, setNewRoot] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ source: Source | null } | null>(null);

  const loadRoots = useCallback(async () => {
    try {
      const data = await api.listRoots();
      setRoots(data.items);
    } catch (loadError) {
      setError(errorMessage(loadError));
    }
  }, []);

  const loadSources = useCallback(async () => {
    try {
      const data = await api.listSources();
      setSources(data.items);
    } catch (loadError) {
      setError(errorMessage(loadError));
    }
  }, []);

  const refreshPlayers = useCallback(async () => {
    try {
      const data = await api.listPlayers();
      setPlayers(data.players);
    } catch (loadError) {
      setError(errorMessage(loadError));
    }
  }, []);

  useEffect(() => {
    void loadRoots();
    void loadSources();
    void refreshPlayers();
  }, [loadRoots, loadSources, refreshPlayers, refreshKey]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  async function addRoot(event: FormEvent) {
    event.preventDefault();
    const path = newRoot.trim();
    if (!path) return;
    try {
      await api.createRoot(path);
      setNewRoot("");
      await loadRoots();
      setNotice("扫描目录已添加");
    } catch (addError) {
      setError(errorMessage(addError));
    }
  }

  async function removeRoot(root: ScanRoot) {
    if (!window.confirm(`移除扫描目录？\n${root.path}\n\n不会删除文件。`)) return;
    try {
      await api.deleteRoot(root.id);
      await loadRoots();
      setNotice("扫描目录已移除");
    } catch (removeError) {
      setError(errorMessage(removeError));
    }
  }

  async function toggleSource(source: Source) {
    try {
      const updated = await api.updateSourceState(source.id, { enabled: !source.enabled });
      setSources((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (toggleError) {
      setError(errorMessage(toggleError));
    }
  }

  async function removeSource(source: Source) {
    if (!window.confirm(`删除刮削源「${source.name}」？`)) return;
    try {
      await api.deleteSource(source.id);
      await loadSources();
      setNotice("刮削源已删除");
    } catch (removeError) {
      setError(errorMessage(removeError));
    }
  }

  async function handleSourceSaved() {
    setEditor(null);
    await loadSources();
    setNotice("源配置已保存");
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 lg:px-10">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-white">设置</h1>
        <p className="mt-1 text-sm text-zinc-500">
          管理刮削源、扫描目录、播放器与界面主题。
        </p>
      </header>

      {error && (
        <div className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="shrink-0 text-xs underline-offset-2 hover:underline"
          >
            关闭
          </button>
        </div>
      )}
      {notice && (
        <div className="mb-4 rounded-xl border border-sky-200 bg-sky-50 px-4 py-2.5 text-sm text-sky-700 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300">
          {notice}
        </div>
      )}

      <div className="space-y-5">
        <Section
          title="刮削源"
          description="配置番号源与通用搜索源；feature 类型优先，query 类型用于降级。"
          action={
            <button
              type="button"
              onClick={() => setEditor({ source: null })}
              className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-sky-400"
            >
              <PlusIcon className="h-3.5 w-3.5" />
              新增源
            </button>
          }
        >
          {sources.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-200 px-6 py-12 text-center dark:border-white/10">
              <DatabaseIcon className="h-8 w-8 text-zinc-300 dark:text-zinc-600" />
              <p className="mt-3 text-sm text-zinc-500">还没有配置任何刮削源</p>
              <button
                type="button"
                onClick={() => setEditor({ source: null })}
                className="mt-3 text-xs font-medium text-sky-600 hover:underline dark:text-sky-400"
              >
                使用模板新建第一个源
              </button>
            </div>
          ) : (
            <ul className="divide-y divide-zinc-100 dark:divide-white/5">
              {sources.map((source) => (
                <li key={source.id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                        {source.name}
                      </span>
                      <span className="rounded border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-700 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300">
                        {sourceType(source) === "feature" ? "番号源" : "搜索源"}
                      </span>
                      {source.builtin && (
                        <span className="rounded border border-zinc-200 bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400">
                          内置
                        </span>
                      )}
                      {!source.enabled && (
                        <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
                          已禁用
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500">
                      <span>{sourceSummary(source)}</span>
                      <span>优先级 {source.priority}</span>
                      {sourceUrl(source) && (
                        <span className="max-w-full truncate font-mono" title={sourceUrl(source)}>
                          {sourceUrl(source)}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => void toggleSource(source)}
                      aria-label={source.enabled ? "禁用源" : "启用源"}
                      title={source.enabled ? "禁用源" : "启用源"}
                      className={`relative h-5 w-9 rounded-full transition ${
                        source.enabled ? "bg-sky-500" : "bg-zinc-300 dark:bg-zinc-700"
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
                          source.enabled ? "left-[18px]" : "left-0.5"
                        }`}
                      />
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditor({ source })}
                      disabled={source.builtin}
                      className="rounded-md border border-zinc-200 px-2 py-1 text-[11px] text-zinc-600 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-30 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      onClick={() => void removeSource(source)}
                      disabled={source.builtin}
                      aria-label="删除源"
                      title="删除源"
                      className="rounded-md p-1.5 text-zinc-400 transition hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-30 dark:hover:bg-red-500/10 dark:hover:text-red-400"
                    >
                      <TrashIcon className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section
          title="扫描目录"
          description="添加存放视频的目录，扫描会建立文件索引并标记缺失文件。"
          action={
            <button
              type="button"
              onClick={() => onStartScan()}
              disabled={scanning || roots.length === 0}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-1.5 text-xs text-zinc-600 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
            >
              <ScanIcon className="h-3.5 w-3.5" />
              扫描全部
            </button>
          }
        >
          {roots.length === 0 ? (
            <p className="py-4 text-center text-sm text-zinc-500">还没有扫描目录</p>
          ) : (
            <ul className="divide-y divide-zinc-100 dark:divide-white/5">
              {roots.map((root) => (
                <li key={root.id} className="flex items-center gap-3 py-3 first:pt-0">
                  <FolderIcon className="h-5 w-5 shrink-0 text-zinc-400" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-zinc-700 dark:text-zinc-200" title={root.path}>
                      {root.path}
                    </div>
                    <div className="text-[11px] text-zinc-500">
                      {root.last_scan_at ? `上次扫描 ${formatDate(root.last_scan_at)}` : "尚未扫描"}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => onStartScan(root.id)}
                    disabled={scanning}
                    className="rounded-md border border-zinc-200 px-2 py-1 text-[11px] text-zinc-600 transition hover:bg-zinc-100 disabled:opacity-30 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
                  >
                    扫描
                  </button>
                  <button
                    type="button"
                    onClick={() => void removeRoot(root)}
                    aria-label="移除目录"
                    title="移除目录"
                    className="rounded-md p-1.5 text-zinc-400 transition hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10 dark:hover:text-red-400"
                  >
                    <TrashIcon className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={(event) => void addRoot(event)} className="mt-3 flex gap-2">
            <input
              value={newRoot}
              onChange={(event) => setNewRoot(event.target.value)}
              placeholder="D:\Media 或 /media/videos"
              className="min-w-0 flex-1 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-950 dark:text-zinc-200 dark:placeholder:text-zinc-600"
            />
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-2 text-sm text-zinc-600 transition hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
            >
              <PlusIcon className="h-4 w-4" />
              添加
            </button>
          </form>
        </Section>

        <Section
          title="播放器"
          description="播放由后端直接调起本机播放器；优先使用设置中的播放器路径。"
          action={
            <button
              type="button"
              onClick={() => void refreshPlayers()}
              className="rounded-lg border border-zinc-200 px-3 py-1.5 text-xs text-zinc-600 transition hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
            >
              重新检测
            </button>
          }
        >
          {players.length === 0 ? (
            <p className="py-3 text-sm text-zinc-500">
              未检测到播放器。安装 mpv / VLC / PotPlayer 后点击“重新检测”。
            </p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2">
              {players.map((player) => (
                <li
                  key={player.path}
                  className="rounded-xl border border-zinc-200 px-3 py-2 dark:border-white/10"
                >
                  <div className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                    {player.name}
                  </div>
                  <div className="truncate text-[11px] text-zinc-500" title={player.path}>
                    {player.path}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="外观" description="选择界面主题，设置会保存在本地浏览器。">
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                ["light", "浅色", SunIcon, "白色背景，适合日间使用"],
                ["dark", "深色", MoonIcon, "深色背景，适合夜间使用"],
              ] as const
            ).map(([value, label, Icon, tip]) => (
              <button
                key={value}
                type="button"
                onClick={() => onThemeChange(value)}
                className={`flex items-center gap-3 rounded-xl border p-3 text-left transition ${
                  theme === value
                    ? "border-sky-400 bg-sky-50 ring-1 ring-sky-400 dark:border-sky-400/60 dark:bg-sky-500/10"
                    : "border-zinc-200 hover:bg-zinc-50 dark:border-white/10 dark:hover:bg-white/5"
                }`}
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600 dark:bg-white/5 dark:text-zinc-300">
                  <Icon className="h-5 w-5" />
                </span>
                <span>
                  <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-100">
                    {label}
                  </span>
                  <span className="block text-[11px] text-zinc-500">{tip}</span>
                </span>
              </button>
            ))}
          </div>
        </Section>
      </div>

      {editor && (
        <SourceEditor
          source={editor.source}
          onClose={() => setEditor(null)}
          onSaved={() => void handleSourceSaved()}
        />
      )}
    </div>
  );
}
