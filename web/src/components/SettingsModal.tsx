/**
 * 全局设置弹窗，包含目录、播放器和刮削源三个标签页。
 * 目录列表同时承担扫描进度展示：扫描期间提高刷新频率，平时也定时同步，
 * 以便看到定时扫描或其他页面触发的任务状态；源编辑交给嵌套的 SourceForm。
 */
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, type PlayerInfo, type ScanRoot, type Source } from "../api";
import { errorMessage, formatDate, formatDuration } from "../format";
import {
  CloseIcon,
  DatabaseIcon,
  FolderIcon,
  PlusIcon,
  ScanIcon,
  SettingsIcon,
  TrashIcon,
  UserIcon,
} from "./Icons";
import { PlayerSettingsPanel } from "./PlayerSettingsPanel";
import { RootDeleteModal } from "./RootDeleteModal";
import { RootSettingsModal } from "./RootSettingsModal";
import { SourceForm } from "./SourceForm";

type Tab = "directories" | "players" | "sources";

/** 将源配置中的 type 映射为设置页的中文标签，旧配置缺省视为番号源。 */
function typeLabel(source: Source): string {
  const type = source.config.type;
  if (type === "actress") return "演员源";
  if (type === "query") return "搜索源";
  return "番号源";
}

/**
 * 设置弹窗。
 * onChanged 用于在目录/源变更后让 App 刷新主列表；refreshKey 变化时重新拉取设置数据。
 */
