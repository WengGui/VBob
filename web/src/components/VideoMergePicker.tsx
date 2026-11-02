/**
 * 手动归并剧集：搜索并选择一个目标视频，把当前视频的文件合并过去。
 * 合并后两个海报变成一个，当前视频记录会被删除。
 */
import { useEffect, useState } from "react";
import { api, type Video } from "../api";
import { codeOf, errorMessage, titleOf } from "../format";
import { SearchIcon } from "./Icons";
import { Modal } from "./Modal";

export function VideoMergePicker({
  sourceId,
  sourceTitle,
  onClose,
  onMerged,
}: {
  sourceId: number;
  sourceTitle: string;
  onClose: () => void;
  onMerged: (targetId: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [mergingId, setMergingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 输入停顿后再搜索，避免每敲一个字都请求。
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      api
        .listVideos({ pageSize: 20, q: query.trim() || undefined, sort: "updated_at" })
        .then((data) => {
          if (!cancelled) setResults(data.items.filter((item) => item.id !== sourceId));
        })
        .catch((loadError) => {
          if (!cancelled) setError(errorMessage(loadError));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, sourceId]);

  async function merge(target: Video) {
    setMergingId(target.id);
    setError(null);
    try {
      await api.mergeVideos(target.id, [sourceId]);
      onMerged(target.id);
    } catch (mergeError) {
      setError(errorMessage(mergeError));
    } finally {
      setMergingId(null);
    }
  }

  return (
    <Modal
      title="归入其他剧集"
      subtitle={sourceTitle}
      onClose={onClose}
      footer={
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-zinc-200 px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
        >
          取消
        </button>
      }
    >
      <p className="text-xs leading-relaxed text-zinc-500">
        选择目标后，当前视频会合并到目标海报下，两个记录变成一个剧集分组；文件路径不会改变。
      </p>
      <div className="relative mt-3">
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索标题 / 文件名 / 番号 / 演员"
          autoFocus
          className="w-full rounded-lg border border-zinc-200 bg-white py-2 pl-9 pr-3 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-600"
        />
      </div>

      <div className="mt-3 max-h-[360px] overflow-y-auto">
        {loading ? (
          <p className="py-8 text-center text-sm text-zinc-500">正在搜索…</p>
        ) : results.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-500">没有可合并的其他视频</p>
        ) : (
          <ul className="divide-y divide-zinc-100 dark:divide-white/5">
            {results.map((video) => (
              <li key={video.id}>
                <button
                  type="button"
                  onClick={() => void merge(video)}
                  disabled={mergingId !== null}
                  className="flex w-full items-center gap-3 py-2.5 text-left transition hover:bg-zinc-50 disabled:opacity-50 dark:hover:bg-white/5"
                >
                  <span className="flex h-10 w-16 shrink-0 items-center justify-center overflow-hidden rounded-md bg-zinc-100 text-xs font-semibold text-zinc-400 dark:bg-zinc-800">
                    {video.metadata?.cover_local ? (
                      <img
                        src={`/api/videos/${video.id}/cover`}
                        alt=""
                        className="h-full w-full object-cover"
                        onError={(event) => {
                          event.currentTarget.style.display = "none";
                        }}
                      />
                    ) : (
                      codeOf(video).slice(0, 8) || "VBob"
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
                      {titleOf(video)}
                    </span>
                    <span className="block text-[11px] text-zinc-500">
                      {codeOf(video) || "无番号"}
                      {(video.file_count ?? 1) > 1 ? ` · ${video.file_count} 个文件` : ""}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-sky-600 dark:text-sky-400">
                    {mergingId === video.id ? "合并中…" : "合并到此"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      )}
    </Modal>
  );
}
