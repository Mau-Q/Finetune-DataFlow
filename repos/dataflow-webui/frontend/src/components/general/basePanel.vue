<template>
    <fv-panel
        v-model="thisValue"
        :title="title"
        :theme="theme"
        :width="width"
        :height="height"
        :background="theme === 'dark' ? 'rgba(0, 0, 0, 0.8)' : 'rgba(250, 250, 250, 0.3)'"
        :title-size="18"
        :isAcrylic="true"
        :is-central-side="true"
        :is-footer="isFooter"
        :teleport="teleport"
    >
        <template v-slot:container>
            <div ref="content" class="base-panel-container" tabindex="-1" @keyup.enter="confirmFromKeyboard">
                <slot name="content"></slot>
            </div>
        </template>
        <template v-slot:footer>
            <div class="bp-control">
                <slot name="control" :close="close">
                    <fv-button></fv-button>
                </slot>
            </div>
        </template>
    </fv-panel>
</template>

<script>
export default {
    props: {
        busy:{type:Boolean,default:false},
        beforeClose:{type:Function,default:null},
        modelValue: {
            default: true
        },
        title: {
            default: 'Title'
        },
        width: {
            default: '800px'
        },
        height: {
            default: '80%'
        },
        isFooter: {
            default: true
        },
        teleport: {
            default: false
        },
        theme: {
            default: 'light'
        }
    },
    emits:['update:modelValue','confirm'],
    mounted(){if(this.thisValue)this.$nextTick(this.activateDialog)},
    beforeUnmount(){this.releaseDialog()},
    data() {
        return {
            thisValue: this.modelValue
        }
    },
    watch: {
        modelValue(val) {
            this.thisValue = val
            if(val)this.$nextTick(this.activateDialog);else this.releaseDialog()
        },
        async thisValue(val) {
            if(!val && this.modelValue && this.beforeClose){
                if(this.checkingClose)return
                this.checkingClose=true
                let allowed=false
                try{allowed=!this.busy && await this.beforeClose()}finally{this.checkingClose=false}
                if(!allowed){this.thisValue=true;return}
            }
            this.$emit('update:modelValue', val)
            if(val)this.$nextTick(this.activateDialog);else this.releaseDialog()
        }
    },
    methods: {
        confirmFromKeyboard(event){if(event.target.tagName==='TEXTAREA' || event.target.closest('form') || event.target.closest('[role="button"]'))return;this.$emit('confirm')},
        activateDialog(){
            if(this.dialogHandler || !this.thisValue)return
            const content=this.$refs.content
            if(!content)return
            const panel=content.closest('.fv-panel-container') || content
            panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-label',this.title)
            this.previousFocus=document.activeElement
            const focusables=()=>[...panel.querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]')].filter(el=>el.getClientRects().length && el.getAttribute('aria-disabled')!=='true')
            this.dialogHandler=event=>{
                // A nested confirmation dialog owns its own keyboard interaction.
                if(!panel.contains(document.activeElement))return
                if(event.key==='Escape'){event.preventDefault();event.stopPropagation();this.close()}
                if(event.key==='Tab'){
                    const items=focusables(),first=items[0]||content,last=items.at(-1)||content
                    if(!items.length || event.shiftKey && document.activeElement===first || !event.shiftKey && document.activeElement===last){event.preventDefault();(event.shiftKey?last:first).focus()}
                }
            }
            panel.addEventListener('keydown',this.dialogHandler)
            this.dialogElement=panel
            const close=panel.querySelector('.control-btn')
            if(close){close.setAttribute('role','button');close.setAttribute('aria-label','关闭');close.tabIndex=0;close.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();close.click()}}}
            ;(focusables().find(el=>el.matches('input,textarea')) || focusables()[0] || content).focus()
        },
        releaseDialog(){
            this.dialogElement?.removeEventListener('keydown',this.dialogHandler)
            this.dialogHandler=null;this.dialogElement=null
            if(this.previousFocus?.isConnected)this.previousFocus.focus()
            this.previousFocus=null
        },
        close() {
            if(this.busy)return
            this.thisValue = false
        }
    }
}
</script>

<style lang="scss">
.fv-panel-container:has(.base-panel-container) { max-width:calc(100vw - 24px); max-height:calc(100dvh - 24px); }
.base-panel-container {
    position: relative;
    width: 100%;
    height: 100%;
    padding: 15px;
    color: rgba(28, 30, 41, 1);
    font-family:
        Akkurat Std,
        -apple-system,
        BlinkMacSystemFont,
        Segoe UI,
        Roboto,
        Oxygen,
        Ubuntu,
        Cantarell,
        Helvetica Neue,
        sans-serif;
    font-weight: 400;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    overflow: hidden;

    .bp-title {
        margin: 5px 0px;
        font-size: 13.8px;
        font-weight: bold;
        color: rgba(123, 139, 209, 1);
        user-select: none;
    }

    .bp-light-title {
        margin: 5px 0px;
        font-size: 12px;
        color: rgba(95, 95, 95, 1);
        user-select: none;
    }

    .bp-info {
        margin: 5px 0px;
        font-size: 12px;
        color: rgba(120, 120, 120, 1);
        user-select: none;
    }

    .bp-std-info {
        font-size: 13.8px;
        color: rgba(27, 27, 27, 1);
        user-select: none;
    }

    .bp-bold-info {
        margin: 5px 0px;
        font-size: 16px;
        font-weight: bold;
        color: rgba(27, 27, 27, 1);
        user-select: none;
    }

    .bp-p-block {
        position: relative;
        width: 100%;
        height: auto;
        padding: 15px 0px;
        box-sizing: border-box;
        line-height: 3;
        display: flex;
        flex-direction: column;
    }

    .bp-row {
        position: relative;
        width: 100%;
        padding: 0px 42px;
        flex-wrap: wrap;
        box-sizing: border-box;
        display: flex;
        align-items: center;

        &.no-pad {
            padding: 0px;
        }

        &.sep {
            justify-content: space-between;
        }

        &.column {
            flex-direction: column;
            align-items: flex-start;
        }

        &.full {
            flex: 1;
        }

        &.auto {
            overflow: auto;
        }
    }

    hr {
        margin: 10px 0px;
        border: none;
        border-top: rgba(120, 120, 120, 0.1) solid thin;
    }
}

.bp-control {
    position: relative;
    width: 100%;
    height: auto;
    padding: 15px 0px;
    gap: 5px;
    box-sizing: border-box;
    display: flex;
    justify-content: flex-end;
}
</style>
