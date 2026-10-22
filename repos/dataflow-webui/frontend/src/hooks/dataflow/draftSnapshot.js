// Draft recovery never retains credentials entered into operator parameters.
export function withoutCredentials(value) {
    if (Array.isArray(value)) return value.map(withoutCredentials)
    if (!value || typeof value !== 'object') return value
    const result = {}
    const credentialParameter = /(?:api[_-]?key|password|secret|access[_-]?token|auth[_-]?token)/i.test(value.name || '')
    for (const [key, item] of Object.entries(value)) {
        if (/(?:api[_-]?key|password|secret|access[_-]?token|auth[_-]?token)/i.test(key)) continue
        if (credentialParameter && ['value', 'default_value'].includes(key)) result[key] = null
        else result[key] = withoutCredentials(item)
    }
    return result
}
