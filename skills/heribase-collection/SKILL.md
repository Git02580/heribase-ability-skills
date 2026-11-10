---
name: heribase-collection
description: Use whenever a user wants to organize coin photos, graded slabs, spreadsheet coin rows or embedded images; create or resume a persistent HeriBase coin task; generate or use the desktop coin review workbench; import WebMCP/JSON review decisions; identify selected coins; or add, edit, or cancel explicitly confirmed HeriBase collection records. This is the user-facing workflow skill for the complete input → organization → identification → review → confirmed collection flow.
compatibility: Python 3.9+; a desktop browser; companion heribase-workspace, heribase-task-package and heribase-cli skills; WebMCP optional because JSON export is always supported.
metadata:
  short-description: 本地硬币资料整理、识别与收藏
---

# HeriBase Collection

将用户提供的散图、目录、XLSX 及装盒评级币照片整理成可恢复的审核任务，自动匹配有充分依据的正反面，再经独立确认完成选定钱币的识别和可选收藏。用户只使用“添加钱币”这一入口，不先选择单枚、批量或手动模式；上传数量和资料类型由 Agent 判断。批量上传、自动配对、批量审核和批量识别继续保留。对用户描述正在处理的钱币、照片和结果，不暴露 Skill、Tool、内部 ID 或内部阶段名称。

`heribase-task-package` 是本地任务数据的唯一契约来源；开始整理、恢复任务、持久化识别/审核/收藏结果或准备线上写入前，必须先阅读 [HeriBase 任务包 Skill](../heribase-task-package/SKILL.md) 及对应参考。`heribase-cli` 是唯一的 HeriBase 命令、鉴权和 JSON 契约来源；执行 CLI 前必须阅读 [HeriBase CLI Skill](../heribase-cli/SKILL.md) 及相应的 [命令参考](../heribase-cli/references/command-reference.md)。不得直接请求 HeriBase 内部 HTTP API。

## 默认入口：在当前对话办理

先阅读 [工作空间 Skill](../heribase-workspace/SKILL.md)。用户给出照片、目录或需要继续的对象后，由 Agent 整理资料、查询状态并连续调用受控能力；不要先打开管理首页，让用户创建任务、建立候选、生成计划或选择宿主会话。任务、原件和执行进度仍按原契约持久化。

没有本次资料时，只请用户发送照片或需要处理的目录；不要使用当前工作目录、下载目录或其他历史任务代替。用户明确说“继续刚才那枚”时，复用当前对话已经绑定的任务键，先读最新状态；不把全局最近任务自动认作当前对象。无法唯一定位时只问需要继续哪一枚。

### 统一用户流程：给资料 → 自动整理 → 确认识别 → 核对后收藏

1. **给照片。** 先查看本次图片，按下方全量图片配对方法判断同币归属和方向，不要求用户预先命名或手工分好正反面。已有充分依据时由 Agent 完成匹配；只有缺图、方向不明或竞争配对无法消除时才展示具体疑问，不能依文件先后强行指定。用户已明确给出的正反面可通过同级 `heribase-workspace/scripts/connector.py prepare --obverse <正面绝对路径> --reverse <反面绝对路径>` 一次归档并建立配对；名称自动产生，无需用户填写。自动推定的配对仍遵守原有置信度和审核契约，不能用此快捷命令伪装成人工确认。`prepare` 不上传到远端，也不识别或收藏。
2. **开始识别。** 用 `connector.py identification-plan --task-key <key>` 获取当前精确范围与账户绑定。展示正反面、图片将上传到 HeriBase、服务实际返回的费用/额度，以及当前未知项；在用户已授权这些对象和实际动作后，才用 `identify --confirmed` 提交该次预览的 revision、hash 和稳定 commandId。已有同范围明确授权不重复询问。
3. **核对并保存。** 用 `connector.py status --task-key <key>` 读取真实结果，展示照片、可读币名、主要字段及未解决差异。用户明确接受当前结果并说“加入收藏”时，用 `collect --confirmed` 传当前 revision、localId、snapshotId 与稳定 commandId。该工具把本次用户的采纳决定、计划校验和收藏执行串起来；不要求用户先标记待收藏、再生成计划、再重复确认同一范围。
4. **报告结果。** 查询真实终态，成功须有真实收藏关联。运行中显示进度；结果未知先核验，不自动新建意图或重复上传/写入。不能把本地归档、识别成功或请求入队当成已收藏。

