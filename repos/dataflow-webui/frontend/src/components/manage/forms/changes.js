// Refresh cached readers in this window and other local WebUI tabs after mutations.
const eventName = 'dataflow:changed'
const storageKey = 'dataflow:last-change'
export function publishChange(topic, id = '') {
    const detail = { topic, id, at: Date.now(), nonce: Math.random().toString(36).slice(2) }
    window.dispatchEvent(new CustomEvent(eventName, { detail }))
    try { localStorage.setItem(storageKey, JSON.stringify(detail)) } catch { /* local-only refresh still works */ }
}
export function subscribeChanges(listener) {
    const local = event => listener(event.detail)
    const remote = event => { if(event.key !== storageKey || !event.newValue)return;try{listener(JSON.parse(event.newValue))}catch{/* ignore unrelated invalid storage */} }
    window.addEventListener(eventName, local)
    window.addEventListener('storage', remote)
    return () => { window.removeEventListener(eventName, local); window.removeEventListener('storage', remote) }
}
