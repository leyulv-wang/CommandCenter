const centralBase = 'http://127.0.0.1:8000'
let profile = null

const byId = (id) => document.getElementById(id)

async function request(url, options = {}) {
  const response = await fetch(url, options)
  if (!response.ok) throw new Error(await response.text() || `请求失败 ${response.status}`)
  return response.json()
}

function showMessage(text) {
  const element = byId('message')
  element.textContent = text
  element.classList.add('show')
  setTimeout(() => element.classList.remove('show'), 2200)
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  })[character])
}

function recordHtml(item, completed = false) {
  const content = Object.entries(item.content || item.form_values || {})
    .map(([key, value]) => `<p>${escapeHtml(key)}：${escapeHtml(value)}</p>`).join('')
  const result = item.result_values
    ? `<p>处理结果：${escapeHtml(JSON.stringify(item.result_values))}</p><p>完成时间：${escapeHtml(item.completed_at || '-')}</p>`
    : ''
  return `<article class="record ${completed ? 'completed' : ''}"><strong>${escapeHtml(item.title || item.ticket_id)}</strong>${content}${result}<p>编号：${escapeHtml(item.task_id || item.ticket_id)}</p></article>`
}

function renderList(id, items, completed = false) {
  byId(id).innerHTML = items.length
    ? items.map((item) => recordHtml(item, completed)).join('')
    : '<div class="empty">暂无数据</div>'
}

async function refreshStatus() {
  try {
    const systems = await request(`${centralBase}/external-systems`)
    const system = systems.find((item) => item.system_code === profile.system_code)
    const status = byId('connection-status')
    status.textContent = system?.role === 'connected' ? '已接入中控' : '未接入中控'
    status.className = `status ${system?.role || 'unknown'}`
  } catch {
    byId('connection-status').textContent = '中控未启动'
  }
}

async function refreshData() {
  const [pending, completed, submissions, spec] = await Promise.all([
    request('/api/tasks?operator_id=u001&status=pending'),
    request('/api/tasks?operator_id=u001&status=completed'),
    request('/api/submissions'),
    request('/api/interface-spec'),
  ])
  renderList('pending-list', pending.items)
  renderList('completed-list', completed.items, true)
  renderList('submission-list', submissions.items)
  byId('task-count').textContent = String(pending.items.length + completed.items.length)
  byId('interface-description').textContent = spec.description
  await refreshStatus()
}

async function createTask(event) {
  event.preventDefault()
  const itemName = byId('item-name').value
  const quantity = Number(byId('quantity').value)
  const reason = byId('reason').value
  const content = profile.interface_type === 'workflow'
    ? { item_name: itemName, quantity, reason }
    : { item_name: itemName, quantity, usage: reason, applicant: '演示员工' }
  await request('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: byId('task-title').value,
      task_type: profile.task_type,
      form_code: profile.task_form_code,
      content,
      assignee_id: byId('assignee').value,
    }),
  })
  event.target.reset()
  byId('quantity').value = '1'
  byId('assignee').value = 'u001'
  showMessage('任务已派发')
  await refreshData()
}

async function resetSystem() {
  if (!confirm(`确认重置${profile.system_name}的演示数据和接入状态？`)) return
  await request(`${centralBase}/demo/reset/${profile.system_code}`, { method: 'POST' })
  showMessage('本系统演示已重置')
  await refreshData()
}

function initTabs() {
  document.querySelectorAll('.tab').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((item) => item.classList.remove('active'))
      document.querySelectorAll('.tab-panel').forEach((item) => item.classList.remove('active'))
      button.classList.add('active')
      byId(`${button.dataset.tab}-panel`).classList.add('active')
    })
  })
}

async function init() {
  profile = await request('/api/system-profile')
  document.title = profile.system_name
  document.body.classList.add(profile.interface_type)
  byId('system-name').textContent = profile.system_name
  byId('interface-label').textContent = profile.interface_type === 'workflow'
    ? 'Workflow Business System'
    : 'Custom URL Business System'
  byId('task-form').addEventListener('submit', (event) => createTask(event).catch((error) => showMessage(error.message)))
  byId('refresh-button').addEventListener('click', () => refreshData().catch((error) => showMessage(error.message)))
  byId('reset-button').addEventListener('click', () => resetSystem().catch((error) => showMessage(error.message)))
  initTabs()
  await refreshData()
}

init().catch((error) => showMessage(error.message))
