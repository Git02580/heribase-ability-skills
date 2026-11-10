---
name: heribase-tracking
description: 在 HeriBase 从本人收藏开启钱币追踪，核对已有追踪位，查看追踪状态、真实行情与来源，或按明确意图更新标签、品相和续期。
compatibility: 同级 heribase-workspace、heribase-task-package、heribase-cli；Python 3.9+ 和 Node.js 24+。
metadata:
  short-description: 本人收藏追踪与行情记录
---

# HeriBase 追踪

先读 [工作空间 Skill](../heribase-workspace/SKILL.md)，启动或复用工作台并绑定当前宿主会话：Codex 桌面 App 使用 `workspace.py start --no-default-browser --page tracking` 获取 URL，其他宿主使用 `workspace.py start --page tracking`。Codex 按工作台设置通过 `mcp__codex_app__open_in_codex` 的右侧浏览器打开，其他宿主按默认行为打开。用户选择聊天则只启动或复用服务，不打开页面。

1. 恢复已有追踪记录。新追踪从已验证的本人 `collection_uri` 开始，不使用裸内部币种/版别 ID。
2. `tracking.preview` 查询追踪位，展示具体对象、实际已有位数及限制。未知费用和有效期保持未知；额度不足保留原任务。
3. 用户确认对象与消耗后，用同一计划的 id/hash 执行 `tracking.confirm`。重复投递沿用 commandId；未知结果先核验原任务和追踪列表，不重复占用追踪位。
4. `business.refresh` 读取真实追踪详情与价格趋势。每次展示注明查询时间、币种与服务返回的品相/适用条件；缺字段保持空白。仅返回 App 入口时说明限制，不编造曲线或估值。
5. 标签、品相或续期按用户具体意图经 [CLI 命令参考](../heribase-cli/references/command-reference.md) 完成，核对对象并保留原始响应。续期只传已验证 trackingUri，不把查询资格当作续期授权。当前网页无独立标签/续期编辑表单，使用聊天完成后重新查询页面。

工具字段见 [工作空间工具协议](../heribase-workspace/references/tools.md)。不购买追踪位、不交易，也不承诺收益或未来价格。
