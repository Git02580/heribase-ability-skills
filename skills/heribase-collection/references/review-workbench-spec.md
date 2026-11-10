# 可复用硬币审核台规范

## 产品形态

审核台围绕一个 `task_key` 工作，不承载任务管理或任意服务器写入。它分为两个前后独立的台面：识别前的“配对审核台”只决定照片/表格证据是否属于同一实物；识别后的“识别审核台”只决定识别结果的后续处理，不得改变配对。默认页面采用已确认的组合：

1. 顶部四列计数：推荐收藏、需复核、普通记录、未识别，并显示各组已审核进度。
2. 默认双栏审核台：左侧候选队列，右侧正反面证据、来源字段、识别字段、冲突依据和用户决定。
3. “全部记录”表格：筛选、排序、逐条选择、选择当前筛选结果和批量决定。

批量操作必须先展示影响数量、覆盖已有决定数、警告项和阻断项，再由用户确认。批量操作仍为每条 item 产生独立决定事件，共享 `batch_action_id`。

配对审核台的批量范围更窄：支持勾选任意候选、按“需人工确认”或“自动就绪”状态加入选择，以及批量“确认配对”“标记待补图”“排除”。“确认配对”只处理已有方向明确正反面证据的记录，不能自动分配或覆盖照片方向；拆分、合并与方向调整只能逐条完成。批量草稿只可存入 `localStorage`，交接包中的每条决定保留共同的可选 `batchActionId`，再经 `import-pairing` 逐条写入任务包。

## 视觉方向

- 使用暖白、纸张灰、炭黑、松绿色、赭黄色和砖红色；不使用蓝紫渐变、发光卡片或装饰性 emoji。
- 强调信息密度与实物证据，卡片只表达边界，不做无意义悬浮层叠。
- 正反面图片保持同等权重；缺图显示明确空态，禁止复制另一面填充。
- 字体和间距接近编辑型桌面工具，默认适配电脑宽屏，同时在窄屏降为单列。
- 系统推荐、服务端事实和“我的决定”使用不同区域与措辞，避免用户把建议误认为已执行状态。

可复用模板位于 `assets/review-workbench/` 和 `assets/pairing-workbench/`。不得把某次任务的真实硬币数据写进模板。

## 数据生成

先确保任务包校验通过。识别前的配对审核台运行：

```bash
python3 <skill-dir>/scripts/build_pairing_workbench.py --task-key <task_key>
```

它生成 `derived/pairing-workbench/`、配对数据集与证据副本。每条记录必须带来源类型；表格候选还必须带行定位、原 URL 和正反面下载状态。盒子币候选必须展示标签证据、评级机构、认证编号、等级、附加标记、币种字段、KM 编号、条码、字段置信度和冲突状态；字段必须明确标作“标签读取线索”。仅字段、下载失败或缺图的表格候选应显示为异常，不能伪装为可配对的图片证据。

识别后的审核台运行：

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

`review-dataset.json` 必须符合 `assets/schemas/review-dataset.schema.json`。两个页面的图片只引用各自工作台目录内复制的任务包证据，不直接依赖原目录、`../../inputs` 相对路径或远程 URL。

当散图或表格配对台被触发时，所有盒子币都在同一确认列表中显示其标签读取线索；当没有其他配对问题时，页面生成器必须先让用户选择是否审核盒标读取。用户选择跳过只允许高置信、证据完整的线索进入首次识别确认卡，不能直接发起后端查询。

## 本地启动与 WebMCP

`file://` 不能稳定满足 origin isolation。使用只读本地服务：

```bash
python3 <skill-dir>/scripts/serve_review_workbench.py --task-key <task_key> --port 0
```

服务只绑定 `127.0.0.1`，只响应 GET，设置 `Origin-Agent-Cluster: ?1`、`Permissions-Policy: tools=(self)`、`nosniff` 和 `no-store`。识别审核台注册两个无输入、只读 WebMCP 工具：

- `get_review_decisions`
- `get_review_decision_summary`

配对审核台注册一个无输入、只读 WebMCP 工具：

- `get_pending_pairing_decisions`

它返回当前浏览器草稿构成的 schema v1 配对交接包（含 `taskKey`、`datasetFingerprint`、逐项 `decisions` 与可选 `batchActionId`），不读写任务包、不会访问 CLI，也不把 `localStorage` 直接视为正式决定。助手在用户完成审核后必须优先调用它；取得结果后仍要用 `import-pairing` 校验并持久化。只有浏览器没有该工具、注册失败或调用失败时，才告知用户导出 JSON。两条交接通路必须生成相同的配对包和数据集指纹。

该静态服务不接收写请求，因此不需要 CSRF 写入令牌。未来若增加浏览器直写任务包的 API，必须另行实现 origin allowlist、随机会话 CSRF、typed payload、revision/item version 校验和授权计划闸门；不能把静态服务扩展为任意文件或 CLI 代理。

## 页面状态与正式决定

页面按 `task_key + dataset_fingerprint` 隔离 `localStorage`，它仅用于刷新恢复。配对台从 WebMCP 或 JSON 得到交接包后，正式决定进入任务包前必须执行：

```bash
python3 <task-package-skill>/scripts/task_operations.py import-pairing \
  --task-key <task_key> \
  --expected-revision <revision> \
  --file <配对决定.json>
```

导入会校验表格/散图来源分配、数据集指纹和每项版本，并将决定写为哈希链事件；配对变化会使旧识别、审核和收藏计划过期。

识别台的正式决定进入任务包前必须执行：

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
