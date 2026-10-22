// Add browser semantics to the existing Fluent controls without changing their rendering.
export function installInteractions(app) {
    app.mixin({
        mounted(){ this.enhanceFluentControl() },
        updated(){ this.enhanceFluentControl() },
        methods:{enhanceFluentControl(){
            const root=this.$el
            if (!root?.setAttribute) return
            if (this.$options.name==='FvButton') {
                const disabled=this.isDisabled
                root.setAttribute('role','button'); root.tabIndex=disabled?-1:0
                root.setAttribute('aria-disabled',String(!!disabled))
                const label=this.$attrs['aria-label'] || this.$attrs.title
                if(label)root.setAttribute('aria-label',label)
                if(!root.__fluentKeyboard){
                    root.__fluentKeyboard=true
                    root.addEventListener('keydown',event=>{
                        if(event.target!==root || !['Enter',' '].includes(event.key))return
                        event.preventDefault()
                        if(root.getAttribute('aria-disabled')!=='true' && !event.repeat)root.click()
                    })
                }
                // The library's fallback slot literally says "Button" for icon-only controls.
                if(this.icon && label){for(const node of [root,...root.querySelectorAll('*')]){for(const child of node.childNodes){if(child.nodeType===3 && child.textContent.trim()==='Button')child.textContent=''}}}
            }
            if(['FvTextBox','FvTextField','FvCombobox'].includes(this.$options.name)){
                const input=root.querySelector('input,textarea')
                const label=this.$attrs['aria-label'] || this.placeholder
                if(input && label)input.setAttribute('aria-label',label)
            }
        }}
    })
}
