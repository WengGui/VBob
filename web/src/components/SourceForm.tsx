import { useState } from "react";
import type { Source } from "../api";
import { api } from "../api";
import { errorMessage } from "../format";
import { Modal } from "./Modal";
import { PlusIcon, TrashIcon } from "./Icons";

const INPUT =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-800 placeholder:text-zinc-400 focus:border-sky-400 focus:outline-none dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200 dark:placeholder:text-zinc-600";

interface FieldOption {
  key: string;
  label: string;
}

const VIDEO_FIELDS: FieldOption[] = [
  { key: "title", label: "名称" },
  { key: "code", label: "番号" },
  { key: "release_date", label: "发行日期" },
  { key: "actresses", label: "演员" },
  { key: "tags", label: "标签" },
  { key: "cover_url", label: "封面" },
  { key: "runtime_sec", label: "时长" },
  { key: "series", label: "系列" },
  { key: "censored", label: "是否有码" },
  { key: "country", label: "国家/地区" },
  { key: "studio", label: "厂商" },
  { key: "overview", label: "简介" },
];
const ACTRESS_FIELDS: FieldOption[] = [
  { key: "name", label: "姓名" },
  { key: "birth_date", label: "出生日期" },
  { key: "nationality", label: "国籍" },
  { key: "cover_url", label: "封面" },
  { key: "height_cm", label: "身高" },
  { key: "bust_cm", label: "胸围" },
  { key: "waist_cm", label: "腰围" },
  { key: "hips_cm", label: "臀围" },
  { key: "cup", label: "罩杯" },
  { key: "aliases", label: "别名" },
  { key: "profile_url", label: "资料页 URL" },
];
const KINDS = ["css", "xpath", "json", "regex"] as const;

interface ExtractRow {
  field: string;
  kind: (typeof KINDS)[number];
  expression: string;
}

function parseExtract(config: Record<string, unknown>): ExtractRow[] {
  const extract = config.extract;
  if (!extract || typeof extract !== "object") return [];
  return Object.entries(extract as Record<string, unknown>)
    .filter(([, value]) => typeof value === "string")
    .map(([field, value]) => {
      const text = String(value);
      const split = text.indexOf(":");
      const prefix = split > 0 ? text.slice(0, split).trim().toLowerCase() : "css";
      const kind = (KINDS as readonly string[]).includes(prefix)
        ? (prefix as ExtractRow["kind"])
        : "css";
      return {
        field,
        kind,
        expression: split > 0 ? text.slice(split + 1).trim() : text,
      };
    });
}

