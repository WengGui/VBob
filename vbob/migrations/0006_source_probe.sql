-- 源的连通性检测结果：保存最近一次探测的信号等级、耗时与状态码。
-- 只保留一行 JSON，便于设置页重新打开时直接显示上次的信号条。
ALTER TABLE sources ADD COLUMN last_test_result_json TEXT;
