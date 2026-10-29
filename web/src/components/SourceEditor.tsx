import { useState } from "react";
import { parse, stringify } from "yaml";
import { api, type Source } from "../api";
import { errorMessage } from "../format";
import { CloseIcon, DatabaseIcon } from "./Icons";

const TEMPLATE = `# VBob 刮削源配置
name: javbus
enabled: true
priority: 10
type: feature        # feature | query
feature: jav_code    # feature 类型必填

request:
  url: "https://www.javbus.com/{jav_code}"
  method: GET
  headers:
    User-Agent: "Mozilla/5.0 ..."

extract:
  title: "xpath: //h3/text()"
  cover_url: "css: .bigImage img@src"
  release_date: "xpath: //span[contains(text(),'發行日期')]/following-sibling::span/text()"

validators:
  - field: title
    required: true
`;

export function SourceEditor({
  source,
  onClose,
  onSaved,
}: {
  source: Source | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [text, setText] = useState(source ? stringify(source.config) : TEMPLATE);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    let parsed: unknown;
    try {
      parsed = parse(text);
    } catch (parseError) {
      setError(`YAML 解析失败：${errorMessage(parseError)}`);
      return;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      setError("配置必须是一个 YAML 对象");
      return;
    }
    setSaving(true);
    try {
      const config = parsed as Record<string, unknown>;
      if (source) {
        await api.updateSource(source.id, config);
      } else {
        await api.createSource(config);
      }
      onSaved();
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm dark:bg-black/70"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-white/10 dark:bg-zinc-950"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-100 px-5 py-3.5 dark:border-white/10">
          <div className="flex items-center gap-2">
            <DatabaseIcon className="h-5 w-5 text-sky-500" />
            <div>
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                {source ? `编辑源 · ${source.name}` : "新增刮削源"}
              </h2>
              <p className="text-[11px] text-zinc-500">
                YAML 配置，保存后会校验并立即生效于后续刮削
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-white/5 dark:hover:text-zinc-200"
            aria-label="关闭"
          >
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            spellCheck={false}
            className="h-[52vh] w-full resize-none rounded-xl border border-zinc-200 bg-zinc-50 p-4 font-mono text-xs leading-6 text-zinc-800 outline-none focus:border-sky-400 dark:border-white/10 dark:bg-zinc-900 dark:text-zinc-200"
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-zinc-500">
            <span>
              提取前缀支持 <code className="rounded bg-zinc-100 px-1 dark:bg-white/10">css:</code>{" "}
              <code className="rounded bg-zinc-100 px-1 dark:bg-white/10">xpath:</code>{" "}
              <code className="rounded bg-zinc-100 px-1 dark:bg-white/10">json:</code>{" "}
              <code className="rounded bg-zinc-100 px-1 dark:bg-white/10">regex:</code>
            </span>
            {!source && (
              <button
                type="button"
                onClick={() => setText(TEMPLATE)}
                className="text-sky-600 hover:underline dark:text-sky-400"
              >
                填入示例模板
              </button>
            )}
          </div>
          {error && (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
              {error}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-zinc-100 px-5 py-3 dark:border-white/10">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-zinc-200 px-4 py-2 text-sm text-zinc-600 transition hover:bg-zinc-100 dark:border-white/10 dark:text-zinc-300 dark:hover:bg-white/5"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving}
            className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? "保存中…" : "保存配置"}
          </button>
        </div>
      </div>
    </div>
  );
}
