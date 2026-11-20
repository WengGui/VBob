/** 当前筛选条件的小标签，点击 × 单独清除。 */
export function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-sky-200 bg-white px-2 py-0.5 text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300">
      {label}
      <button
        type="button"
        onClick={onClear}
        className="rounded px-0.5 text-sky-500 hover:bg-sky-100 hover:text-sky-700 dark:hover:bg-sky-500/20"
        aria-label={`清除筛选：${label}`}
      >
        ×
      </button>
    </span>
  );
}
