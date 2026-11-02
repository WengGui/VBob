/**
 * 通用弹窗容器：统一遮罩、标题、可滚动内容和底部操作区。
 * 点击遮罩关闭；内容区阻止冒泡，避免在表单内点击时误触关闭。
 */
import type { ReactNode } from "react";
import { CloseIcon } from "./Icons";

/** wide 用于字段较多的表单；footer 为空时隐藏底部操作栏；headerActions 放标题右侧操作按钮。 */
export function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
  headerActions,
  wide = false,
  tall = false,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  headerActions?: ReactNode;
  wide?: boolean;
  /** 固定高度（详情弹窗用），避免内容多少导致弹窗大小跳动。 */
  tall?: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm dark:bg-black/70"
      onClick={onClose}
      role="presentation"
    >
      {/* 阻止内容区点击冒泡到遮罩，确保输入和按钮操作不会关闭弹窗。 */}
      <div
        className={`flex w-full flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-white/10 dark:bg-zinc-950 ${
          tall ? "h-[86vh]" : "max-h-[92vh]"
        } ${wide ? "max-w-5xl" : "max-w-3xl"}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-zinc-100 px-5 py-3.5 dark:border-white/10">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[11px] text-zinc-500">{subtitle}</p>}
          </div>
          <div className="flex items-center gap-1">
            {headerActions}
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-white/5 dark:hover:text-zinc-200"
              aria-label="关闭"
            >
              <CloseIcon className="h-5 w-5" />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-zinc-100 px-5 py-3 dark:border-white/10">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
