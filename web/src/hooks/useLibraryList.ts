/**
 * 海报墙/演员列表的数据加载。
 * 按当前视图与筛选条件请求分页数据，并在切换视图后丢弃过期响应；
 * 组件只拿结果，失败信息通过 onError 交给上层显示。
 */
import { useEffect, useState } from "react";
import { api, type Actress, type Video } from "../api";
import { errorMessage } from "../format";

export function useLibraryList(params: {
  isVideoView: boolean;
  page: number;
  pageSize: number;
  query: string;
  videoSort: string;
  actressSort: string;
  randomSeed: number;
  /** 收藏视图：只返回已收藏项。 */
  favorite: boolean;
  /** 只显示待补全的视频。 */
  incompleteOnly: boolean;
  /** 只显示未刮削的视频。 */
  unscrapedOnly: boolean;
  filterActressId?: number;
  filterTag?: string;
  filterSeries?: string;
  /** Video category; undefined 表示全部。 */
  category?: string;
  refreshKey: number;
  onError: (message: string) => void;
}) {
  const {
    isVideoView,
    page,
    pageSize,
    query,
    videoSort,
    actressSort,
    randomSeed,
    favorite,
    incompleteOnly,
    unscrapedOnly,
    filterActressId,
    filterTag,
    filterSeries,
    category,
    refreshKey,
    onError,
  } = params;
  const [videos, setVideos] = useState<Video[]>([]);
  const [actresses, setActresses] = useState<Actress[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  // 按当前视图加载视频或演员列表；清理函数用于丢弃切换视图后返回的旧响应。
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const request = isVideoView
      ? api
          .listVideos({
            page,
            pageSize,
            q: query || undefined,
            sort: videoSort,
            seed: videoSort === "random" ? randomSeed : undefined,
            favorite: favorite ? true : undefined,
            complete: incompleteOnly ? false : undefined,
            scraped: unscrapedOnly ? false : undefined,
            actressId: filterActressId,
            tag: filterTag,
            series: filterSeries,
            category,
          })
          .then((data) => {
            if (cancelled) return;
            setVideos(data.items);
            setTotal(data.total);
          })
      : api
          .listActresses({
            page,
            pageSize,
            q: query || undefined,
            sort: actressSort,
            favorite: favorite ? true : undefined,
          })
          .then((data) => {
            if (cancelled) return;
            setActresses(data.items);
            setTotal(data.total);
          });
    request
      .catch((error) => {
        if (!cancelled) onError(errorMessage(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    isVideoView,
    page,
    pageSize,
    query,
    videoSort,
    actressSort,
    randomSeed,
    favorite,
    incompleteOnly,
    unscrapedOnly,
    filterActressId,
    filterTag,
    filterSeries,
    category,
    refreshKey,
    onError,
  ]);

  return { videos, actresses, total, loading, setVideos, setActresses };
}
