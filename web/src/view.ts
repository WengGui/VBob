/**
 * 主界面共享的视图类型与列表常量。
 * 放在独立模块里，供 App 与拆出的侧栏/列表 hook 共用，避免循环引用。
 */

/** 主视图：视频/演员，以及各自的收藏视图。 */
export type View = "videos" | "actresses" | "favorites-videos" | "favorites-actresses";

/** 单页数量，视频与演员列表共用。 */
export const PAGE_SIZE = 60;

/** 排序值直接使用后端字段名，作为下拉框的 value 传给接口。 */
export const VIDEO_SORTS = [
  ["updated_at", "加入时间：近→远"],
  ["filename", "文件名"],
  ["year", "年份"],
  ["code", "番号"],
  ["random", "随机顺序"],
] as const;

export const ACTRESS_SORTS = [
  ["video_count", "作品数：多→少"],
  ["name", "姓名"],
  ["birth_date", "出生日期"],
] as const;

/** 随机排序种子，避开 0，保证后端乘法散列能打乱顺序。 */
export function newRandomSeed(): number {
  return Math.floor(Math.random() * 2_147_483_646) + 1;
}

/** 侧栏标题与页面标题使用同一份映射。 */
export const VIEW_TITLES: Record<View, string> = {
  videos: "视频",
  actresses: "演员",
  "favorites-videos": "收藏的视频",
  "favorites-actresses": "收藏的演员",
};
