// Explicit logout survives refresh within this tab. A new tab can auto-enter.
const KEY = 'dataflow-development-logged-out'
export function shouldAutoLogin(status, storage) {
    return status.development === true && storage.getItem(KEY) !== '1'
}
export function markLoggedOut(storage) { storage.setItem(KEY, '1') }
export function clearLoggedOut(storage) { storage.removeItem(KEY) }
