/**
 * 侧栏导航按钮。
 * 窄屏只显示图标；indent 用于收藏/分类子项缩进，count 为右侧数量角标，
 * expanded 非 undefined 时表示可折叠项并显示旋转箭头。
 */
import type { ReactNode } from "react";
import { ChevronDownIcon } from "./Icons";

export function NavButton({
  icon,
  label,
  active,
  onClick,
  indent = false,
  count,
  expanded,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  indent?: boolean;
  /** 右侧数量角标；undefined 表示不显示。 */
  count?: number;
  /** 可折叠项传入当前展开状态，右侧显示旋转箭头；undefined 表示不可折叠。 */
  expanded?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={`flex w-full items-center gap-3 rounded-lg py-2 text-sm transition ${
        indent ? "pl-6 pr-3" : "px-3"
      } ${
        active
          ? "bg-sky-50 font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-300"
          : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-white/5"
      }`}
    >
      {icon}
      <span className="hidden min-w-0 flex-1 truncate text-left lg:inline">{label}</span>
      {count !== undefined && (
        <span className="hidden shrink-0 rounded bg-zinc-100 px-1.5 text-[10px] text-zinc-500 lg:inline dark:bg-white/5 dark:text-zinc-400">
          {count}
        </span>
      )}
      {expanded !== undefined && (
        <ChevronDownIcon
          className={`hidden h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform lg:block ${
            expanded ? "" : "-rotate-90"
          }`}
        />
      )}
    </button>
  );
}
