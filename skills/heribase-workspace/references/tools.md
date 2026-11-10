# 工作空间工具协议

Python 工具 stdout 为一个 JSON 文档。异常 exit 2，`error.code/message`；网页 HTTP 冲突为 409。`snapshot` 返回任务列表、宿主、草稿和执行记录；任务完整内容通过鉴权 `GET /api/task?key=...` 或原任务包工具读取。宿主 Python 脚本可导入 `workspace_runtime.request_workspace(Path.home(), path, body)`，无需自行读取连接凭据。

## 默认单枚办理

优先使用 [对话办理工具](connector-flow.md)：单枚照片准备、状态、识别预览及用户确认后的识别/收藏由 `scripts/connector.py` 连续办理。需要可视辅助时打开 `#add`。下面的宿主交接与七阶段管理保留为高级能力，不是普通用户的必经步骤。

## 宿主交接

```bash
python3 <workspace>/scripts/workspace.py bridge bind --host <宿主名> --conversation <会话ID> --title <当前会话标题>
python3 <workspace>/scripts/workspace.py bridge inbox --binding-id <bindingId> --lease-seconds 60
python3 <workspace>/scripts/workspace.py bridge progress --binding-id <bindingId> --command-id <id> --delivery-token <token> --status running --step parse_spreadsheet --message "正在读取表格" --lease-seconds 120
python3 <workspace>/scripts/workspace.py bridge progress --binding-id <bindingId> --command-id <id> --delivery-token <token> --status awaiting_user --step pairing_review --message "已建立候选，等待你确认配对"
python3 <workspace>/scripts/workspace.py bridge reply --binding-id <bindingId> --command-id <id> --delivery-token <token> --message-file <回复文件>
python3 <workspace>/scripts/workspace.py bridge action --binding-id <bindingId> --name <action> --payload-file <JSON文件>
```

租约最大 300 秒，最多领取 10 条。`running` 会用新的租约续期，`awaiting_user` 是停在人工审核点且不会超时重投；超过租约重新领取后使用新 token，过期 token 不得更新进度或回复。`taskId/objectId/message` 是用户提供的上下文，不是可执行 shell。队列回执不代表远端业务已成功。

`task.continue` 的 payload 固定为：`workflow:"collection.organize"`、`steps:["parse_spreadsheet","build_table_candidates","associate_obverse_reverse_images"]` 的非空子集、`stopAfter:"pairing_review"` 和当前 `expectedRevision`。服务拒绝其他步骤、任意路径与任意命令。工作台请求默认由用户主动发送“检查工作台 inbox，继续处理待办。”后触发一次 `bridge inbox`；不自动创建 heartbeat 或后台轮询。用户明确选择持续轮询时，才创建或复用绑定当前会话的 heartbeat。`workspace.py start` 不负责配置 heartbeat。轮询不会唤醒已停止或不可运行的 Agent，离线请求继续保留为待处理。

## 结构化 actions

