import { useState } from "react";
import type { ReactNode } from "react";
import type { VideoDetail } from "../api";
import { api } from "../api";
import { errorMessage } from "../format";
import { Modal } from "./Modal";

const INPUT =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-600";

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

export function VideoEditModal({
  detail,
  onClose,
  onSaved,
}: {
  detail: VideoDetail;
  onClose: () => void;
  onSaved: () => void;
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

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const runtime = runtimeMinutes.trim()
        ? Math.max(0, Math.round(Number(runtimeMinutes) * 60))
        : null;
      if (runtime !== null && Number.isNaN(runtime)) {
        throw new Error("时长必须是数字（分钟）");
      }
      await api.updateVideoMetadata(detail.video.id, {
        version: metadata?.version ?? 0,
        title,
        original_title: originalTitle,
        release_date: releaseDate || null,
        code,
        series,
        studio,
        director,
        country,
        censored: censored || null,
        runtime_sec: runtime,
        genres: splitList(genres),
        tags: splitList(tags),
        actresses: splitList(actresses).map((name) => ({ name })),
        overview,
      });
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
    <Modal
      title="编辑视频信息"
      subtitle="所有字段都会标记为手动值，自动刮削不会覆盖"
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
      </div>
      {error && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      )}
    </Modal>
  );
}
