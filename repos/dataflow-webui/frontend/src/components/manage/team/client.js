import axios from 'axios'
export const team = { enabled: false, development: false, viewer: '', csrf: '', project: '', version: 0 }
export function installTeamTransport(client) {
    client.interceptors.request.use((config) => {
        if (team.enabled && String(config.url).startsWith('/api/')) {
            config.headers['X-CSRF-Token'] = team.csrf
            config.headers['X-Project-ID'] = team.project
            config.headers['If-Match'] = String(team.version)
        }
        return config
    })
    client.interceptors.response.use((response) => {
        const value = response.headers['x-resource-version']
        if (value !== undefined) team.version = Math.max(team.version, Number(value))
        return response
    })
}
installTeamTransport(axios)
export async function request(path, body, method = body === undefined ? 'GET' : 'POST') {
    const response = await fetch(path, {
        method,
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': team.csrf,
            'X-Project-ID': team.project
        },
        body: body === undefined ? undefined : JSON.stringify(body)
    })
    const data = await response.json()
    if (!response.ok) {
        const error = new Error(data.detail || data.message || '操作失败')
        error.status = response.status
        throw error
    }
    return data.data ?? data
}
