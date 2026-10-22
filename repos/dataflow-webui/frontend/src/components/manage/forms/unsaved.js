import { getCurrentInstance, onMounted, onBeforeUnmount, onActivated, onDeactivated } from 'vue'

export function confirmAction(vm, message, status = 'warning') {
    return new Promise(resolve => {
        if (!vm.$infoBox) { resolve(window.confirm(message)); return }
        const previous=document.activeElement
        let box
        const finish=value=>{box?.removeEventListener('keydown',keyboard);resolve(value);if(previous?.isConnected)previous.focus()}
        const keyboard=event=>{
            const buttons=[...box.querySelectorAll('[role="button"],button')].filter(el=>el.getClientRects().length)
            if(event.key==='Escape'){event.preventDefault();buttons.at(-1)?.click()}
            if(event.key==='Tab' && buttons.length){const first=buttons[0],last=buttons.at(-1);if(event.shiftKey && document.activeElement===first || !event.shiftKey && document.activeElement===last){event.preventDefault();(event.shiftKey?last:first).focus()}}
        }
        vm.$infoBox(message, { title:'确认操作', status, theme: vm.theme || 'light', confirm: () => finish(true), cancel: () => finish(false) })
        box=document.getElementById('__fv-global-info-box__')
        if(box){box.setAttribute('role','alertdialog');box.setAttribute('aria-modal','true');box.setAttribute('aria-label',message);box.addEventListener('keydown',keyboard);queueMicrotask(()=>box.querySelectorAll('[role="button"],button').item(1)?.focus())}
    })
}
export const confirmDiscard = vm => confirmAction(vm, '有未保存的修改。放弃修改并继续？')

// Shared by nested editors as well as route views; KeepAlive editors only guard while active.
export function useUnsavedChanges(dirty, discard = () => {}) {
    const vm = getCurrentInstance().proxy
    let active = true, removeGuard
    const unload = event => { if (active && dirty(vm)) { event.preventDefault(); event.returnValue = '' } }
    const workspaceChange = event => { if(active && dirty(vm)){if(!window.confirm('有未保存的修改。放弃修改并继续？'))event.preventDefault();else discard(vm)} }
    onMounted(() => {
        window.addEventListener('dataflow-before-workspace-change', workspaceChange)
        window.addEventListener('beforeunload', unload)
        removeGuard = vm.$router.beforeEach(async () => {
            if (!active || !dirty(vm)) return true
            if (!await confirmDiscard(vm)) return false
            discard(vm)
            return true
        })
    })
    onActivated(() => { active = true })
    onDeactivated(() => { active = false })
    onBeforeUnmount(() => { removeGuard?.(); window.removeEventListener('dataflow-before-workspace-change', workspaceChange); window.removeEventListener('beforeunload', unload) })
}
