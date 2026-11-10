/**
 * 网页只构造一个固定的整理续办契约。服务端会再次验证；这层限制的目的是
 * 防止把自由文本或页面字段误当作宿主可执行命令。
 */
export function continuationRequest(task, item, bindingId, message, commandId) {
  const manifest = task?.manifest;
  if (!manifest?.task_key || !Number.isInteger(manifest.revision) || manifest.revision < 0) {
    throw new Error('当前任务缺少可核对的任务版本，请刷新后重试');
  }
  if (!bindingId) throw new Error('请先连接当前 Agent 会话');
  return {
    commandId,
    bindingId,
    taskId: manifest.task_key,
    objectId: item?.local_id || null,
    intent: 'task.continue',
    message,
    payload: {
      workflow: 'collection.organize',
      steps: ['parse_spreadsheet', 'build_table_candidates', 'associate_obverse_reverse_images'],
      stopAfter: 'pairing_review',
      expectedRevision: manifest.revision,
    },
  };
}

/** 优先显示宿主提供的可读会话标题；老绑定暂时回退到会话 ID。 */
export function hostDisplayTitle(host) {
  return host?.conversationTitle?.trim() || host?.conversation || '未命名会话';
}

/** 选择器同时保留宿主、在线状态和短会话 ID，避免同名会话难以区分。 */
export function hostOptionLabel(host) {
  const conversation = host?.conversation || '';
  const shortId = conversation.length > 20
    ? `${conversation.slice(0, 8)}…${conversation.slice(-8)}`
    : conversation;
  return `${host?.host || 'Agent'} · ${hostDisplayTitle(host)} · ${host?.connected ? '在线' : '离线'} · ${shortId}`;
}

/** 用户在宿主会话中手动触发 inbox 检查时使用的最短提示词。 */
export const INBOX_PROMPT = '检查工作台 inbox，继续处理待办。';

/** 两种入口始终使用稳定名称，避免在线状态把排队请求误说成即时执行。 */
export function bridgeActionLabels() {
  return { request: '提交请求', continuation: '提交整理任务' };
}

/** 说明请求实际进入持久化 inbox，由 Agent 检查时领取，而不是网页直接唤醒。 */
export function bridgeDeliveryHint(host) {
  if (!host) return '连接 Agent 会话后即可提交；请求会保存在 inbox。';
  return host.connected
    ? '请求已保存到 inbox；Agent 检查时领取。'
    : 'Agent 当前未取件；请求会保留在 inbox。';
}

/** 固定续办流程的范围说明：整理到配对审核即停止，不隐式执行线上操作。 */
export const continuationSummary = '解析表格、建立候选并关联正反面；完成后停在配对审核，不会自动识别或收藏。';

/** 将剪贴板能力作为回调传入，浏览器不支持或用户拒绝时都以 false 结束。 */
export async function copyInboxPrompt(writeText) {
  if (typeof writeText !== 'function') return false;
  try {
    await writeText(INBOX_PROMPT);
    return true;
  } catch {
    return false;
  }
}

export function commandStatus(command) {
  const labels = {
    pending: '已保存，等待接收',
    received: '已接收，准备开始',
    running: '正在处理',
    awaiting_user: '等待你的确认',
    completed: '已完成',
    failed: '处理失败',
    cancelled: '已取消',
  };
  return labels[command.status] || command.status;
}