export function SourceForm({
  source,
  onClose,
  onSaved,
}: {
  source: Source | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const config = source?.config ?? {};
  const request = (config.request ?? {}) as Record<string, unknown>;
  const extractConfig = (config.extract ?? {}) as Record<string, unknown>;
  const structuredActresses =
    extractConfig.actresses && typeof extractConfig.actresses === "object"
      ? (extractConfig.actresses as Record<string, unknown>)
      : null;
  const extraExtract = Object.fromEntries(
    Object.entries(extractConfig).filter(
      ([field, value]) => typeof value !== "string" && field !== "actresses",
    ),
  );
  const [type, setType] = useState(
    typeof config.type === "string" ? config.type : "feature",
  );
  const [name, setName] = useState(source?.name ?? "");
  const [feature, setFeature] = useState(
    typeof config.feature === "string" ? config.feature : "jav_code",
  );
  const [priority, setPriority] = useState(String(source?.priority ?? 100));
  const [enabled, setEnabled] = useState(source?.enabled ?? true);
  const [url, setUrl] = useState(typeof request.url === "string" ? request.url : "");
  const [method, setMethod] = useState(
    typeof request.method === "string" ? request.method : "GET",
  );
  const [encoding, setEncoding] = useState(
    typeof request.encoding === "string" ? request.encoding : "auto",
  );
  const [rows, setRows] = useState<ExtractRow[]>(() => {
    const parsed = parseExtract(config);
    return parsed.length ? parsed : [{ field: "title", kind: "css", expression: "" }];
  });
  const [actressLinkMode, setActressLinkMode] = useState(Boolean(structuredActresses));
  const [actressSelector, setActressSelector] = useState(
    typeof structuredActresses?.selector === "string" ? structuredActresses.selector : "",
  );
  const [actressNameExpr, setActressNameExpr] = useState(
    typeof structuredActresses?.name === "string" ? structuredActresses.name : "@title",
  );
  const [actressUrlExpr, setActressUrlExpr] = useState(
    typeof structuredActresses?.url === "string" ? structuredActresses.url : "@href",
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const fieldOptions = type === "actress" ? ACTRESS_FIELDS : VIDEO_FIELDS;

  function changeType(value: string) {
    const options = value === "actress" ? ACTRESS_FIELDS : VIDEO_FIELDS;
    setType(value);
    setRows((current) =>
      current.map((row) =>
        options.some((option) => option.key === row.field)
          ? row
          : { ...row, field: options[0].key },
      ),
    );
  }

  function addRow() {
    const used = new Set(rows.map((row) => row.field));
    const next = fieldOptions.find((option) => !used.has(option.key)) ?? fieldOptions[0];
    setRows((current) => [...current, { field: next.key, kind: "css", expression: "" }]);
  }

  function updateRow(index: number, patch: Partial<ExtractRow>) {
    setRows((current) =>
      current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)),
    );
  }

  async function save() {
    setError(null);
    const cleaned = rows.filter((row) => row.field.trim() && row.expression.trim());
    if (!cleaned.length && !(type !== "actress" && actressLinkMode)) {
      setError("至少配置一个提取字段");
      return;
    }
    if (type !== "actress" && actressLinkMode) {
      if (!actressSelector.trim()) {
        setError("启用演员链接提取时，必须填写演员链接选择器");
        return;
      }
      if (!actressNameExpr.trim() || !actressUrlExpr.trim()) {
        setError("演员链接提取需要填写姓名和 URL 表达式");
        return;
      }
    }
    const rowExtract = Object.fromEntries(
      cleaned
        .filter((row) => !(actressLinkMode && row.field.trim() === "actresses"))
        .map((row) => [
          row.field.trim(),
          `${row.kind}: ${row.expression.trim()}`,
        ]),
    );
    const extract: Record<string, unknown> = { ...extraExtract, ...rowExtract };
    if (type !== "actress") {
      if (actressLinkMode) {
        extract.actresses = {
          selector: actressSelector.trim(),
          name: actressNameExpr.trim(),
          url: actressUrlExpr.trim(),
        };
      } else {
        const simpleActresses = cleaned.find((row) => row.field.trim() === "actresses");
        if (simpleActresses) {
          extract.actresses = `${simpleActresses.kind}: ${simpleActresses.expression.trim()}`;
        } else {
          delete extract.actresses;
        }
      }
    }
    const payload: Record<string, unknown> = {
      ...(source?.config ?? {}),
      name: name.trim(),
      enabled,
      priority: Number(priority),
      type,
      request: { ...request, url: url.trim(), method, encoding },
      extract,
    };
    if (type === "feature") payload.feature = feature.trim();
    else delete payload.feature;
    setSaving(true);
    try {
      if (source) {
        await api.updateSource(source.id, payload);
      } else {
        await api.createSource(payload);
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
      title={source ? `编辑源 · ${source.name}` : "新增刮削源"}
      subtitle="图形化配置常用字段；提取表达式支持 css / xpath / json / regex"
      onClose={onClose}
      wide
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
          <Label>名称</Label>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如 javbus"
            className={INPUT}
          />
        </div>
        <div>
          <Label>类型</Label>
          <select value={type} onChange={(event) => changeType(event.target.value)} className={INPUT}>
            <option value="feature">按特征查询（番号等）</option>
            <option value="query">按标题搜索（降级）</option>
            <option value="actress">演员资料源</option>
          </select>
        </div>
        {type === "feature" && (
          <div>
            <Label>使用特征</Label>
            <select value={feature} onChange={(event) => setFeature(event.target.value)} className={INPUT}>
              <option value="jav_code">番号</option>
              <option value="title">标题</option>
            </select>
          </div>
        )}
        <div>
          <Label>优先级（越小越先）</Label>
          <input
            value={priority}
            onChange={(event) => setPriority(event.target.value)}
            inputMode="numeric"
            className={INPUT}
          />
        </div>
        <div className="flex items-end pb-2">
          <label className="inline-flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              className="h-4 w-4 rounded border-zinc-300"
            />
            启用此源
          </label>
        </div>
        <div className="sm:col-span-2">
          <Label>请求 URL</Label>
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://example.com/search/{jav_code}"
            className={INPUT}
          />
        </div>
        <div>
          <Label>请求方法</Label>
          <select value={method} onChange={(event) => setMethod(event.target.value)} className={INPUT}>
            <option value="GET">GET</option>
            <option value="POST">POST</option>
          </select>
        </div>
        <div>
          <Label>响应编码</Label>
          <select
            value={encoding}
            onChange={(event) => setEncoding(event.target.value)}
            className={INPUT}
          >
            <option value="auto">自动探测</option>
            <option value="utf-8">UTF-8</option>
            <option value="gbk">GBK</option>
            <option value="euc-jp">EUC-JP</option>
            <option value="shift_jis">Shift_JIS</option>
          </select>
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">提取字段</h3>
            <p className="text-[11px] text-zinc-500">
              字段名称已使用中文；css/xpath 选择器可带 @属性，数组字段由抓取引擎处理
            </p>
            {Boolean(extraExtract.actresses) && (
              <p className="mt-1 text-[11px] text-sky-600 dark:text-sky-400">
                演员字段已配置为“姓名 + 演员页链接”模式，编辑其他字段时会保留。
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={addRow}
            className="inline-flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
          >
            <PlusIcon className="h-3.5 w-3.5" />
            添加字段
          </button>
        </div>
        <div className="space-y-2">
          {rows.map((row, index) => (
            <div key={index} className="grid grid-cols-12 gap-2">
              <select
                value={row.field}
                onChange={(event) => updateRow(index, { field: event.target.value })}
                className={`${INPUT} col-span-3`}
              >
                {fieldOptions.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.label}
                  </option>
                ))}
                {row.field && !fieldOptions.some((option) => option.key === row.field) && (
                  <option value={row.field}>{row.field}（未识别字段）</option>
                )}
              </select>
              <select
                value={row.kind}
                onChange={(event) =>
                  updateRow(index, { kind: event.target.value as ExtractRow["kind"] })
                }
                className={`${INPUT} col-span-2`}
              >
                {KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {kind}
                  </option>
                ))}
              </select>
              <input
                value={row.expression}
                onChange={(event) => updateRow(index, { expression: event.target.value })}
                placeholder=".title@text 或 //h3/text()"
                className={`${INPUT} col-span-6 font-mono text-xs`}
              />
              <button
                type="button"
                onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                className="col-span-1 flex items-center justify-center rounded-md text-zinc-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-500/10"
                aria-label="删除字段"
              >
                <TrashIcon className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {type !== "actress" && (
        <div className="mt-4 rounded-xl border border-zinc-200 p-3 dark:border-white/10">
          <label className="inline-flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-200">
            <input
              type="checkbox"
              checked={actressLinkMode}
              onChange={(event) => setActressLinkMode(event.target.checked)}
              className="h-4 w-4 rounded border-zinc-300"
            />
            演员使用“姓名 + 演员页链接”提取
          </label>
          <p className="mt-1 text-[11px] text-zinc-500">
            勾选后从视频页同时提取演员姓名和演员详情页 URL，用于后续演员资料源补全生日、国籍、三围等。
          </p>
          {actressLinkMode && (
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              <div>
                <Label>演员链接选择器</Label>
                <input
                  value={actressSelector}
                  onChange={(event) => setActressSelector(event.target.value)}
                  placeholder='xpath: //div[contains(@class,"star-box")]//a[@title]'
                  className={`${INPUT} font-mono text-xs`}
                />
              </div>
              <div>
                <Label>姓名表达式</Label>
                <input
                  value={actressNameExpr}
                  onChange={(event) => setActressNameExpr(event.target.value)}
                  placeholder="@title"
                  className={`${INPUT} font-mono text-xs`}
                />
              </div>
              <div>
                <Label>URL 表达式</Label>
                <input
                  value={actressUrlExpr}
                  onChange={(event) => setActressUrlExpr(event.target.value)}
                  placeholder="@href"
                  className={`${INPUT} font-mono text-xs`}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      )}
    </Modal>
  );
}

function Label({ children }: { children: string }) {
  return (
    <label className="mb-1 block text-[11px] font-medium text-zinc-500 dark:text-zinc-400">
      {children}
    </label>
  );
}
