/**
 * 目录编辑弹窗。
 * 编辑扫描目录的路径、自动扫描间隔、媒体类型和限定源；
 * 限定源按勾选顺序执行，留空时使用该分类下全部启用源。
 */
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, CATEGORY_LABELS, categoryLabel, type ScanRoot, type Source } from "../api";
import { errorMessage, formatDate, formatDuration } from "../format";
import { ClockIcon, FolderIcon, PlusIcon, TrashIcon } from "./Icons";
import { Modal } from "./Modal";

const INPUT =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-600";

/** 常用间隔，点击后直接填入输入框；0 表示关闭自动扫描。 */
const PRESETS = [
  { minutes: 0, label: "关闭" },
  { minutes: 5, label: "5 分钟" },
  { minutes: 15, label: "15 分钟" },
  { minutes: 30, label: "30 分钟" },
  { minutes: 60, label: "1 小时" },
  { minutes: 120, label: "2 小时" },
  { minutes: 360, label: "6 小时" },
] as const;

export function RootSettingsModal({
  root,
  onClose,
  onSaved,
}: {
  /** null 表示新增目录；传入现有目录则为编辑模式。 */
  root: ScanRoot | null;
  onClose: () => void;
  /** 保存成功后由父组件关闭弹窗、刷新列表并展示提示。 */
  onSaved: (message: string) => void;
}) {
  const isNew = root === null;
  const [path, setPath] = useState(root?.path ?? "");
  const [interval, setIntervalValue] = useState(
    String(root?.scan_interval_minutes ?? 0),
  );
  const [category, setCategory] = useState(root?.category ?? "other");
  // 已选源保持用户点击顺序，顺序即刮削顺序。
  const [selected, setSelected] = useState<number[]>(root?.source_ids ?? []);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .listSources()
      .then((data) => setSources(data.items))
      .catch((loadError) => setError(errorMessage(loadError)));
  }, []);

  const minutes = interval.trim() === "" ? 0 : Number(interval);
  const intervalValid = Number.isInteger(minutes) && minutes >= 0;
  const pathChanged = !isNew && path.trim() !== (root?.path ?? "");
  const intervalChanged =
    !isNew && intervalValid && minutes !== (root?.scan_interval_minutes ?? 0);
  const categoryChanged = !isNew && category !== (root?.category ?? "other");
  const selectedChanged =
    !isNew &&
    (selected.length !== (root?.source_ids ?? []).length ||
      selected.some((id, index) => id !== (root?.source_ids ?? [])[index]));
  // 演员源不参与视频刮削，不放在目录限定列表里。
  const selectableSources = sources.filter(
    (source) => source.config.type !== "actress",
  );
  const available = selectableSources.filter(
    (source) => !selected.includes(source.id),
  );
  const sourceById = new Map(
    selectableSources.map((source) => [source.id, source]),
  );

  // 选中/取消/上下移动都保持数组顺序，后端按该顺序执行源。
  function addSource(id: number) {
    setSelected((current) => (current.includes(id) ? current : [...current, id]));
  }

  function removeSource(id: number) {
    setSelected((current) => current.filter((item) => item !== id));
  }

  function moveSource(index: number, delta: number) {
    setSelected((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }
  const summary = intervalValid
    ? minutes === 0
      ? "已关闭自动扫描"
      : `每 ${minutes} 分钟自动扫描一次`
    : "请输入有效的分钟数";

  // 由后端弹出系统目录选择框，避免手动输入完整路径。
  async function browse() {
    setError(null);
    try {
      const { path: picked } = await api.pickDirectory();
      if (picked) setPath(picked);
    } catch (pickError) {
      setError(errorMessage(pickError));
    }
  }

  // 路径为空或间隔非法时不提交，错误直接展示在表单内，避免离开弹窗后才发现。
  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const trimmed = path.trim();
    if (!trimmed) {
      setError("目录路径不能为空");
      return;
    }
    if (!intervalValid) {
      setError("自动扫描间隔必须是 0 或正整数（分钟）");
      return;
    }
    if (!isNew && !pathChanged && !intervalChanged && !categoryChanged && !selectedChanged) {
      onClose();
      return;
    }
    setSaving(true);
    try {
      if (root === null) {
        await api.createRoot(trimmed, minutes, category, selected);
        onSaved("目录已添加，可以开始扫描");
        return;
      }
      await api.updateRoot(root.id, {
        ...(pathChanged ? { path: trimmed } : {}),
        ...(intervalChanged ? { scan_interval_minutes: minutes } : {}),
        ...(categoryChanged ? { category } : {}),
        ...(selectedChanged ? { source_ids: selected } : {}),
      });
      onSaved(
        pathChanged
          ? "目录路径已更新，已有记录已按相对路径迁移"
          : "目录设置已保存",
      );
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={isNew ? "添加目录" : "编辑目录"}
      subtitle={isNew ? "选择目录并设置媒体类型与刮削源" : (root?.path ?? "")}
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-zinc-200 px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
          >
            取消
          </button>
          <button
            type="submit"
            form="root-settings-form"
            disabled={saving || !intervalValid}
            className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-40"
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </>
      }
    >
      <form id="root-settings-form" onSubmit={(event) => void save(event)}>
        {/* 顶部概览：让用户在修改配置时仍能看到该目录的扫描结果。 */}
        {root && (
          <div className="grid grid-cols-2 gap-2 rounded-xl bg-zinc-50 p-3 sm:grid-cols-4 dark:bg-white/[0.03]">
            <Stat label="已收录" value={`${root.scanned_count ?? 0} 部`} />
            <Stat label="文件" value={`${root.file_count ?? root.scanned_count ?? 0} 个`} />
            <Stat label="已刮削" value={String(root.scraped_count ?? 0)} />
            <Stat
              label="自动扫描"
              value={root.scan_interval_minutes ? `${root.scan_interval_minutes} 分钟` : "关闭"}
            />
          </div>
        )}

        <fieldset className="mt-4 rounded-xl border border-zinc-200 p-4 dark:border-white/10">
          <legend className="sr-only">目录路径</legend>
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-50 text-sky-600 dark:bg-sky-500/10 dark:text-sky-300">
              <FolderIcon className="h-4 w-4" />
            </span>
            <div>
              <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                目录路径
              </h3>
              <p className="text-[11px] text-zinc-500">
                文件夹被改名或移动后，在这里更新为新地址。
              </p>
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <input
              autoFocus
              value={path}
              onChange={(event) => setPath(event.target.value)}
              placeholder="D:\Media 或 /media/videos"
              spellCheck={false}
              className={`${INPUT} font-mono text-xs`}
            />
            <button
              type="button"
              onClick={() => void browse()}
              className="shrink-0 whitespace-nowrap rounded-lg border border-zinc-200 px-3 py-2 text-xs text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
            >
              浏览…
            </button>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">
            目录被改名/移动时，已有视频会按相对路径迁移；如果只是把扫描范围改成子目录或上级目录，文件不会移动，范围外的记录会标记为缺失。
          </p>
        </fieldset>

        <fieldset className="mt-3 rounded-xl border border-zinc-200 p-4 dark:border-white/10">
          <legend className="sr-only">媒体类型与刮削源</legend>
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-300">
              <FolderIcon className="h-4 w-4" />
            </span>
            <div>
              <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                媒体类型与刮削源
              </h3>
              <p className="text-[11px] text-zinc-500">
                目录内的视频默认使用该分类；限定源留空时使用分类下全部启用源。
              </p>
            </div>
          </div>

          <div className="mt-3">
            <label className="text-[11px] text-zinc-500">媒体类型</label>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              className={`${INPUT} mt-1`}
            >
              {CATEGORY_LABELS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="mt-3">
            <div className="flex items-center justify-between">
              <label className="text-[11px] text-zinc-500">
                限定源（可选，按列表顺序执行）
              </label>
              <span className="text-[10px] text-zinc-400">留空 = 自动</span>
            </div>
            {selected.length === 0 ? (
              <p className="mt-2 rounded-lg border border-dashed border-zinc-200 px-3 py-3 text-center text-[11px] text-zinc-400 dark:border-white/10">
                未限定，使用「{categoryLabel(category)}」分类下全部启用源
              </p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {selected.map((id, index) => {
                  const source = sourceById.get(id);
                  return (
                    <li
                      key={id}
                      className="flex items-center gap-2 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-xs dark:border-white/10"
                    >
                      <span className="w-5 shrink-0 text-center text-[10px] text-zinc-400">
                        {index + 1}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-zinc-700 dark:text-zinc-200">
                        {source?.name ?? `已删除的源 #${id}`}
                      </span>
                      <span className="shrink-0 text-[10px] text-zinc-400">
                        {source ? categoryLabel(source.category) : ""}
                      </span>
                      <button
                        type="button"
                        onClick={() => moveSource(index, -1)}
                        disabled={index === 0}
                        aria-label="上移"
                        className="rounded px-1 text-zinc-400 hover:bg-zinc-100 disabled:opacity-30 dark:hover:bg-white/5"
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        onClick={() => moveSource(index, 1)}
                        disabled={index === selected.length - 1}
                        aria-label="下移"
                        className="rounded px-1 text-zinc-400 hover:bg-zinc-100 disabled:opacity-30 dark:hover:bg-white/5"
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        onClick={() => removeSource(id)}
                        aria-label="移除"
                        className="rounded p-1 text-zinc-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
                      >
                        <TrashIcon className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
            {available.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {available.map((source) => (
                  <button
                    key={source.id}
                    type="button"
                    onClick={() => addSource(source.id)}
                    className="inline-flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-[11px] text-zinc-600 hover:border-sky-300 hover:bg-sky-50 hover:text-sky-700 dark:border-white/10 dark:text-zinc-300 dark:hover:border-sky-500/30 dark:hover:bg-sky-500/10 dark:hover:text-sky-300"
                  >
                    <PlusIcon className="h-3 w-3" />
                    {source.name}
                    <span className="text-[10px] text-zinc-400">
                      {categoryLabel(source.category)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </fieldset>

        <fieldset className="mt-3 rounded-xl border border-zinc-200 p-4 dark:border-white/10">
          <legend className="sr-only">自动扫描间隔</legend>
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-300">
              <ClockIcon className="h-4 w-4" />
            </span>
            <div>
              <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                自动扫描间隔
              </h3>
              <p className="text-[11px] text-zinc-500">{summary}</p>
            </div>
          </div>

          {/* 常用间隔快捷选择，选中态与输入框保持同步。 */}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {PRESETS.map((preset) => {
              const selected = intervalValid && preset.minutes === minutes;
              return (
                <button
                  key={preset.minutes}
                  type="button"
                  onClick={() => setIntervalValue(String(preset.minutes))}
                  className={`rounded-lg border px-2.5 py-1 text-xs transition ${
                    selected
                      ? "border-sky-300 bg-sky-50 font-medium text-sky-700 dark:border-sky-500/40 dark:bg-sky-500/10 dark:text-sky-300"
                      : "border-zinc-200 text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>

          <div className="mt-3 flex items-center gap-2">
            {/* 单独写宽度，避免与 INPUT 中的 w-full 冲突导致提示文字换行。 */}
            <input
              type="number"
              min={0}
              step={1}
              value={interval}
              onChange={(event) => setIntervalValue(event.target.value)}
              aria-label="自动扫描间隔（分钟）"
              className="w-24 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200"
            />
            <span className="whitespace-nowrap text-xs text-zinc-500">分钟</span>
            <span className="ml-auto whitespace-nowrap text-[11px] text-zinc-400">
              0 表示关闭
            </span>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-zinc-500">
            服务运行期间每 30 秒检查一次，到期且没有正在运行的任务时自动扫描。
            {root?.last_scan_started_at && (
              <>
                {" "}上次扫描：{formatDate(root.last_scan_started_at)}
                {root.last_scan_duration_ms != null &&
                  `，耗时 ${root.last_scan_duration_ms < 1000 ? "<1 秒" : formatDuration(Math.round(root.last_scan_duration_ms / 1000))}`}
              </>
            )}
          </p>
        </fieldset>

        {error && (
          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
            {error}
          </div>
        )}
      </form>
    </Modal>
  );
}

/** 概览区的小号指标。 */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-zinc-800 dark:text-zinc-100">{value}</div>
    </div>
  );
}
