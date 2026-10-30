import { useState } from "react";
import type { ActressDetail } from "../api";
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

function Label({ children }: { children: string }) {
  return (
    <label className="mb-1 block text-[11px] font-medium text-zinc-500 dark:text-zinc-400">
      {children}
    </label>
  );
}

export function ActressEditModal({
  detail,
  onClose,
  onSaved,
}: {
  detail: ActressDetail;
  onClose: () => void;
  onSaved: () => void;
}) {
  const actress = detail.actress;
  const [name, setName] = useState(actress.name);
  const [aliases, setAliases] = useState(actress.aliases.join(", "));
  const [birthDate, setBirthDate] = useState(actress.birth_date ?? "");
  const [nationality, setNationality] = useState(actress.nationality ?? "");
  const [height, setHeight] = useState(actress.height_cm ? String(actress.height_cm) : "");
  const [bust, setBust] = useState(actress.bust_cm ? String(actress.bust_cm) : "");
  const [waist, setWaist] = useState(actress.waist_cm ? String(actress.waist_cm) : "");
  const [hips, setHips] = useState(actress.hips_cm ? String(actress.hips_cm) : "");
  const [cup, setCup] = useState(actress.cup ?? "");
  const [profileUrl, setProfileUrl] = useState(actress.profile_url ?? "");
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [coverUrl, setCoverUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function numberOrNull(value: string): number | null {
    if (!value.trim()) return null;
    const parsed = Number(value);
    if (Number.isNaN(parsed)) throw new Error("三围/身高必须是数字");
    return Math.round(parsed);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.updateActress(actress.id, {
        version: actress.version,
        name,
        aliases: splitList(aliases),
        birth_date: birthDate || null,
        nationality,
        height_cm: numberOrNull(height),
        bust_cm: numberOrNull(bust),
        waist_cm: numberOrNull(waist),
        hips_cm: numberOrNull(hips),
        cup,
        profile_url: profileUrl,
      });
      if (coverFile) {
        await api.uploadActressCover(actress.id, coverFile);
      } else if (coverUrl.trim()) {
        await api.setActressCoverUrl(actress.id, coverUrl.trim());
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
      title="编辑演员信息"
      subtitle="姓名、出生日期、国籍、封面计入演员完整度"
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
        <div>
          <Label>姓名</Label>
          <input value={name} onChange={(event) => setName(event.target.value)} className={INPUT} />
        </div>
        <div>
          <Label>别名（逗号分隔）</Label>
          <input
            value={aliases}
            onChange={(event) => setAliases(event.target.value)}
            className={INPUT}
          />
        </div>
        <div>
          <Label>出生日期</Label>
          <input
            value={birthDate}
            onChange={(event) => setBirthDate(event.target.value)}
            placeholder="2000-01-01"
            className={INPUT}
          />
        </div>
        <div>
          <Label>国籍</Label>
          <input
            value={nationality}
            onChange={(event) => setNationality(event.target.value)}
            className={INPUT}
          />
        </div>
        <div>
          <Label>身高（cm）</Label>
          <input value={height} onChange={(event) => setHeight(event.target.value)} className={INPUT} />
        </div>
        <div>
          <Label>罩杯</Label>
          <input value={cup} onChange={(event) => setCup(event.target.value)} className={INPUT} />
        </div>
        <div>
          <Label>胸围（cm）</Label>
          <input value={bust} onChange={(event) => setBust(event.target.value)} className={INPUT} />
        </div>
        <div>
          <Label>腰围（cm）</Label>
          <input value={waist} onChange={(event) => setWaist(event.target.value)} className={INPUT} />
        </div>
        <div>
          <Label>臀围（cm）</Label>
          <input value={hips} onChange={(event) => setHips(event.target.value)} className={INPUT} />
        </div>
        <div>
          <Label>资料页 URL</Label>
          <input
            value={profileUrl}
            onChange={(event) => setProfileUrl(event.target.value)}
            className={INPUT}
          />
        </div>
        <div className="sm:col-span-2 rounded-xl border border-zinc-200 p-3 dark:border-white/10">
          <Label>封面</Label>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => setCoverFile(event.target.files?.[0] ?? null)}
            className="w-full text-xs text-zinc-500 file:mr-3 file:rounded-md file:border-0 file:bg-zinc-100 file:px-3 file:py-1.5 file:text-xs file:text-zinc-700 dark:file:bg-white/10 dark:file:text-zinc-200"
          />
          <input
            value={coverUrl}
            onChange={(event) => setCoverUrl(event.target.value)}
            placeholder="或填写图片 URL，保存时下载到本地"
            className={`${INPUT} mt-2`}
          />
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
