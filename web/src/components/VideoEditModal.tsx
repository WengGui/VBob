/**
 * 视频元数据编辑弹窗。
 * 表单字段在初始化时从 detail 拷贝；保存时映射回后端的 snake_case 键，
 * 并携带 version 做并发校验。封面支持上传文件或填写远端 URL，文件优先。
 */
import { useState } from "react";
import type { ReactNode } from "react";
import type { VideoDetail } from "../api";
import { api } from "../api";
import { errorMessage } from "../format";
import { Modal } from "./Modal";
import { VideoMergePicker } from "./VideoMergePicker";

const INPUT =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-600";

/** 逗号/顿号分隔的输入统一转成数组，兼容中英文标点并丢弃空项。 */
function splitList(value: string): string[] {
  return value
    .split(/[,，、]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <label className="mb-1 block text-[11px] font-medium text-zinc-500 dark:text-zinc-400">
      {children}
    </label>
  );
}

/** 编辑视频信息；保存成功后调用 onSaved 让父组件关闭弹窗并刷新列表/详情。 */
export function VideoEditModal({
  detail,
  onClose,
  onSaved,
  onMerged,
}: {
  detail: VideoDetail;
  onClose: () => void;
  onSaved: () => void;
  /** 当前视频已被合并到其他视频，父组件需要关闭详情并刷新列表。 */
  onMerged: () => void;
}) {
  const metadata = detail.metadata;
  const [title, setTitle] = useState(metadata?.title ?? "");
  const [originalTitle, setOriginalTitle] = useState(metadata?.original_title ?? "");
  const [releaseDate, setReleaseDate] = useState(metadata?.release_date ?? "");
  const [code, setCode] = useState(
    metadata?.code ??
      (typeof detail.video.features.jav_code === "string"
        ? detail.video.features.jav_code
        : ""),
  );
  const [series, setSeries] = useState(metadata?.series ?? "");
  const [studio, setStudio] = useState(metadata?.studio ?? "");
  const [director, setDirector] = useState(metadata?.director ?? "");
  const [country, setCountry] = useState(metadata?.country ?? "");
  const [censored, setCensored] = useState(metadata?.censored ?? "");
  const [runtimeMinutes, setRuntimeMinutes] = useState(
    metadata?.runtime_sec ? String(Math.round(metadata.runtime_sec / 60)) : "",
  );
  const [genres, setGenres] = useState((metadata?.genres ?? []).join(", "));
  const [tags, setTags] = useState((metadata?.tags ?? []).join(", "));
  const [actresses, setActresses] = useState(
    detail.actresses.map((actress) => actress.name).join(", "),
  );
  const [overview, setOverview] = useState(metadata?.overview ?? "");
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [coverUrl, setCoverUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      // 界面按分钟编辑，后端存秒；空值表示不设置，非法输入在提交前拦截。
      const runtime = runtimeMinutes.trim()
        ? Math.max(0, Math.round(Number(runtimeMinutes) * 60))
        : null;
      if (runtime !== null && Number.isNaN(runtime)) {
        throw new Error("时长必须是数字（分钟）");
      }

      // 只提交真正修改过的字段，避免“点一次保存就把所有字段标记为手动”，
      // 导致之后重新刮削无法补全任何信息。
      const initialCode =
        metadata?.code ??
        (typeof detail.video.features.jav_code === "string"
          ? detail.video.features.jav_code
          : "");
      const initialGenres = metadata?.genres ?? [];
      const initialTags = metadata?.tags ?? [];
      const initialActresses = detail.actresses.map((actress) => actress.name);
      const currentGenres = splitList(genres);
      const currentTags = splitList(tags);
      const currentActresses = splitList(actresses);
      const sameList = (left: string[], right: string[]) =>
        left.length === right.length && left.every((value, index) => value === right[index]);

      const patch: Record<string, unknown> = { version: metadata?.version ?? 0 };
      if (title !== (metadata?.title ?? "")) patch.title = title;
      if (originalTitle !== (metadata?.original_title ?? "")) {
        patch.original_title = originalTitle;
      }
      if (releaseDate !== (metadata?.release_date ?? "")) {
        patch.release_date = releaseDate || null;
      }
      if (code !== initialCode) patch.code = code;
      if (series !== (metadata?.series ?? "")) patch.series = series;
      if (studio !== (metadata?.studio ?? "")) patch.studio = studio;
      if (director !== (metadata?.director ?? "")) patch.director = director;
      if (country !== (metadata?.country ?? "")) patch.country = country;
      if (censored !== (metadata?.censored ?? "")) patch.censored = censored || null;
      const initialMinutes = metadata?.runtime_sec
        ? String(Math.round(metadata.runtime_sec / 60))
        : "";
      if (runtimeMinutes !== initialMinutes) patch.runtime_sec = runtime;
      if (!sameList(currentGenres, initialGenres)) patch.genres = currentGenres;
      if (!sameList(currentTags, initialTags)) patch.tags = currentTags;
      if (!sameList(currentActresses, initialActresses)) {
        // 后端按姓名匹配已有演员，不存在的会在保存时创建。
        patch.actresses = currentActresses.map((name) => ({ name }));
      }
      if (overview !== (metadata?.overview ?? "")) patch.overview = overview;

      if (Object.keys(patch).length > 1) {
        await api.updateVideoMetadata(detail.video.id, patch);
      }
      // 文件与 URL 同时存在时以文件为准，避免一次保存下载两次封面。
      if (coverFile) {
        await api.uploadVideoCover(detail.video.id, coverFile);
      } else if (coverUrl.trim()) {
        await api.setVideoCoverUrl(detail.video.id, coverUrl.trim());
      }
      onSaved();
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
    <Modal
      title="编辑视频信息"
      subtitle="只保存修改过的字段，这些字段不会被自动刮削覆盖"
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
            type="button"
            onClick={() => void save()}
            disabled={saving}
            className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-40"
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <FieldLabel>名称</FieldLabel>
          <input value={title} onChange={(event) => setTitle(event.target.value)} className={INPUT} />
        </div>
        <div className="sm:col-span-2">
          <FieldLabel>原名</FieldLabel>
          <input
            value={originalTitle}
            onChange={(event) => setOriginalTitle(event.target.value)}
            className={INPUT}
          />
        </div>
        <div>
          <FieldLabel>番号</FieldLabel>
          <input value={code} onChange={(event) => setCode(event.target.value)} className={INPUT} />
        </div>
        <div>
          <FieldLabel>发行日期</FieldLabel>
          <input
            value={releaseDate}
            onChange={(event) => setReleaseDate(event.target.value)}
            placeholder="2026-10-29 或 2026"
            className={INPUT}
          />
        </div>
        <div>
          <FieldLabel>时长（分钟）</FieldLabel>
          <input
            value={runtimeMinutes}
            onChange={(event) => setRuntimeMinutes(event.target.value)}
            inputMode="decimal"
            className={INPUT}
          />
        </div>
        <div>
          <FieldLabel>是否有码</FieldLabel>
          <select
            value={censored}
            onChange={(event) => setCensored(event.target.value)}
            className={INPUT}
          >
            <option value="">未设置</option>
            <option value="censored">有码</option>
            <option value="uncensored">无码</option>
            <option value="unknown">未知</option>
          </select>
        </div>
        <div>
          <FieldLabel>国家/地区</FieldLabel>
          <input
            value={country}
            onChange={(event) => setCountry(event.target.value)}
            className={INPUT}
          />
        </div>
        <div>
          <FieldLabel>系列</FieldLabel>
          <input value={series} onChange={(event) => setSeries(event.target.value)} className={INPUT} />
        </div>
        <div>
          <FieldLabel>厂商</FieldLabel>
          <input value={studio} onChange={(event) => setStudio(event.target.value)} className={INPUT} />
        </div>
        <div>
          <FieldLabel>导演</FieldLabel>
          <input
            value={director}
            onChange={(event) => setDirector(event.target.value)}
            className={INPUT}
          />
        </div>
        <div className="sm:col-span-2">
          <FieldLabel>演员（逗号分隔，可新建）</FieldLabel>
          <input
            value={actresses}
            onChange={(event) => setActresses(event.target.value)}
            placeholder="演员 A, 演员 B"
            className={INPUT}
          />
        </div>
        <div className="sm:col-span-2">
          <FieldLabel>类型（逗号分隔）</FieldLabel>
          <input value={genres} onChange={(event) => setGenres(event.target.value)} className={INPUT} />
        </div>
        <div className="sm:col-span-2">
          <FieldLabel>标签（逗号分隔）</FieldLabel>
          <input value={tags} onChange={(event) => setTags(event.target.value)} className={INPUT} />
        </div>
        <div className="sm:col-span-2">
          <FieldLabel>简介</FieldLabel>
          <textarea
            value={overview}
            onChange={(event) => setOverview(event.target.value)}
            rows={3}
            className={INPUT}
          />
        </div>
        <div className="sm:col-span-2 rounded-xl border border-zinc-200 p-3 dark:border-white/10">
          <FieldLabel>封面</FieldLabel>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => setCoverFile(event.target.files?.[0] ?? null)}
            className="w-full text-xs text-zinc-500 file:mr-3 file:rounded-md file:border-0 file:bg-zinc-100 file:px-3 file:py-1.5 file:text-xs file:text-zinc-700 dark:file:bg-white/10 dark:file:text-zinc-200"
          />
          <div className="mt-2 flex gap-2">
            <input
              value={coverUrl}
              onChange={(event) => setCoverUrl(event.target.value)}
              placeholder="或填写图片 URL，保存时下载到本地"
              className={INPUT}
            />
          </div>
          {(metadata?.cover_local || coverFile) && (
            <p className="mt-2 text-[11px] text-zinc-500">
              {coverFile ? `已选择文件：${coverFile.name}` : "已有本地封面，重新上传会覆盖。"}
            </p>
          )}
        </div>
        <div className="sm:col-span-2 rounded-xl border border-sky-200 bg-sky-50/50 p-3 dark:border-sky-500/20 dark:bg-sky-500/5">
          <FieldLabel>剧集分组</FieldLabel>
          <p className="text-[11px] leading-relaxed text-zinc-500">
            把当前视频合并到另一个海报下，两个记录变成一个剧集分组，文件路径不会改变。
            合并前请先保存其他修改；合并后当前记录会被删除。
          </p>
          <button
            type="button"
            onClick={() => setMergeOpen(true)}
            className="mt-2 rounded-lg bg-sky-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-400"
          >
            归入其他剧集…
          </button>
        </div>
      </div>
      {error && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      )}
    </Modal>
    {mergeOpen && (
      <VideoMergePicker
        sourceId={detail.video.id}
        sourceTitle={metadata?.title || detail.video.filename}
        onClose={() => setMergeOpen(false)}
        onMerged={() => {
          setMergeOpen(false);
          onMerged();
        }}
      />
    )}
    </>
  );
}