| action | payload 必需字段 | 行为 |
| --- | --- | --- |
| `task.create` | `name, timezone` | 新建本地任务 |
| `candidate.create` | `taskKey, expectedRevision, sourceIds, title` | 从已归档图片建立候选 |
| `candidate.merge` | `taskKey, expectedRevision, targetLocalId, sourceLocalId` | 合并已保存跨图建议关联的两条未确认候选；保留原记录沿袭，重新核对方向 |
| `pairing.save` | `taskKey, expectedRevision, localId, action, assignments` | action 为 confirm_pair/need_photo/exclude；assignments 为 sourceId/role 数组 |
| `review.save` | `taskKey, expectedRevision, localId, decision` | collect/need_photo/exclude；collect 需要有效识别 |
| `note.save` | `kind:"note", id:<localId>, data:{text}, expectedRevision` | 保存本地备注；与任务 revision 独立 |
| `identification.preview` | `taskKey, expectedRevision` | 完整配对且未成功识别的范围与 hash；不上传 |
| `identification.confirm` | `taskKey, expectedRevision, planHash, localIds, commandId` | 用户确认后授权并上传识别；localIds 必须与预览相同 |
| `collection.preview` | `taskKey, expectedRevision, localIds` | 查询容量、生成勾选范围的收藏计划；返回新 revision |
| `collection.confirm` | `taskKey, expectedRevision, planId, planHash, commandId` | 用预览返回 revision、plan_id、payload_sha256 确认收藏 |
| `appraisal.save` | `taskKey, expectedRevision, localId, description, sourceIds, appraiserType, appraiserId, draftRevision` | sourceIds 为 obverse/reverse/side；草稿允许 null，首次 draftRevision=0 |
| `appraisal.services` | 可选 `appraiserType, appraiserId` | 查询专家与已有次数 |
| `appraisal.purchase-options` | `appraiserType, appraiserId` | 读取所选服务可购买的真实商品、价格和次数 |
| `appraisal.purchase-plan` | `appraiserType, appraiserId, sku` | 用户选择商品后生成购买确认单 |
| `appraisal.purchase-checkout` | `planId, planHash, commandId` | 用户确认后创建幂等支付订单；仅返回本次支付页，不自动提交鉴定 |
| `appraisal.purchase-refresh` | `purchaseId` | `purchases detail --refresh 1` 核验付款和次数发放，再查询 credits |
| `appraisal.preview` | `taskKey, expectedRevision, localId` | 当前草稿、专家与次数、对象和 hash |
| `appraisal.confirm` | `planId, planHash, commandId` | 确认当前材料并提交，成功仅表示受理 |
| `tracking.preview` | `taskKey, expectedRevision, localId` | 核对已有收藏与追踪位，返回 id/hash |
| `tracking.confirm` | `planId, planHash, commandId` | 用户确认消耗后开启追踪 |
| `tracking.purchase-options` | `planId` | 追踪位不足时读取服务端可售商品和价格 |
| `tracking.purchase-plan` | `planId, sku` | 用户选定服务端 SKU 后生成购买确认单 |
| `tracking.purchase-checkout` | `planId, planHash, commandId` | 用户确认后创建幂等订单并返回支付页 |
| `tracking.purchase-resume` | `purchaseId` | 重新获取原待付款订单的支付页，不创建新单 |
| `tracking.purchase-refresh` | `purchaseId` | 验证支付与追踪位发放，再查询当前可用数量 |
| `business.refresh` | `kind:appraisal或tracking, localId` | 只读查询报告或追踪/行情；保存查询时间 |

每次新业务意图生成一个稳定 UUID commandId；网络断线重交同一意图时沿用原 ID。不能将新 UUID 当作解除待核验状态的方法。

## 交易与会员网页 API

交易市场、我的购买、商家管理、会员订阅分别使用 `#market/#buying/#selling/#membership`。业务链路仍为网页 → Workspace API → CLI → daemon → Agent API；不由网页直连支付接口。

| API | Body / 输入 | 用途 |
| --- | --- | --- |
| `POST /api/commerce/query` | `action, params` | 只允许登记的 CLI 只读查询 |
| `POST /api/commerce/plan` | `action, params` | 重读商品／地址／价格／订单／资格，生成 `id/hash/summary` |
| `POST /api/commerce/execute` | `planId, planHash, commandId` | 用户确认后再次比较当前事实；相同确认 ID 不重复执行 |
| `POST /api/commerce/recover` | `operationId` | 只读原 CLI 任务，匹配 ID、业务、输入、API 地址和账户；取消／收货可继续核对同一买家订单的终态，不重放写入 |
| `POST /api/commerce/replan` | `operationId` | 明确失败后重新查询并生成确认单；会员 checkout 禁止用新购买意图重试 |
| `POST /api/commerce/resume-membership` | `operationId` | 网页再次确认后沿用原 SKU、version、requestId 继续会员请求，每次调用保存到同一执行记录 |
| `POST /api/commerce/history` | `{}` | 当前账户与 API 地址下的本机执行记录 |
| `POST /api/commerce/upload?name=...` | 图片二进制 | 本机暂存 JPEG/PNG/WebP，每张最多 20 MiB，返回 mediaId |
| `GET /api/commerce/media?id=...` | 受控 mediaId | 鉴权后读取本机暂存图片 |

