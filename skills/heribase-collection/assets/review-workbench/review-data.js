(function attachEmptyHeriBaseReviewData(global) {
  "use strict";

  // 占位数据只用于验证模板可以独立打开。正式页面由 build_review_workbench.py
  // 从任务包生成同名文件，并使用 task_key + dataset fingerprint 隔离审核缓存。
  global.COIN_REVIEW_DATA = {
    records: [],
    statusCounts: { collect: 0, review: 0, normal: 0, unidentified: 0 },
    buildMeta: {
      taskKey: "template-preview",
      generatedAt: "1970-01-01T00:00:00.000Z",
      datasetFingerprint: "template-preview",
      totalRecordCount: 0,
    },
  };
}(globalThis));
