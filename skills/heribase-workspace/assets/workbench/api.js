/* 凭据只用于本机连接，不进入资料、日志或 localStorage；业务事实始终来自服务。 */
const SESSION_KEY = 'heribase.workspace.session';
const initial = new URLSearchParams(location.hash.slice(1));
if (initial.has('access')) {
  sessionStorage.setItem(SESSION_KEY, initial.get('access'));
  const route = initial.get('page') || 'home';
  const query = new URLSearchParams();
  if (initial.has('task')) query.set('task', initial.get('task'));
  history.replaceState(null, '', `#${route}${query.size ? `?${query}` : ''}`);
}

export class ApiError extends Error {
  constructor(status, detail, path) {
    super(detail.message || '工作空间请求失败');
    this.status = status;
    this.code = detail.code;
    this.detail = detail;
    this.path = path;
  }
}

export async function request(path, body, options = {}) {
  const key = sessionStorage.getItem(SESSION_KEY);
  if (!key) throw new ApiError(401, { code: 'connection_required', message: '请从 HeriBase 业务入口打开工作台，以建立本机连接。' });
  const headers = { Authorization: `Bearer ${key}` };
  let payload;
  if (body !== undefined) {
    headers['Content-Type'] = options.binary ? 'application/octet-stream' : 'application/json';
    payload = options.binary ? body : JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', headers, body: payload, signal: options.signal });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(0, { code: 'offline', message: '本机服务暂时不可用，当前输入尚未提交。重新连接后可继续。' });
  }
  const value = await response.json();
  if (!response.ok) throw new ApiError(response.status, value.error || {}, path);
  return value;
}

export async function connect() {
  return request('/api/session', {});
}
export function snapshot() {
  return request('/api/snapshot');
}
export function accountProfile() {
  return request('/api/account-profile');
}
export function apiCheck() {
  return request('/api/api-check', {});
}
export function task(key) {
  return request(`/api/task?${new URLSearchParams({ key })}`);
}
export function media(taskKey, sourceId) {
  return `/api/media?${new URLSearchParams({ task: taskKey, source: sourceId })}`;
}
export function upload(taskKey, revision, file) {
  return request(`/api/upload?${new URLSearchParams({ task: taskKey, revision, name: file.name })}`, file, { binary: true });
}
