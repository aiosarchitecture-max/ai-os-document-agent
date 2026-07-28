const diag = document.getElementById('diag')
const statusEl = document.getElementById('status')
const tokenEl = document.getElementById('token')
let excalidrawAPI = null
let version = 0
let modules = null
const COLOR_HEX = { green: '#b2f2bb', amber: '#ffec99', gray: '#e9ecef', blue: '#a5d8ff' }
const HEX_TO_COLOR = { '#b2f2bb': 'green', '#ffec99': 'amber', '#e9ecef': 'gray', '#a5d8ff': 'blue' }

function setStatus(text) { statusEl.textContent = text }
function token() { return sessionStorage.getItem('aios_canvas_token') || '' }
function authHeaders(json = false) {
  const headers = { Authorization: `Bearer ${token()}` }
  if (json) headers['Content-Type'] = 'application/json'
  return headers
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...authHeaders(Boolean(options.body)), ...(options.headers || {}) }
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try { detail = JSON.stringify((await response.json()).detail) } catch (_) {}
    const error = new Error(detail)
    error.status = response.status
    throw error
  }
  return response.json()
}

async function loadCanvas() {
  if (!excalidrawAPI || !token()) return
  setStatus('Načítavam…')
  const data = await api('/canvas/document')
  version = data.version
  if (data.snapshot && Array.isArray(data.snapshot.elements)) {
    excalidrawAPI.updateScene({ elements: data.snapshot.elements })
  } else {
    const elements = modules.convertToExcalidrawElements(
      (data.nodes || []).map(node => ({
        type: 'rectangle', id: node.id, x: node.x, y: node.y,
        width: node.w, height: node.h,
        backgroundColor: COLOR_HEX[node.color] || COLOR_HEX.gray,
        label: { text: node.text || '' }
      })),
      { regenerateIds: false }
    )
    excalidrawAPI.updateScene({ elements: modules.restoreElements(elements, null) })
  }
  try { excalidrawAPI.scrollToContent() } catch (_) {}
  setStatus(`Pripojené · verzia ${version}`)
}

async function saveCanvas() {
  if (!excalidrawAPI || !token()) { setStatus('Najprv sa pripoj'); return }
  const elements = excalidrawAPI.getSceneElements()
  const nodes = elements.filter(element => element.type === 'rectangle' && !element.isDeleted).map(rect => ({
    id: rect.id,
    x: Math.round(rect.x), y: Math.round(rect.y),
    w: Math.round(rect.width), h: Math.round(rect.height),
    text: (elements.find(element => element.type === 'text' && element.containerId === rect.id) || {}).text || '',
    color: HEX_TO_COLOR[(rect.backgroundColor || '').toLowerCase()] || 'gray'
  }))
  setStatus('Ukladám…')
  try {
    const saved = await api('/canvas/document', {
      method: 'PUT',
      body: JSON.stringify({
        expected_version: version,
        nodes,
        edges: [],
        snapshot: { elements }
      })
    })
    version = saved.version
    setStatus(`Uložené · verzia ${version}`)
  } catch (error) {
    setStatus(error.status === 409
      ? 'Konflikt verzií — obnov plátno'
      : `Uloženie zlyhalo: ${error.message}`)
  }
}

function addNode() {
  if (!excalidrawAPI) return
  const text = prompt('Text nového uzla:', 'Nový uzol')
  if (!text) return
  const elements = modules.convertToExcalidrawElements([{
    type: 'rectangle', x: 100, y: 400, width: 150, height: 60,
    backgroundColor: COLOR_HEX.blue, label: { text }
  }])
  excalidrawAPI.updateScene({
    elements: [...excalidrawAPI.getSceneElements(), ...modules.restoreElements(elements, null)]
  })
}

async function connect() {
  const supplied = tokenEl.value.trim()
  if (supplied) sessionStorage.setItem('aios_canvas_token', supplied)
  tokenEl.value = ''
  try {
    await loadCanvas()
  } catch (error) {
    sessionStorage.removeItem('aios_canvas_token')
    setStatus(error.status === 401
      ? 'Neplatný token'
      : `Pripojenie zlyhalo: ${error.message}`)
  }
}

window.addEventListener('error', event => {
  diag.style.display = 'block'
  diag.textContent = `Chyba plátna: ${event.message}`
})
window.addEventListener('unhandledrejection', event => {
  diag.style.display = 'block'
  diag.textContent = `Chyba plátna: ${event.reason}`
})
document.getElementById('connect').addEventListener('click', connect)
document.getElementById('save').addEventListener('click', saveCanvas)
document.getElementById('add').addEventListener('click', addNode)

try {
  const ReactModule = await import('react')
  const React = ReactModule.default || ReactModule
  const { createRoot } = await import('react-dom/client')
  modules = await import('excalidraw')
  function App() {
    return React.createElement(modules.Excalidraw, {
      excalidrawAPI: apiRef => {
        excalidrawAPI = apiRef
        if (token()) loadCanvas().catch(error => setStatus(`Pripojenie zlyhalo: ${error.message}`))
      }
    })
  }
  createRoot(document.getElementById('root')).render(React.createElement(App))
  diag.style.display = 'none'
  if (token()) setStatus('Pripájam…')
} catch (error) {
  diag.textContent = `Nepodarilo sa načítať editor: ${error.message}`
  diag.className = 'fail'
}
