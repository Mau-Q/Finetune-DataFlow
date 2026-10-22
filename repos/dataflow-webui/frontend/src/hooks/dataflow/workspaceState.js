import { team } from '@/components/manage/team/client'

export function workspaceKey(name) {
    return `dataflow:ui:v1:${team.enabled ? team.viewer || 'anonymous' : 'local'}:${team.project || 'local'}:${name}`
}
export function readWorkspaceState(name, fallback = null) {
    try { return JSON.parse(localStorage.getItem(workspaceKey(name))) ?? fallback } catch { return fallback }
}
export { withoutCredentials } from './draftSnapshot'
import { withoutCredentials } from './draftSnapshot'
export function writeWorkspaceState(name, value) {
    try {
        const json = JSON.stringify(withoutCredentials(value))
        if (json.length > 2_000_000) return false
        localStorage.setItem(workspaceKey(name), json)
        return true
    } catch { return false }
}