完整命令和字段见 [对话办理工具](../heribase-workspace/references/connector-flow.md)。这些参数只供 Agent 使用，不让用户输入任务键、摘要、commandId 或指定唤起口令。

### 同一入口中的查看与纠错

统一可视页用 `workspace.py start --no-default-browser --page add --task-key <key>`；用户明确要求打开工具时，无任务键则打开 `add`。Codex 中将返回 URL 交给内置浏览器，不调用系统浏览器；URL 含本机连接凭据，不粘贴进聊天、截图或业务记录。

照片、目录、表格和盒子币使用同一个“添加钱币”入口，不能拆成多个用户模式，也不能要求用户逐枚手选正反面。收到一批资料就按下方 `organize_batch` 和 [全量图片配对方法](references/pairing-method.md) 完整归档、整批比较、自动匹配，再统一展示匹配摘要与疑问项。保留高置信自动就绪、低置信候选建议、EXIF 辅助线索、用户纠错、批量审核与选定范围识别。Agent 自动处理有充分依据的条目，只把缺图、方向不明、重复或识别差异交给用户判断。网页 `add` 页使用同一个资料区接收一份或多份照片及表格；旧 `import` 链接兼容转到 `add`，不再形成独立入口。资料已经归档时复用该任务及来源，不再次建任务或重复导入。浏览器归档资料后，由本机工作空间自动启动受限 Codex 整理 worker，不再要求用户返回聊天触发。worker 使用当前已登录 Codex 的额度，按全量方法输出配对 JSON，由后端做版本、来源覆盖和像素区域核验并通过任务包工具保存；它不会唤醒或冒充当前聊天，也不执行 HeriBase 线上识别、收藏或用户审核决定。批次结束立即开始，页面关闭导致批次结束通知丢失时，已保存资料在静默期后继续；整理中断或连接/额度失败显示具体原因，可原页重试。复杂核对可按需打开 `pairing` 或 `review` 页；不要求用户走完七阶段管理界面。批次记录继续保留。

网页与聊天读取同一份任务事实。用户从辅助页返回说“改好了，继续”时，先读取该任务最新 revision 和结果再办下一步；默认不创建 heartbeat，也不要求用户发送 inbox 指令。旧协作队列只用于显式的高级交办，不能声称它会原生唤醒已停止的 Agent。

## 安装与环境依赖

本 Skill 需要 Python 3.9+、桌面浏览器，以及可用的 `heribase-task-package` 和 `heribase-cli`。基础环境、CLI 安装和初始化见 [统一安装说明](../heribase-cli/references/installation.md)。

## 不可违反的边界

- 不存在 `heribase batch organize`；批量整理只是在本地进行的识别前准备，不是服务端批量识别。
- 创建任务时即把资料复制进 `~/.heribase/user-tasks/<task_key>/`；首次确认前不得上传、识别或写入收藏。
- `local_id` 是永久本地记录 ID，但不是服务端资产 ID。`identify_uri`、`user_uniq_uri` 和 `collection_uri` 只能使用可追溯的真实服务响应。
- 每项原子 CLI 命令都使用 `--json`，只解析 stdout 中唯一的 JSON 文档。
- CLI stdout 原始 JSON 与规范化字段必须双层保存；raw 响应不可变，空缺服务字段用 `null`。
- 持久化工作台以服务端任务包为事实；旧兼容页的 `localStorage` 只是草稿缓存。单项或批量审核都必须落为逐项追加事件。
- 线上收藏、修改或取消必须经过当前有效的 `collection/plan.json`；用户确认绑定计划摘要，范围改变即重新确认。
- 费用、额度、权益、预计耗时或服务端状态未由 CLI/API 明确返回时，标记为“当前未知”；不得猜测或承诺。

