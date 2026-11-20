/** 展示层纯函数测试：字段优先级、格式化与封面版本参数。 */
import { describe, expect, it } from "vitest";
import {
  censoredLabel,
  codeOf,
  coverUrl,
  durationOf,
  formatDuration,
  formatSize,
  titleOf,
  yearOf,
} from "./format";
import type { Video } from "./api";

function makeVideo(overrides: Partial<Video> = {}): Video {
  return {
    id: 1,
    filename: "SSIS-001.mp4",
    path: "/media/SSIS-001.mp4",
    features: {},
    metadata: null,
    favorite: false,
    present: true,
    duration_sec: null,
    ...overrides,
  } as Video;
}

describe("coverUrl", () => {
  it("无版本信息时不追加参数", () => {
    expect(coverUrl(1, null)).toBe("/api/videos/1/cover");
    expect(coverUrl(2, {})).toBe("/api/videos/2/cover");
  });

  it("用封面路径与刮削时间组成版本号并编码", () => {
    const url = coverUrl(3, {
      cover_local: "covers/videos/3.jpg",
      last_scraped_at: "2026-01-02T03:04:05Z",
    });
    expect(url.startsWith("/api/videos/3/cover?v=")).toBe(true);
    expect(url).toContain(encodeURIComponent("covers/videos/3.jpg|2026-01-02T03:04:05Z"));
  });

  it("只有一项版本信息时也能生成参数", () => {
    expect(coverUrl(4, { cover_local: "covers/videos/4.jpg" })).toBe(
      `/api/videos/4/cover?v=${encodeURIComponent("covers/videos/4.jpg")}`,
    );
  });
});

describe("video field helpers", () => {
  it("标题优先元数据，其次特征，最后去掉扩展名的文件名", () => {
    const withMeta = makeVideo({
      metadata: { title: "元数据标题" } as Video["metadata"],
      features: { title: "特征标题" },
    });
    expect(titleOf(withMeta)).toBe("元数据标题");
    expect(titleOf(makeVideo({ features: { title: "特征标题" } }))).toBe("特征标题");
    expect(titleOf(makeVideo())).toBe("SSIS-001");
  });

  it("番号回退到特征提取结果", () => {
    expect(codeOf(makeVideo({ features: { jav_code: "SSIS-001" } }))).toBe("SSIS-001");
    expect(codeOf(makeVideo())).toBe("");
  });

  it("年份与时长分别回退到元数据", () => {
    expect(yearOf(makeVideo())).toBeNull();
    expect(yearOf(makeVideo({ metadata: { year: 2024 } as Video["metadata"] }))).toBe(2024);
    expect(durationOf(makeVideo({ metadata: { runtime_sec: 5400 } as Video["metadata"] }))).toBe(
      5400,
    );
    expect(durationOf(makeVideo({ duration_sec: 120 }))).toBe(120);
  });
});

describe("formatting", () => {
  it("文件大小按 1024 进制，0 显示破折号", () => {
    expect(formatSize(null)).toBe("—");
    expect(formatSize(0)).toBe("—");
    expect(formatSize(1536)).toBe("1.5 KB");
    expect(formatSize(1024 * 1024 * 1024 * 2)).toBe("2.0 GB");
  });

  it("时长超过一小时带小时段", () => {
    expect(formatDuration(null)).toBeNull();
    expect(formatDuration(65)).toBe("1:05");
    expect(formatDuration(3661)).toBe("1:01:01");
  });

  it("有码/无码文案", () => {
    expect(censoredLabel("censored")).toBe("有码");
    expect(censoredLabel("uncensored")).toBe("无码");
    expect(censoredLabel(null)).toBeNull();
  });
});