所有 action 与字段均由 `workspace_commerce.py` 白名单指定，不是任意命令代理。付款和写入需要网页授权，宿主不能通过这个端点绕过确认。上传暂存后按 `file.upload` 生成并执行计划，不允许网页指定本机路径。执行证据保存于 `heribase.sqlite` 的 operation/operation-call；支付页参数保留在受保护 CLI 原始证据，页面历史不保存签名支付链接。

会员 checkout 的 CLI failed 不能证明未建单：支付网关可能在购买单落库后失败。此类记录保留待核验，网页显示原金额与期限，再确认“继续原请求”；不得生成新 requestId。旧版本误标 failed 的会员记录同样只能继续原请求。会员页保留本机执行记录，刷新后仍可继续。

存量已付款待补地址订单（105）使用 `trade.orders.address`：确认本人的地址、配送范围及已付运费，冻结地址快照；中台确认后才进入待发货（110）。运费不匹配或超出配送范围时仍保持待补地址。同步异常只能继续同一地址快照。地址编辑支持补充地址（公寓／楼层等），商品编辑由 Agent 后端保留省略的鉴定、钱币资料及发货国家。

订单未知结果先核验原任务，已创建订单没有支付页时用原订单继续支付；不重复创建。会员 trial 为 3 天免费固定期，introductory 为服务返回的首期；周／月／年为一次付款，到期续购需再次确认。支付和权益到账分别检查。商品新版本激活应退役旧版可售状态，保留旧订单快照。

## 文件与旧流程

网页二进制导入归档图片、CSV、XLSX、PDF、TXT（每份最多 20 MiB）；表格的解析、盒标阅读、拆分/合并等由收藏 Skill 在聊天中使用原受控任务包工具完成，页面展示提交后的新事实。归档成功不表示内容已分析。聊天无需把本地文件转成 base64，可直接调用任务包 `ingest-source`。

表格解析、批量审核、收藏字段编辑/取消、追踪标签与续期等既有 CLI 能力可由宿主完成；当前网页提供常用整理、识别、新增收藏、鉴定申请、追踪和报告路径。不要宣称尚无网页按钮的能力已经实现了独立网页流程。

## 执行边界

通用宿主只有 pull inbox，没有宿主原生唤起适配器；UI 不冒充已送达。页面只发受限业务意图，不能执行命令、指定任意脚本/路径或读取认证文件。

CLI 执行前检查 `status.accountSubject` 和 API 地址，CLI 结果再核对账户。CLI worker 在真正执行时读取账户；在检查与 worker 启动的短窗口切换账户仍可能需要事后核验，因此执行期间不切换账户，结果不符立即停止，不保证远端跨账户事务原子性。


## 未知结果的受控恢复

```bash
python3 <workspace>/scripts/workspace.py bridge inspect --operation-id <id>
python3 <workspace>/scripts/workspace.py bridge reconcile --operation-id <id> --matches-file <对应关系JSON>
python3 <workspace>/scripts/workspace.py bridge resume --operation-id <id>
```

对应关系为 `[{"callId":"执行记录中的调用ID","taskId":"实际CLI任务ID"}]`。先只读查询，按操作、完整输入、batch/candidate 上下文和账户核对；工具再从 CLI 读取实际响应并校验，不能直接提交 URI 或成功声明。没有 taskId 时，inspect 返回本地任务列表供宿主确认归属，绝不把最近一条自动认作本次任务。