## 任务流程

批量与兼容模式的阶段及确认模板见 [任务协议](references/task-protocol.md)。以下是 Agent 内部步骤，不要求用户逐页操作；单枚优先使用上面的对话办理入口：

1. **`create_or_resume_task` — 创建或恢复任务。** 新任务使用 `heribase-task-package` 创建 `YYYYMMDD-HHmm-<slug>` 目录；已有任务先校验完整性、恢复状态和 revision。不得把旧页面状态当作任务事实。
2. **`organize_batch` — 本地预整理。** 先完整归档散图、目录、XLSX（字段或嵌入图片）、远程表格图片和评级盒照片，再阅读 [全量图片配对方法](references/pairing-method.md)，建立来源索引与稳定 `local_id`。归档后运行 `scripts/analyze_image_metadata.py --task-key <task_key>` 生成 EXIF 候选报告；脚本会先使用当前 Python 环境，若缺少 Pillow 会主动尝试用该解释器的 pip 安装，安装成功后继续分析。若安装失败，在报告中记录原因并跳过可选 EXIF 步骤，不中断正常视觉配对。图片本身若没有 EXIF，不能通过安装软件恢复已缺失的信息；仍分析像素尺寸并继续视觉配对。必须盘点整批资料后再分组，先记录逐图可见特征，再对所有未确认图片进行全局候选比较；不要按文件顺序逐张即时定组。把稀有币种/版别兼容性、独特背景/环境与 EXIF 多信号组合用于召回和排序，然后在原图上复核；单独的设备、时间、位置、尺寸或背景线索不能确立配对。候选应覆盖未配对来源与待确认记录，保留排名、关系类型、支持证据、冲突证据与置信度，并在配对审核台展示，确保用户能看到较低置信度但值得复核的候选。每个来源最多进入一个活动配对；方向置信度与“是否同一枚”分别判断。高置信自动就绪门槛保持 `0.85`，中低置信候选可进入人工审核，绝不为了提高配对数量降低门槛或强行合并。表格的每一行都必须形成可追溯的 `table-*` 候选：保留工作表/行号、原字段和正反面 URL；逐张获取其远程图片并作为独立来源归档。下载失败、缺 URL 或无法定位的图片必须记录到受影响候选的警告和任务异常中，不能把“仅有表格字段”误报为“图片已处理”。单图盒子币可形成独立 `graded_slab` 候选；多模态标签分析只生成带证据和置信度的来源声明，供后端定位使用。
3. **`review_pairing` — 配对确认。** 任一候选的配对置信度低于 `0.85`、缺面、证据冲突、图片重复引用或带 `pairing_needs_confirmation` 时，先展示需要用户判断的具体照片；需要批量看图时再打开当前任务的 `pairing` 页面。用户可确认、拆分、合并、标记待补图或排除；正式决定只能经 `task_operations.py import-pairing` 写入。配对台提供候选勾选、“全选需确认”“全选自动就绪”和清空选择；只允许批量执行确认配对、标记待补图或排除。批量确认配对仅适用于已具备方向明确的正反面证据，不能重写用户已选的照片方向；拆分、合并和照片方向调整必须逐条处理。执行批量草稿前展示影响条目数、覆盖已有草稿数及被跳过的阻断项；每条受影响候选仍形成独立决定，并共享 `batchActionId`。审核结束后优先通过页面的只读 WebMCP 工具 `get_pending_pairing_decisions` 读取当前草稿；仅在工具不存在、注册失败或读取失败时，才提示用户导出同结构 JSON 作为降级交接。盒子正反面仍需配对，但优先使用可见的评级机构、认证编号、等级和条码作为强线索；不得只因年份或币名相近而合并。若散图或表格有任何配对审核项，台面还必须列出所有盒子币的标签提取摘要供一并确认。若全部候选高置信且无冲突，存在盒子币时询问用户是否先审核标签识别；用户不要求时才跳过页面，并在首次识别确认卡中展示自动配对和标签线索摘要。
4. **`identify_and_value` — 单枚识别与审核。** 仅处理用户首次确认选定、且证据满足 CLI 要求的记录。逐枚保存识别尝试、原始响应和规范化服务身份；根据实际证据遵从 [结果分组与排序](references/result-classification.md) 生成审核数据。单面、古钱币、低质量图片或仅有评级盒的记录保留待补图/复核，不能伪造另一面。对已确认候选执行上传、识别与后续收藏时，均追加同一对仅本地参数 `--batch-id <task_key>` 与 `--candidate-id <safe_candidate_key>`；后者是从 `local_id` 派生的仅含字母、数字、`_`、`-` 的稳定键，不能直接使用包含 `:` 的 `local_id`。
5. **`review_in_workbench` — 识别审核决定。** 识别结果已保存后，在当前对话或单枚添加页展示可读结果；需要复杂对照或批量审核时再打开 `review` 页面。高级审核台提供双栏审核、顶部分组计数、全部记录视图和分组全选。每项决定逐条写入任务包；批量决定共享批次 ID。此阶段不得改变照片归属或配对。
6. **`prepare_collection` — 计划、确认与写入。** 依据最新审核事件生成带摘要的 `collection/plan.json`，展示精确范围后获得第二次确认。把确认绑定到当前 `payload_sha256`；紧邻第一条线上写入前必须运行 `task_operations.py preflight-plan`，再次校验摘要、dataset revision、item version、决定和身份冲突。只有 preflight 返回 `online_writes_allowed: true` 才逐条调用 CLI，并把实际 `collection_uri`、raw 响应和尝试事件写回任务包。

