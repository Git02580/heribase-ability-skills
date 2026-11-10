# HeriBase 收藏任务：失败、取消、恢复与确认令牌迁移

## 原子操作与部分失败

每个候选项独立经历 `pending → uploading → uploaded → identifying → identified | failed`。批次中的其他候选项可以继续处理；成功项不能因为另一项失败被丢弃或重复执行。

| 情况 | 处理方式 |
|---|---|
| 上传失败 | 标记候选项失败，保留其他结果；仅在用户要求时重试该项 |
| 识别失败 | 放入待复核/失败，不进入收藏草稿；仅在用户要求时重试该项 |
| 收藏写入失败 | 报告成功与失败的精确清单；保留成功的 `collection_uri`，只对已授权计划中的确定失败项建立新 attempt |
| 收藏响应不明确、超时或进程崩溃 | 标记 `reconcile_required`；先用只读 CLI 查询服务端事实，禁止直接重试 |
| CLI 任务仍在运行 | 使用 `heribase task get <task-id> --json` 或 `heribase task wait <task-id> --json` 查询；未知终态不能报告为失败或成功 |
| 未认证或权限错误 | 停止该项，按 `heribase-cli` 说明要求用户登录或处理权限问题 |

## `fetch failed` 与本地 daemon 恢复

`fetch failed`、连接被拒绝或连接重置可能来自 CLI daemon，也可能来自上游服务；不能直接假定为网络问题或重复发起操作。

1. 先记录受影响候选、原始错误和是否可能已向服务端提交。
2. 运行 `heribase daemon status --json`。只有显示 daemon 不健康、未运行，或 status 无法与 daemon 通信时，才运行一次正常的 `heribase daemon stop --json`，再运行 `heribase daemon start --json`，并复查 status。
3. daemon 健康后，读取类操作可重试一次；上传或识别仅能在已获授权的范围内重试。
4. 对 `collection add`、`collection update`、`collection cancel`，凡是请求可能已送达、超时或终态未知，一律先标记 `reconcile_required` 并进行只读核验，不能因为 daemon 已恢复就直接重试。

不得使用 `daemon stop --force` 作为常规恢复手段；它可能中断仍在运行的本地任务，除非用户另有明确要求。

上传成功不等于识别成功；识别成功不等于收藏成功。

## 取消与恢复

- 首次确认前取消：保留完整任务包；绝不上传、识别或写收藏。
- 识别过程中取消：停止尚未开始的候选项。已提交 CLI 的任务先查询终态；只有用户明确要求取消该任务时，才使用 `heribase task cancel <task-id> --json`。
- 第二次确认前取消：保留识别结果和审核决定；取消或废弃当前收藏计划，不执行 `collection add`。
- 会话中断：从 `~/.heribase/user-tasks/<task_key>/` 恢复。先验证 integrity、JSONL 哈希链、raw 挂接、manifest/items revision，再查询仍为运行中或不明确的 CLI 原子任务。

批次终态应如实显示为 `completed`、`completed_with_exceptions` 或 `cancelled`，并附带可继续处理的准确候选项清单。

## 未来服务端确认令牌迁移

当前实现没有服务端确认令牌。第二次确认的实际流程是：

```text
识别审核 → 带 payload_sha256 的本地收藏计划 → 用户确认该摘要 → 执行前复核摘要 → collection add
```

未来 API 与 CLI 实际提供受控写入能力后，仅替换最后一段：

```text
prepare_collection
  → 服务端返回目标范围、费用、有效期、幂等信息和 confirmationId
  → 用户确认预览
  → confirm_action(confirmationId)
```

`confirmationId` 由服务端签发并绑定用户、操作范围、费用、有效期、幂等键和审计记录。它用于进一步防止确认后范围变化、重复写入和过期执行；在它出现之前，本地计划摘要是现行明确闸门。首次整理确认不使用令牌，因为尚未上传、识别或写入收藏。

在该 API 和 CLI 命令真正发布前：不得生成伪造的 `confirmationId`，不得声称已预留费用，不得调用不存在的 `heribase action prepare` 或 `heribase action confirm`。
