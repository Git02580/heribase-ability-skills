---
name: heribase-appraisal
description: 在 HeriBase 准备或恢复真人钱币鉴定材料，选择官方服务或专家、购买或核对次数、确认提交，并查询进度与真实鉴定报告。
compatibility: 同级 heribase-workspace、heribase-task-package、heribase-cli；Python 3.9+ 和 Node.js 24+。
metadata:
  short-description: 鉴定材料、确认提交与报告跟进
---

# HeriBase 真人鉴定

先读 [工作空间 Skill](../heribase-workspace/SKILL.md)，启动或复用工作台并绑定当前宿主会话：Codex 桌面 App 使用 `workspace.py start --no-default-browser --page appraisals` 获取 URL，其他宿主使用 `workspace.py start --page appraisals`。有明确藏品时打开 `appraisal --task-key <key>`；Codex 按工作台设置通过 `mcp__codex_app__open_in_codex` 的右侧浏览器打开，其他宿主按默认行为打开。用户选择纯聊天则只用 `--no-default-browser` 启动服务，不打开页面。先恢复已有申请，不从空白重新收集相同材料。

1. 从当前藏品档案关联本人收藏或已识别记录，归档正面、反面、侧面与补充材料。来源和描述保存为本地草稿；未完成材料不能假装齐全。
2. 查询服务真实返回的官方服务、专家和已有次数。新调用方使用 `officialList`，标准 7 天服务为类型 `1`、专家 ID `0`，加急 3 天服务为类型 `5`、专家 ID `0`；专家目录的 `durationTime` 原样保留。使用实际专家 ID；不推断免费额度、鉴定时间或费用。`appraisal.save` 保存材料，`appraisal.preview` 查询当前服务并返回本次 hash。
3. 展示对象、专家、图片、关注问题和已有次数消耗，按用户已明确授权的范围执行 `appraisal.confirm`。图片离开本机及额度消耗必须属于授权范围。
4. 提交成功只表示受理。用 `business.refresh` 查询原申请，保留服务状态、查询时间和原始报告，不生成专家尚未返回的结论。
5. 超时或未知结果保留 `reconcile_required`，先查询原 CLI 任务和 `appraisals list/detail`，不重复核销次数。

工具字段见 [工作空间工具协议](../heribase-workspace/references/tools.md)。线上命令与 JSON 契约见 [CLI 命令参考](../heribase-cli/references/command-reference.md)。次数不足或用户希望预先购买时，工作台先查询 `products`，按所选服务的 `purchaseFilter` 匹配 `entitlementSpec`，展示商品真实价格/币种/次数并按用户明确选择创建 `checkout`。同一次购买固定 `requestId`，保留原订单 URI；工作台只打开服务端提供的支付页，由用户在网页完成付款，不保存支付页面参数。

支付后调用 `purchases detail --refresh 1`，仅 `paymentState=paid` 且 `fulfillmentState=granted` 视为购买到账，再查询所选专家对应的 credits。已付款但发放 pending 时继续查询原单；不要重复下单，不以 return 页面或浏览器打开成功判定付款，不模拟支付回调。购买与提交是两个动作，购买不会自动触发核销。随后恢复第 3 步，按已授权范围单独提交。