遇到失败、取消、会话中断或用户要求重试时，先阅读 [失败、取消与恢复](references/recovery-and-confirmation.md)。该文档也定义未来 API 提供确认令牌后的迁移边界；在 API 和 CLI 实际支持前，绝不虚构 `confirmationId`、`prepare` 或 `confirm` 命令。

## 本地预整理

建立任务包中的规范化记录，每个候选项至少包含：

```text
local_id: 20260828-1034-batch-flat:local-07
state: awaiting_precheck
type: raw_coin | graded_slab | single_side | ambiguous
front/back: 本地来源引用（可为空）
source: 文件、工作表和行号
pairConfidence: high | medium | low
duplicateGroup: 可为空
extractedFacts: 仅限可读到的证书号、等级或表格字段
warnings: 缺面、冲突、模糊、疑似重复等
```

- 为每张输入建立来源索引：任务包内副本、原路径或 URL、SHA-256；XLSX 的工作表、行、单元格和嵌入图片位置；可可靠读取的文字。
- 表格按行建立候选，不因表格行与散图看似相似而自动合并。每个含远程图 URL 的单元格都要尝试获取并建立带父表格来源、工作表/行/列定位和原 URL 的独立 `remote_image` 来源；下载失败也要保留 URL、失败原因与时间。
- 只有字段而没有成功归档图片的表格候选，标为 `source_incomplete` / 待补图，默认不进入识别范围；它们仍必须出现在输入摘要、异常清单和配对摘要中。
- 将图片分类为正面、反面、评级盒/证书标签、细节图或无法判断；单图同时含硬币和标签时归为 `graded_slab`，并保留其作为硬币与标签的同一证据。模糊评级文字不能成为事实。
- 对清晰盒标使用多模态分析提取机构（PCGS、NGC 等）、认证编号、等级、附加标记、年份、铸厂、面额、币名、KM（Krause）编号、条码及可见其他属性。每个字段必须保存原文、规范化值、置信度、证据来源和可见区域；读不清即留空并标待复核，不能补全编号或 KM。
- 盒标来源声明可作为后端识别/查询的优先定位线索，但服务端 `identify_uri`、`user_uniq_uri` 等才是最终身份。盒标与裸币图像推测冲突时保留两者并触发审核。
- 只在证据充分时配对或去重；不确定项应进入待复核，不能强行合并。
- 无法可靠提取或关联 XLSX 图片时，列出受影响的行和图片，请用户补充或指定关联方式。