export function SettingsModal({
  onClose,
  onStartScan,
  onScrape,
  onChanged,
  scanning,
  refreshKey,
}: {
  onClose: () => void;
  onStartScan: (rootId?: number) => void;
  onScrape: (rootId: number) => void;
  onChanged: () => void;
  scanning: boolean;
  refreshKey: number;
}) {
  const [tab, setTab] = useState<Tab>("directories");
  const [roots, setRoots] = useState<ScanRoot[]>([]);
  const [players, setPlayers] = useState<PlayerInfo[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [newRoot, setNewRoot] = useState("");
  const [newInterval, setNewInterval] = useState("0");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ source: Source | null } | null>(null);
  // 目录编辑弹窗：路径和自动扫描间隔在同一表单中修改。
  const [rootEditor, setRootEditor] = useState<ScanRoot | null>(null);
  // 目录删除弹窗：可选择只删数据或连同视频文件一起删除。
  const [deletingRoot, setDeletingRoot] = useState<ScanRoot | null>(null);

  const loadRoots = useCallback(async () => {
    try {
      setRoots((await api.listRoots()).items);
    } catch (loadError) {
      setError(errorMessage(loadError));
    }
  }, []);

  const loadSources = useCallback(async () => {
    try {
      setSources((await api.listSources()).items);
    } catch (loadError) {
      setError(errorMessage(loadError));
    }
  }, []);

  const loadPlayers = useCallback(async () => {
    try {
      setPlayers((await api.listPlayers()).players);
    } catch (loadError) {
      setError(errorMessage(loadError));
    }
  }, []);

  // 首次打开或外部数据变化（refreshKey）时并行加载三类设置数据。
  useEffect(() => {
    void loadRoots();
    void loadSources();
    void loadPlayers();
  }, [loadRoots, loadSources, loadPlayers, refreshKey]);

  // 扫描进行中每秒刷新目录，及时更新内嵌 active_job 的 done/total 进度。
  useEffect(() => {
    if (!scanning) return;
    const timer = window.setInterval(() => {
      void loadRoots();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [scanning, loadRoots]);

  // 即使本页没有发起任务，也低频同步目录（例如定时扫描或后台刮削的状态）。
  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadRoots();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadRoots]);

  // 设置页的操作反馈使用局部 notice，自动消失以免遮挡面板。
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  // 添加目录前去掉首尾空白；间隔输入非法或为空时按 0（关闭自动扫描）处理。
  async function addRoot(event: FormEvent) {
    event.preventDefault();
    const path = newRoot.trim();
    if (!path) return;
    try {
      await api.createRoot(path, Number(newInterval) || 0);
      setNewRoot("");
      setNewInterval("0");
      await loadRoots();
      setNotice("扫描目录已添加");
    } catch (addError) {
      setError(errorMessage(addError));
    }
  }

  // 删除目录交给 RootDeleteModal 确认；磁盘文件是否删除由用户在弹窗中选择。
  function removeRoot(root: ScanRoot) {
    setDeletingRoot(root);
  }

  // 启用状态由后端返回完整 Source 后替换列表项，避免本地构造对象丢失字段。
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

  // 恢复默认源只在缺失时插入，不会覆盖用户已经修改过的同名配置。
  async function restoreSources() {
    try {
      const data = await api.restoreDefaultSources();
      setSources(data.items);
      setNotice("默认刮削源已补齐");
    } catch (restoreError) {
      setError(errorMessage(restoreError));
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

  // 活动任务优先于上次扫描结果：有 active_job 时按任务类型显示“扫描中/刮削中”。
  function rootStatus(root: ScanRoot): string {
    if (root.active_job) {
      return root.active_job.type === "scan" ? "扫描中" : "刮削中";
    }
    if (root.last_scan_status === "running") return "扫描中";
    if (root.last_scan_status === "failed") return "上次扫描失败";
    return "空闲";
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-sm dark:bg-black/75"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="flex h-[86vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-white/10 dark:bg-zinc-950"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-100 px-6 py-4 dark:border-white/10">
          <div>
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-white">全局设置</h2>
            <p className="mt-0.5 text-[11px] text-zinc-500">
              目录、播放器与刮削源配置
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-1.5 text-xs text-zinc-500 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
          >
            <CloseIcon className="h-4 w-4" />
            关闭
          </button>
        </div>

        <div className="flex min-h-0 flex-1">
          <nav className="w-44 shrink-0 border-r border-zinc-100 bg-zinc-50/60 p-3 dark:border-white/5 dark:bg-white/[0.02]">
            {(
              [
                ["directories", "目录管理", FolderIcon],
                ["players", "播放器", SettingsIcon],
                ["sources", "刮削源", DatabaseIcon],
              ] as const
            ).map(([value, label, Icon]) => (
              <button
                key={value}
                type="button"
                onClick={() => setTab(value)}
                className={`mb-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition ${
                  tab === value
                    ? "bg-sky-50 font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-300"
                    : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            ))}
          </nav>

          <div className="min-w-0 flex-1 overflow-y-auto p-5">
            {(error || notice) && (
              <div
                className={`mb-4 rounded-xl border px-4 py-2 text-sm ${
                  error
                    ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300"
                    : "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <span>{error ?? notice}</span>
                  <button
                    type="button"
                    onClick={() => {
                      setError(null);
                      setNotice(null);
                    }}
                    className="shrink-0 text-xs underline-offset-2 hover:underline"
                  >
                    关闭
                  </button>
                </div>
              </div>
            )}

            {tab === "directories" && (
              <div>
                <div className="mb-4 flex items-center justify-between">
                  <p className="text-xs text-zinc-500">
                    添加本地视频目录；扫描会建立索引并统计完整度。
                  </p>
                  {/* 扫描全部会为每个目录分别发起任务。 */}
                  <button
                    type="button"
                    onClick={() => roots.forEach((root) => onStartScan(root.id))}
                    disabled={scanning || roots.length === 0}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-1.5 text-xs text-zinc-600 hover:bg-zinc-100 disabled:opacity-40 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
                  >
                    <ScanIcon className="h-3.5 w-3.5" />
                    扫描全部
                  </button>
                </div>

                <div className="space-y-3">
                  {roots.map((root) => (
                    <div
                      key={root.id}
                      className="rounded-xl border border-zinc-200 p-4 dark:border-white/10"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <FolderIcon className="h-4 w-4 shrink-0 text-zinc-400" />
                            <span className="truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
                              {root.path}
                            </span>
                          </div>
                          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
                            <span>已收录 {root.scanned_count ?? 0} 部</span>
                            <span>文件 {root.file_count ?? root.scanned_count ?? 0} 个</span>
                            <span>已刮削 {root.scraped_count ?? 0}</span>
                            <span>当前状态：{rootStatus(root)}</span>
                            {root.last_scan_started_at && (
                              <span>上次开始：{formatDate(root.last_scan_started_at)}</span>
                            )}
                            {root.last_scan_finished_at && (
                              <span>上次结束：{formatDate(root.last_scan_finished_at)}</span>
                            )}
                            {root.last_scan_duration_ms != null && (
                              <span>
                                耗时：
                                {root.last_scan_duration_ms < 1000
                                  ? "<1 秒"
                                  : formatDuration(Math.round(root.last_scan_duration_ms / 1000))}
                              </span>
                            )}
                            <span>自动扫描：{root.scan_interval_minutes ? `${root.scan_interval_minutes} 分钟` : "关闭"}</span>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          <button
                            type="button"
                            onClick={() => onStartScan(root.id)}
                            disabled={scanning}
                            className="rounded-md border border-zinc-200 px-2 py-1 text-[11px] text-zinc-600 hover:bg-zinc-100 disabled:opacity-30 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
                          >
                            手动扫描
                          </button>
                          <button
                            type="button"
                            onClick={() => onScrape(root.id)}
                            disabled={scanning || !!root.active_job}
                            className="rounded-md border border-sky-200 px-2 py-1 text-[11px] text-sky-600 hover:bg-sky-50 disabled:opacity-30 dark:border-sky-500/20 dark:text-sky-300 dark:hover:bg-sky-500/10"
                          >
                            批量刮削
                          </button>
                          <button
                            type="button"
                            onClick={() => setRootEditor(root)}
                            className="rounded-md border border-zinc-200 px-2 py-1 text-[11px] text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
                          >
                            编辑
                          </button>
                          <button
                            type="button"
                            onClick={() => void removeRoot(root)}
                            aria-label="删除目录"
                            className="rounded-md p-1.5 text-zinc-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
                          >
                            <TrashIcon className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                      {root.active_job && (
                        <div className="mt-3">
                          <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                            {/* 总数未知时保留一段固定长度，表示任务仍在准备/运行。 */}
                            <div
                              className="h-full rounded-full bg-sky-500 transition-all"
                              style={{
                                width:
                                  root.active_job.total > 0
                                    ? `${Math.round((root.active_job.done / root.active_job.total) * 100)}%`
                                    : "30%",
                              }}
                            />
                          </div>
                          <p className="mt-1 text-[11px] text-zinc-500">
                            {root.active_job.message}
                          </p>
                        </div>
                      )}
                    </div>
                  ))}
                  {roots.length === 0 && (
                    <p className="py-8 text-center text-sm text-zinc-500">还没有扫描目录</p>
                  )}
                </div>

                <form onSubmit={(event) => void addRoot(event)} className="mt-4 flex flex-wrap gap-2">
                  <input
                    value={newRoot}
                    onChange={(event) => setNewRoot(event.target.value)}
                    placeholder="D:\Media 或 /media/videos"
                    className="min-w-48 flex-1 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200"
                  />
                  <input
                    value={newInterval}
                    onChange={(event) => setNewInterval(event.target.value)}
                    title="自动扫描间隔（分钟）"
                    inputMode="numeric"
                    className="w-28 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200"
                  />
                  <button
                    type="submit"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-3 py-2 text-sm font-semibold text-white hover:bg-sky-400"
                  >
                    <PlusIcon className="h-4 w-4" />
                    添加目录
                  </button>
                </form>
                <p className="mt-1 text-[11px] text-zinc-500">
                  第二个输入框为自动扫描间隔（分钟，0=关闭）
                </p>
              </div>
            )}

            {tab === "players" && (
              <PlayerSettingsPanel
                players={players}
                onReloadPlayers={() => void loadPlayers()}
                onNotice={setNotice}
              />
            )}

            {tab === "sources" && (
              <div>
                <div className="mb-4 flex items-center justify-between">
                  <p className="text-xs text-zinc-500">
                    支持视频源与演员源；优先级越小越先执行。
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void restoreSources()}
                      className="rounded-md border border-zinc-200 px-2 py-1.5 text-[11px] text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
                    >
                      恢复默认源
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditor({ source: null })}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-400"
                    >
                      <PlusIcon className="h-3.5 w-3.5" />
                      新增源
                    </button>
                  </div>
                </div>
                {sources.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-zinc-200 px-4 py-12 text-center dark:border-white/10">
                    <DatabaseIcon className="mx-auto h-8 w-8 text-zinc-300 dark:text-zinc-700" />
                    <p className="mt-3 text-sm text-zinc-500">还没有配置刮削源</p>
                  </div>
                ) : (
                  <ul className="divide-y divide-zinc-100 dark:divide-white/5">
                    {sources.map((source) => (
                      <li key={source.id} className="flex flex-wrap items-center gap-3 py-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                              {source.name}
                            </span>
                            <span className="rounded border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-700 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300">
                              {typeLabel(source)}
                            </span>
                            {source.config.type === "actress" && (
                              <UserIcon className="h-3.5 w-3.5 text-zinc-400" />
                            )}
                            {source.builtin && (
                              <span className="rounded border border-zinc-200 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:border-white/10">
                                内置
                              </span>
                            )}
                            {!source.enabled && (
                              <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
                                已禁用
                              </span>
                            )}
                          </div>
                          <div className="mt-1 text-[11px] text-zinc-500">
                            优先级 {source.priority}
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => void toggleSource(source)}
                            className={`relative h-5 w-9 rounded-full transition ${
                              source.enabled ? "bg-sky-500" : "bg-zinc-300 dark:bg-zinc-700"
                            }`}
                            aria-label={source.enabled ? "禁用" : "启用"}
                          >
                            <span
                              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${
                                source.enabled ? "left-[18px]" : "left-0.5"
                              }`}
                            />
                          </button>
                          {/* 内置源只允许启停，配置和删除入口禁用。 */}
                          <button
                            type="button"
                            onClick={() => setEditor({ source })}
                            disabled={source.builtin}
                            className="rounded-md border border-zinc-200 px-2 py-1 text-[11px] text-zinc-600 hover:bg-zinc-100 disabled:opacity-30 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
                          >
                            编辑
                          </button>
                          <button
                            type="button"
                            onClick={() => void removeSource(source)}
                            disabled={source.builtin}
                            aria-label="删除源"
                            className="rounded-md p-1.5 text-zinc-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-30 dark:hover:bg-red-500/10"
                          >
                            <TrashIcon className="h-4 w-4" />
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 删除目录：确认后清理记录，按选择决定是否删除磁盘文件。 */}
      {deletingRoot && (
        <RootDeleteModal
          root={deletingRoot}
          onClose={() => setDeletingRoot(null)}
          onDeleted={(result) => {
            setDeletingRoot(null);
            void loadRoots();
            onChanged();
            if (result.failed_files.length > 0) {
              setError(
                `数据已删除，但有 ${result.failed_files.length} 个文件删除失败：${result.failed_files
                  .map((file) => `${file.filename}（${file.message}）`)
                  .join("；")}`,
              );
            } else if (result.deleted_files > 0) {
              setNotice(
                `已删除 ${result.deleted_videos} 部影片和 ${result.deleted_files} 个文件`,
              );
            } else {
              setNotice(`已删除 ${result.deleted_videos} 部影片的数据`);
            }
          }}
        />
      )}

      {/* 目录编辑保存后刷新列表并通知主界面，路径变更可能影响视频列表。 */}
      {rootEditor && (
        <RootSettingsModal
          root={rootEditor}
          onClose={() => setRootEditor(null)}
          onSaved={(message) => {
            setRootEditor(null);
            void loadRoots();
            onChanged();
            setNotice(message);
          }}
        />
      )}

      {/* source 为 null 表示新增；保存后关闭编辑器并重新拉取源列表。 */}
      {editor && (
        <SourceForm
          source={editor.source}
          onClose={() => setEditor(null)}
          onSaved={() => {
            setEditor(null);
            void loadSources();
            setNotice("源配置已保存");
          }}
        />
      )}
    </div>
  );
}
