# 静态识别结果审核台规范（兼容模式）

## 产品形态

识别前的配对核对统一在本次任务的正式工作台 `add` 页，见 [配对确认流程](task-protocol.md#配对确认识别前门槛)。本规范仅描述识别完成后的兼容审核台。它围绕一个 `task_key` 工作，只审核识别结果的后续处理，不能改变配对。页面由以下部分组成：

1. 顶部四列计数：推荐收藏、需复核、普通记录、未识别，并显示各组已审核进度。
2. 默认双栏审核台：左侧候选队列，右侧正反面证据、来源字段、识别字段、冲突依据和用户决定。
3. “全部记录”表格：筛选、排序、逐条选择、选择当前筛选结果和批量决定。

批量操作必须先展示影响数量、覆盖已有决定数、警告项和阻断项，再由用户确认。批量操作仍为每条 item 产生独立决定事件，共享 `batch_action_id`。

## 视觉方向

- 使用暖白、纸张灰、炭黑、松绿色、赭黄色和砖红色；不使用蓝紫渐变、发光卡片或装饰性 emoji。
- 强调信息密度与实物证据，卡片只表达边界，不做无意义悬浮层叠。
- 正反面图片保持同等权重；缺图显示明确空态，禁止复制另一面填充。
- 字体和间距接近编辑型桌面工具，默认适配电脑宽屏，同时在窄屏降为单列。
- 系统推荐、服务端事实和“我的决定”使用不同区域与措辞，避免用户把建议误认为已执行状态。

可复用模板位于 `assets/review-workbench/`。不得把某次任务的真实硬币数据写进模板。

## 数据生成

先校验任务包，再生成识别结果审核台：

```bash
python3 <skill-dir>/scripts/build_review_workbench.py --task-key <task_key>
```

生成内容：

```text
~/.heribase/user-tasks/<task_key>/derived/
├── review-dataset.json
└── review-workbench/
    ├── index.html
    ├── review-handoff.js
    └── review-data.js
```

`review-dataset.json` 必须符合 `assets/schemas/review-dataset.schema.json`。页面图片只引用审核台目录内复制的任务包证据。

## 本地启动与 WebMCP

`file://` 不能稳定满足 origin isolation。使用只读本地服务：

```bash
python3 <skill-dir>/scripts/serve_review_workbench.py --task-key <task_key> --port 0
```

服务只绑定 `127.0.0.1`，只响应 GET，设置 `Origin-Agent-Cluster: ?1`、`Permissions-Policy: tools=(self)`、`nosniff` 和 `no-store`。识别审核台注册两个无输入、只读 WebMCP 工具：

- `get_review_decisions`
- `get_review_decision_summary`

该静态服务不接收写请求，因此不需要 CSRF 写入令牌。未来若增加浏览器直写任务包的 API，必须另行实现 origin allowlist、随机会话 CSRF、typed payload、revision/item version 校验和授权计划闸门；不能把静态服务扩展为任意文件或 CLI 代理。

## 页面状态与正式决定

页面按 `task_key + dataset_fingerprint` 隔离 `localStorage`，它仅用于刷新恢复。识别台的正式决定进入任务包前必须执行：

```bash
python3 <task-package-skill>/scripts/task_operations.py import-review \
  --task-key <task_key> \
  --expected-revision <revision> \
  --file <审核决定.json> \
  --mode replace
```

脚本验证 v2 Schema 与数据集指纹，复制导入原件，并把每项决定转换为哈希链事件。页面不能直接调用 HeriBase CLI，也不能把“本地待收藏”解释为已收藏。

## 稳定输出要求

- 每次基础数据变化后重新生成审核台；旧导出包因指纹不符必须拒绝。
- 页面记录 ID 必须使用永久 `local_id`，不能回退到 `candidate_07` 等会话 ID。
- 识别详情展示 `identify_uri`、`user_uniq_uri`，收藏成功后展示 `collection_uri`。
- 盒标字段与服务端识别字段分区展示；前者显示证据、原文与置信度，后者显示真实响应。认证编号或 KM 编号不能被渲染为已验证的服务端身份。
- 用户完成审核后，先导入任务包并报告三类决定计数，再生成收藏计划；不得跳过计划确认闸门。