任务状态持久化在任务包中，可跨会话恢复：

```text
received → indexing → grouping → awaiting_precheck → identification_pending
→ identifying → identification_review → awaiting_collection_confirmation
→ collecting → completed | completed_with_exceptions | cancelled
```

用户可在 `awaiting_precheck` 修正配对、拆分、合并或排除候选项。配对改变会使相关识别、审核决定和未执行收藏计划过期。进入识别后，不把已成功识别的候选项重新识别。

同一实物在不同任务中保留两条任务记录，只通过相同且已验证的 `user_uniq_uri` 建立实体关联。同任务两个活跃记录出现相同 `user_uniq_uri` 时必须停止自动收藏并让用户消除冲突。

## 静态审核台生成与交接（兼容模式）

生成页面前阅读 [可复用硬币审核台规范](references/review-workbench-spec.md) 与 [盒子币标签分析](references/slab-label-analysis.md)。识别前先运行 `build_pairing_workbench.py`；页面必须同时列出散图候选和已成功归档证据的表格候选，并显示表格行、正反面 URL 与下载状态。配对批量操作只写浏览器草稿；审核结束后先经 WebMCP 的 `get_pending_pairing_decisions` 取得交接包，再通过 `import-pairing` 逐条落为事件。仅当 WebMCP 不可用或读取失败时，才要求用户导出 JSON 并导入；无论来源为何，不能把 `localStorage` 或批量 UI 状态当作正式决定。存在盒子币时还要显示标签字段、字段置信度、原始证据与冲突状态。只有所有可识别候选均为 `requires_review: false`、不存在表格下载/关联异常、且用户选择不审核盒标识别时，才直接生成首次识别确认卡。识别后审核再运行：

```bash
python3 <skill-dir>/scripts/build_review_workbench.py --task-key <task_key>
python3 <skill-dir>/scripts/serve_review_workbench.py --task-key <task_key> --port 0
```

打开服务返回的 `http://127.0.0.1:<port>/`。页面通过 WebMCP 暴露只读决定；若浏览器不支持，则让用户导出 JSON。取得决定后，必须用 `heribase-task-package/scripts/task_operations.py import-review` 导入任务包，不能直接解析 `localStorage` 作为最终数据。

## 已收藏资料的编辑

当用户明确要求编辑或取消已有收藏时，先把选中的永久 `local_id` 与完整编辑字段写成 typed intent，再通过 `task_operations.py build-plan --operation collection_update|collection_cancel --operations-json <intent>` 生成对应计划。任务中必须已有可验证的 `collection_uri`。展示精确变更或取消范围，取得绑定 `payload_sha256` 的确认，紧邻写入运行 preflight 后，再使用 `heribase-cli` 命令参考中的收藏编辑或取消命令。避免以空值覆盖未知字段；不得传入或推断资产关联字段，服务端会按收藏记录回查资产身份。

## 验收行为

对“这 60 张图片都是我的硬币，帮我整理一下”，必须先创建完整任务包，再返回候选实物、配对、缺面、疑似重复和待确认的识别范围。没有首次明确确认时，不能运行上传、识别或收藏命令。识别后必须生成可复用审核台并持久化人工决定；没有与当前计划摘要绑定的第二次确认时，不能加入收藏。结束时必须报告 `task_key`、数据健康、异常/待协调项和继续任务的方法。

## 参考

- [任务协议](references/task-protocol.md)
- [结果分组与排序](references/result-classification.md)
- [全量图片配对方法](references/pairing-method.md)
- [失败、取消与恢复](references/recovery-and-confirmation.md)
- [可复用硬币审核台规范](references/review-workbench-spec.md)
- [盒子币标签分析](references/slab-label-analysis.md)
