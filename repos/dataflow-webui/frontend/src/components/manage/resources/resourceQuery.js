export function filtersFromQuery(query) {
    return { source: query.source === 'builtin' ? 'builtin' : 'user', search:String(query.q || ''),usage:String(query.usage || ''),purpose:String(query.purpose || ''),pipeline:String(query.pipeline || ''),operator:String(query.operator || ''),relation:query.relation === 'compatible' ? 'compatible' : 'referenced' }
}
export function queryForFilters(previous, filters) {
    const query = {...previous}
    const values = {source:filters.source === 'builtin' ? 'builtin' : '',q:filters.search,usage:filters.usage,purpose:filters.purpose,pipeline:filters.pipeline,operator:filters.operator,relation:filters.relation === 'compatible' ? 'compatible' : ''}
    for(const [key,value] of Object.entries(values)){if(value)query[key]=value;else delete query[key]}
    return query
}
