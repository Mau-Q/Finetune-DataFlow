const DEFAULT_LAYOUT = {
    columns: 4,
    startX: 350,
    startY: 160,
    gapX: 320,
    gapY: 230,
    datasetX: 30
}

const stableNodeCompare = (a, b) => {
    const aStep = Number(a.data?.pipeline_idx)
    const bStep = Number(b.data?.pipeline_idx)
    const aHasStep = Number.isFinite(aStep)
    const bHasStep = Number.isFinite(bStep)

    if (aHasStep && bHasStep && aStep !== bStep) return aStep - bStep
    if (aHasStep !== bHasStep) return aHasStep ? -1 : 1
    if ((a.position?.y || 0) !== (b.position?.y || 0)) {
        return (a.position?.y || 0) - (b.position?.y || 0)
    }
    if ((a.position?.x || 0) !== (b.position?.x || 0)) {
        return (a.position?.x || 0) - (b.position?.x || 0)
    }
    return String(a.id).localeCompare(String(b.id))
}

const isNodeEdge = (edge) => edge.data?.edgeType === 'node'
    || (edge.sourceHandle === 'node::source::node' && edge.targetHandle === 'node::target::node')

export const stableTopologicalOrder = (nodes, edges) => {
    const nodeMap = new Map(nodes.map((node) => [node.id, node]))
    const outgoing = new Map(nodes.map((node) => [node.id, new Set()]))
    const indegree = new Map(nodes.map((node) => [node.id, 0]))

    edges.filter(isNodeEdge).forEach((edge) => {
        if (!nodeMap.has(edge.source) || !nodeMap.has(edge.target)) return
        if (outgoing.get(edge.source).has(edge.target)) return
        outgoing.get(edge.source).add(edge.target)
        indegree.set(edge.target, indegree.get(edge.target) + 1)
    })

    const ready = nodes.filter((node) => indegree.get(node.id) === 0).sort(stableNodeCompare)
    const ordered = []

    while (ready.length) {
        const node = ready.shift()
        ordered.push(node)
        outgoing.get(node.id).forEach((targetId) => {
            indegree.set(targetId, indegree.get(targetId) - 1)
            if (indegree.get(targetId) === 0) {
                ready.push(nodeMap.get(targetId))
                ready.sort(stableNodeCompare)
            }
        })
    }

    return {
        ordered,
        hasCycle: ordered.length !== nodes.length
    }
}

export const buildSnakeLayout = (nodes, edges, options = {}) => {
    const layout = { ...DEFAULT_LAYOUT, ...options }
    const { ordered, hasCycle } = stableTopologicalOrder(nodes, edges)
    if (hasCycle) return { positions: new Map(), hasCycle }

    const positions = new Map()
    const datasetNodes = ordered.filter((node) => node.type === 'database-node')
    const operatorNodes = ordered.filter((node) => node.type === 'operator-node')
    const otherNodes = ordered.filter(
        (node) => node.type !== 'database-node' && node.type !== 'operator-node'
    )

    datasetNodes.forEach((node, index) => {
        positions.set(node.id, {
            x: layout.datasetX,
            y: layout.startY + index * layout.gapY
        })
    })

    operatorNodes.forEach((node, index) => {
        const row = Math.floor(index / layout.columns)
        const columnInRow = index % layout.columns
        const column = row % 2 === 0
            ? columnInRow
            : layout.columns - 1 - columnInRow
        positions.set(node.id, {
            x: layout.startX + column * layout.gapX,
            y: layout.startY + row * layout.gapY
        })
    })

    otherNodes.forEach((node, index) => {
        const operatorRows = Math.max(1, Math.ceil(operatorNodes.length / layout.columns))
        positions.set(node.id, {
            x: layout.startX + (index % layout.columns) * layout.gapX,
            y: layout.startY + (operatorRows + Math.floor(index / layout.columns)) * layout.gapY
        })
    })

    return { positions, hasCycle }
}