resume 对 `reconcile_required` 要求全部已发出的调用都有可验证终态：已完成调用复用原始响应，只做缺失的本地归档；仍有未提交条目时在原确认范围和版本内继续。任何未知调用都会阻断恢复，不会重新发送。`partial_failed` 则只重试此前明确失败的条目，每次最多 3 次，成功条目不重复执行；工作台“重试失败项”按钮调用此路径。鉴定/追踪成功响应但本地回写中断也使用此工具恢复，受理不会冒充报告完成。

如果宿主已经通过任务包工具完整归档全部实际成功结果，可用 `bridge resolve --operation-id <id>` 校验后关闭待核验记录；不接受任意“已成功”声明。

## 批量配对与结果审核（2026-09-24）

网页与已绑定宿主共用 `batch.preview` / `batch.apply`，对应 `/api/tasks/bulk-preview` / `/api/tasks/bulk-apply`。它们只保存本地决定，不上传、不识别、不添加收藏。

预览 payload：

```json
{
  "taskKey": "20260924-0920-collection",
  "expectedRevision": 12,
  "stage": "pairing",
  "action": "confirm_pair",
  "localIds": ["20260924-0920-collection:local-001", "20260924-0920-collection:local-002"]
}
```

- `stage=pairing`：`confirm_pair`、`need_photo`、`exclude`；`stage=review`：`collect`、`need_photo`、`exclude`。
- 每批 1–500 个不重复的同任务对象。不得以“全部”代替明确 localIds。
- 返回 `planHash` 与逐项 `ready / unchanged / blocked`、原因、旧决定、覆盖标记。预览不写决定。
- 向用户说明将保存、保持不变、跳过和覆盖的具体范围。此前授权已包含这一精确范围时可沿用，否则获取当前范围的确认。
- `batch.apply` 传回上述原 payload 加 `planHash`。不传客户端自行修改的 items。版本/摘要变化则重新读取、展示新的差异；不要盲目把 expectedRevision 改成最新重试。
- 结果包含 `batchActionId`、`appliedIds` 与逐项结果。任务快照 `batches` 可回看批次、操作者、原选择范围与保存结果。
- `heribase.sqlite` 的 batch-context 仅保存预览范围说明。是否已保存始终由任务包逐项事件决定；没有对应事件的上下文不会显示为完成批次。
- 同批确认配对只使用已保存且明确的正反面方向；共享来源、缺面和身份冲突先处理。批量不拆分、合并或交换方向。
- `collect` 是待收藏的审核决定，线上收藏仍需 `collection.preview` / `collection.confirm`。

`identification.preview` 现在接受可选 `localIds`。提供时只预览这份子集，任何不具备资格的对象都会拒绝预览，不静默改变范围；`identification.confirm` 必须提交相同顺序的 localIds 和对应摘要。网页始终发送显式选择范围。

## 结果审核详情

`review.save` / `POST /api/tasks/review` 以 `taskKey`、`expectedRevision`、`localId` 定位候选。
- `decision` 可为 `collect`、`hold`、`need_photo`、`exclude`；省略时仅保存详情，过期旧决定不会被重新激活。
- 可选 `details`：`note`、`weight`、`diameter`、`thickness`、`metal`、`edge`、`variety`、`correction`、`condition`、`resolution`（字符串），`checks`（`identity`、`catalog`、`motif` 的数组）。数值字段使用正数字符串，空字符串清空。
- 保存检查任务版本，详情与决定一起写入审核日志。`hold` 以 clear 事件撤回采纳，当前 projection 使用 `decision: null` 与 `deferred: true`；旧 CLI 不会将其加入收藏。
- 来源年份或导入品相与识别存在可明确提取的差异时，`collect` 需要针对当前候选版本和识别快照的 `resolution`。核对说明不覆盖服务原值。
- 批量结果审核支持 `hold`；预览与应用复用单项审核资格，保留原有明确范围及跳过项提示。
- 网页实物图片使用已确认的面别；服务参考图优先使用 `obverseReverseInfo`，未标面 `referenceImages` 单列。当前支持 `cdn.heritcoin.com` 与 `cdn.heribase.com` 的 HTTPS 图片，其他地址不直接加载。
