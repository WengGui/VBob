/**
 * 播放器设置面板。
 * 读取设置中的 playback.player，支持通过本机文件选择框指定播放器、
 * 使用自动检测结果，或改回自动检测；保存后点击播放即调用该程序。
 */
import { useEffect, useState } from "react";
import { api, type AppSettings, type PlayerConfig, type PlayerInfo } from "../api";
import { errorMessage } from "../format";
import { PlayIcon, ScanIcon, SettingsIcon } from "./Icons";

const INPUT =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-600";

/** 从可执行文件名推断播放器标识，与后端的 name 约定保持一致。 */
function inferName(path: string): string {
  const file = path.split(/[\\/]/).pop() ?? "custom";
  const stem = file.replace(/\.[^.]+$/, "").toLowerCase();
  if (stem.includes("potplayer")) return "potplayer";
  if (stem.includes("mpv")) return "mpv";
  if (stem.includes("vlc")) return "vlc";
  return stem || "custom";
}

export function PlayerSettingsPanel({
  players,
  onReloadPlayers,
  onNotice,
}: {
  players: PlayerInfo[];
  /** 重新探测本机播放器（父组件加载 players）。 */
  onReloadPlayers: () => void;
  onNotice: (message: string) => void;
}) {
  // undefined 表示设置仍在加载，null 表示选择自动检测。
  const [configured, setConfigured] = useState<PlayerConfig | null | undefined>(undefined);
  const [pathDraft, setPathDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSettings()
      .then((settings: AppSettings) => {
        if (cancelled) return;
        const player = settings.playback?.player ?? null;
        setConfigured(player);
        setPathDraft(player?.path ?? "");
      })
      .catch((loadError) => {
        if (!cancelled) setError(errorMessage(loadError));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 统一保存：player 为 null 时表示改回自动检测。
  async function savePlayer(player: PlayerConfig | null, message: string) {
    setSaving(true);
    setError(null);
    try {
      const settings = await api.updateSettings({ playback: { player } });
      const next = settings.playback?.player ?? null;
      setConfigured(next);
      setPathDraft(next?.path ?? "");
      onNotice(message);
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  // 后端弹出系统文件选择框；取消时 path 为 null。
  async function chooseExecutable() {
    setPicking(true);
    setError(null);
    try {
      const picked = await api.pickPlayer();
      if (picked.path) {
        await savePlayer(
          { name: picked.name || inferName(picked.path), path: picked.path, args: [] },
          `已选择播放器：${picked.path}`,
        );
      }
    } catch (pickError) {
      setError(errorMessage(pickError));
    } finally {
      setPicking(false);
    }
  }

  async function saveManualPath() {
    const path = pathDraft.trim();
    if (!path) {
      setError("请填写播放器可执行文件的完整路径");
      return;
    }
    // 路径未变时保留原有参数模板；换了程序则使用空参数。
    const args = configured?.path === path ? configured.args : [];
    await savePlayer({ name: inferName(path), path, args }, "播放器路径已保存");
  }

  const configuredPath = configured?.path;
  const current = players.find(
    (player) => player.path.toLowerCase() === configuredPath?.toLowerCase(),
  );

  return (
    <div className="space-y-4">
      {/* 当前播放器概览：用户一眼能看出点击播放时会启动哪个程序。 */}
      <section className="rounded-xl border border-sky-200 bg-sky-50/60 p-4 dark:border-sky-500/20 dark:bg-sky-500/[0.06]">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-zinc-800 dark:text-zinc-100">
            <PlayIcon className="h-4 w-4 text-sky-600 dark:text-sky-300" />
            当前播放器
          </div>
          <span
            className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${
              configured
                ? "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300"
                : "bg-zinc-100 text-zinc-600 dark:bg-white/10 dark:text-zinc-300"
            }`}
          >
            {configured ? "已指定" : "自动检测"}
          </span>
        </div>
        {configured ? (
          <>
            <div className="mt-2 text-sm font-medium text-zinc-800 dark:text-zinc-100">
              {configured.name}
              {current && (
                <span className="ml-2 text-[11px] font-normal text-zinc-500">
                  已检测到
                </span>
              )}
            </div>
            <div className="mt-0.5 break-all font-mono text-[11px] text-zinc-500">
              {configured.path}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void chooseExecutable()}
                disabled={picking || saving}
                className="rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-400 disabled:opacity-40"
              >
                {picking ? "等待选择…" : "更换播放器"}
              </button>
              <button
                type="button"
                onClick={() => void savePlayer(null, "已改为自动检测播放器")}
                disabled={saving}
                className="rounded-lg border border-zinc-200 px-3 py-1.5 text-xs text-zinc-600 hover:bg-zinc-100 disabled:opacity-40 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
              >
                改回自动检测
              </button>
            </div>
          </>
        ) : configured === null ? (
          <>
            <p className="mt-2 text-xs leading-relaxed text-zinc-500">
              尚未指定播放器，点击播放时会按 mpv / VLC / PotPlayer 的顺序自动检测。
            </p>
            <button
              type="button"
              onClick={() => void chooseExecutable()}
              disabled={picking || saving}
              className="mt-3 rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-400 disabled:opacity-40"
            >
              {picking ? "等待选择…" : "选择本地播放器"}
            </button>
          </>
        ) : (
          <p className="mt-2 text-xs text-zinc-500">正在读取播放器设置…</p>
        )}
      </section>

      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
            检测到的播放器
          </h3>
          <p className="text-[11px] text-zinc-500">来自 PATH 或常见安装目录，点击「使用」即可保存。</p>
        </div>
        <button
          type="button"
          onClick={onReloadPlayers}
          className="inline-flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-[11px] text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
        >
          <ScanIcon className="h-3.5 w-3.5" />
          重新检测
        </button>
      </div>

      {players.length === 0 ? (
        <p className="rounded-xl border border-dashed border-zinc-200 px-4 py-8 text-center text-sm text-zinc-500 dark:border-white/10">
          未检测到播放器。可以直接在下方选择本机程序，或安装 mpv / VLC / PotPlayer 后重新检测。
        </p>
      ) : (
        <ul className="space-y-2">
          {players.map((player) => {
            const active = player.path.toLowerCase() === configuredPath?.toLowerCase();
            return (
              <li
                key={player.path}
                className={`flex items-center gap-3 rounded-xl border p-3 ${
                  active
                    ? "border-sky-300 bg-sky-50/60 dark:border-sky-500/40 dark:bg-sky-500/5"
                    : "border-zinc-200 dark:border-white/10"
                }`}
              >
                <SettingsIcon className="h-5 w-5 shrink-0 text-zinc-400" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                    {player.name}
                    <span className="ml-2 text-[10px] font-normal text-zinc-400">
                      {player.source === "path" ? "PATH" : "常见安装目录"}
                    </span>
                  </div>
                  <div className="truncate font-mono text-[11px] text-zinc-500">
                    {player.path}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    void savePlayer(
                      { name: player.name, path: player.path, args: [] },
                      `已使用 ${player.name} 播放`,
                    )
                  }
                  disabled={active || saving}
                  className="shrink-0 rounded-lg border border-zinc-200 px-3 py-1 text-xs text-zinc-600 hover:bg-zinc-100 disabled:opacity-40 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
                >
                  {active ? "使用中" : "使用"}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {/* 文件选择框不可用时的手动兜底，也可以直接粘贴路径。 */}
      <section className="rounded-xl border border-zinc-200 p-4 dark:border-white/10">
        <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">手动指定路径</h3>
        <p className="mt-0.5 text-[11px] text-zinc-500">
          选择框由本机后端弹出；也可以在下方粘贴可执行文件的完整路径。
        </p>
        <input
          value={pathDraft}
          onChange={(event) => setPathDraft(event.target.value)}
          placeholder="C:\Tools\mpv\mpv.exe"
          spellCheck={false}
          className={`${INPUT} mt-2 font-mono text-xs`}
        />
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void chooseExecutable()}
            disabled={picking || saving}
            className="rounded-lg border border-zinc-200 px-3 py-1.5 text-xs text-zinc-600 hover:bg-zinc-100 disabled:opacity-40 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
          >
            {picking ? "等待选择…" : "浏览本机文件…"}
          </button>
          <button
            type="button"
            onClick={() => void saveManualPath()}
            disabled={saving || picking}
            className="rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-400 disabled:opacity-40"
          >
            保存路径
          </button>
        </div>
      </section>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      )}
    </div>
  );
}
