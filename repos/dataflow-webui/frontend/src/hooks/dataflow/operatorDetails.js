// Cache metadata only for one graph load. Each node receives its own copy so
// editing one repeated operator cannot change another node's saved parameters.
export function createOperatorDetailLoader(fetchDetail) {
    const requests = new Map()
    return async (name) => {
        if (!requests.has(name)) {
            const request = Promise.resolve().then(() => fetchDetail(name)).then((response) => {
                if (response?.code !== 200) requests.delete(name)
                return response
            }, (error) => {
                requests.delete(name)
                throw error
            })
            requests.set(name, request)
        }
        const response = await requests.get(name)
        return response == null ? response : JSON.parse(JSON.stringify(response))
    }
}
