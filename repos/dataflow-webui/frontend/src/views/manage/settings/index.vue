<template>
    <div class="df-settings-container" :class="[{ dark: theme === 'dark' }]">
        <div class="major-container">
            <div class="title-block">
                <p class="main-title">{{ local('Settings') }}</p>
            </div>
            <div class="content-block">
                <fv-Collapse :theme="theme" class="serving-item" :icon="theme === 'light' ? 'Light' : 'QuietHours'"
                    :title="local('Switch Theme')" :content="local('Change the theme of the DataFlow WebUI.')"
                    :disabled-collapse="true" :max-height="'auto'">
                    <template #extension>
                        <fv-toggle-switch :theme="theme" v-model="themeModel" :on="local('Dark')"
                            :off="local('Light')"></fv-toggle-switch>
                    </template>
                </fv-Collapse>
                <fv-Collapse :theme="theme" class="serving-item" icon="LocaleLanguage" :title="local('Language')"
                    :content="local('Change the language of the DataFlow WebUI.')" :disabled-collapse="true"
                    :max-height="'auto'">
                    <template #extension>
                        <fv-combobox :theme="theme" v-model="languageModel" :options="languageList"
                            style="width: 120px;"></fv-combobox>
                    </template>
                </fv-Collapse>
                <fv-Collapse :theme="theme" class="serving-item" icon="FolderOpen" title="运行结果目录" :content="outputRoot || '读取中…'" :max-height="300">
                    <div class="result-storage-settings">
                        <p>每次运行创建独立子目录，保留最终结果、中间文件与日志。运行前可临时更改位置。</p>
                        <fv-button :theme="theme" icon="FolderOpen" :disabled="savingStorage" :border-radius="6" style="margin-bottom:8px" @click="chooseOutputRoot">选择文件夹</fv-button>
                        <fv-text-box v-model="outputRoot" :theme="theme" aria-label="默认结果根目录" placeholder="输入本机绝对目录路径" :border-radius="6" style="width:100%;height:38px" />
                        <p v-if="storageError" role="alert" class="storage-error">{{ storageError }}</p><p v-if="storageNotice" role="status">{{ storageNotice }}</p>
                        <fv-button :theme="theme" :disabled="savingStorage || !outputRoot.trim()" :border-radius="6" style="margin-top:12px" @click="saveOutputRoot">{{ savingStorage ? '正在保存…' : '保存默认目录' }}</fv-button>
                    </div>
                </fv-Collapse>
            </div>
        </div>
    </div>
</template>

<script>
import { useUnsavedChanges, confirmDiscard } from '@/components/manage/forms/unsaved'
import { mapState, mapActions } from 'pinia'
import axios from 'axios'
import {publishChange,subscribeChanges} from '@/components/manage/forms/changes'
import { useAppConfig } from '@/stores/appConfig'
import { useTheme } from '@/stores/theme'

export default {
 setup(){useUnsavedChanges(vm=>vm.rootDirty,vm=>{vm.outputRoot=vm.savedOutputRoot})},
    name: 'DataflowSettings',
    data() {
        return {
            savedOutputRoot:'', rootVersion:0, stopChanges:null, outputRoot: '', storageError: '', storageNotice: '', savingStorage: false,
            languageList: [
                {
                    key: 'en',
                    text: 'English'
                },
                {
                    key: 'cn',
                    text: '中文'
                }
            ],
            lock: {
                update: true
            }
        }
    },
    watch: {
        language() {
            this.reviseConfig()
        },
        theme() {
            this.reviseConfig()
        }
    },
    computed: {
        rootDirty(){return this.outputRoot!==this.savedOutputRoot},
        ...mapState(useAppConfig, ['local', 'language']),
        ...mapState(useTheme, ['theme', 'color', 'gradient']),
        themeModel: {
            get() {
                if (this.theme == undefined) return false
                return this.theme === 'light' ? false : true
            },
            set(val) {
                this.reviseTheme(val ? 'dark' : 'light')
            }
        },
        languageModel: {
            get() {
                if (this.language == undefined) return {
                    key: 'en',
                    text: 'English'
                }
                return this.languageList.find(item => item.key === this.language)
            },
            set(val) {
                let language = this.languageList.find(item => item.key === val.key)
                if (language) {
                    this.reviseLanguage(language.key)
                }
            }
        },
    },
    mounted() {
        this.getConfig()
        this.loadOutputRoot()
        this.stopChanges=subscribeChanges(change=>{if(change.topic==='result-storage'){if(this.rootDirty)this.storageNotice='默认目录已在其他页面更新，当前输入已保留。';else this.loadOutputRoot()}})
    },
    activated(){if(!this.rootDirty)this.loadOutputRoot()},
    beforeUnmount(){this.stopChanges?.()},
    methods: {
        async loadOutputRoot() {
            const version=++this.rootVersion
            try { const r = await axios.get('/api/v1/tasks/result-storage'); if (!r.data.success) throw new Error(r.data.message); if(version===this.rootVersion && !this.rootDirty){this.outputRoot = r.data.data.output_root;this.savedOutputRoot=this.outputRoot} }
            catch(e) { if(version===this.rootVersion)this.storageError = e.message }
        },
        async chooseOutputRoot() {
            this.savingStorage=true;this.storageError='';try{const r=await axios.post('/api/v1/tasks/result-storage/choose');if(!r.data.success)throw new Error(r.data.message);if(!r.data.data.cancelled)this.outputRoot=r.data.data.output_root}catch(e){this.storageError=e.response?.data?.message||e.message}finally{this.savingStorage=false}
        },
        async saveOutputRoot() {
            if (this.savingStorage) return
            this.savingStorage = true; this.storageError = ''; this.storageNotice = ''
            try { const r = await axios.put('/api/v1/tasks/result-storage', {output_root:this.outputRoot}); if (!r.data.success) throw new Error(r.data.message); this.outputRoot = r.data.data.output_root;this.savedOutputRoot=this.outputRoot;publishChange('result-storage'); this.storageNotice = '默认结果目录已保存。' }
            catch(e) { this.storageError = e.response?.data?.message || e.message }
            finally { this.savingStorage = false }
        },
        ...mapActions(useAppConfig, ['reviseLanguage']),
        ...mapActions(useTheme, ['reviseTheme']),
        getConfig() {
            this.$api.preferences.get_preferences_api_v1_preferences__get().then(res => {
                if (res.code === 200) {
                    if (res.data.language) {
                        this.reviseLanguage(res.data.language)
                    }
                    if (res.data.theme) {
                        this.reviseTheme(res.data.theme)
                    }
                }
            })
        },
        reviseConfig() {
            if (!this.lock.update) return
            this.lock.update = false
            this.$api.preferences.set_preferences_api_v1_preferences__post({
                language: this.language,
                theme: this.theme
            }).then(res => {
                if (res.code === 200) {
                    this.lock.update = true
                }
            }).finally(() => {
                this.lock.update = true
            })
        }
    }
}
</script>

<style lang="scss">
.result-storage-settings{padding:16px;line-height:1.7;font-size:13px}.storage-error{color:#b63830}
.df-settings-container {
    position: relative;
    width: 100%;
    height: 100%;
    background-color: rgba(241, 241, 241, 1);
    display: flex;
    justify-content: center;

    &.dark {
        background: rgba(36, 36, 36, 1);

        .major-container {
            .title-block {
                .main-title {
                    color: whitesmoke;
                }
            }
        }
    }

    .major-container {
        width: 100%;
        max-width: 1200px;
        height: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;

        .title-block {
            position: absolute;
            width: 100%;
            padding: 15px;
            padding-top: 30px;
            z-index: 1;
            backdrop-filter: blur(20px);

            .main-title {
                font-size: 28px;
                font-weight: 400;
                color: rgba(26, 26, 26, 1);
            }
        }

        .content-block {
            position: relative;
            width: 100%;
            height: 100%;
            gap: 5px;
            padding: 15px;
            padding-top: 100px;
            display: flex;
            flex-direction: column;
            overflow: overlay;

            .serving-item {
                flex-shrink: 0;

                .collapse-item-content {
                    position: relative;
                    height: auto;
                    transition: all 0.3s;
                }

                .serving-item-title {
                    margin: 5px 0px;
                    font-size: 13.8px;
                    font-weight: bold;
                    color: rgba(123, 139, 209, 1);
                    user-select: none;
                }

                .serving-item-light-title {
                    margin: 5px 0px;
                    font-size: 12px;
                    color: rgba(95, 95, 95, 1);
                    user-select: none;
                }

                .serving-item-info {
                    margin: 5px 0px;
                    font-size: 12px;
                    color: rgba(120, 120, 120, 1);
                    user-select: none;
                }

                .serving-item-std-info {
                    font-size: 13.8px;
                    color: rgba(27, 27, 27, 1);
                    user-select: none;
                }

                .serving-item-bold-info {
                    margin: 5px 0px;
                    font-size: 16px;
                    font-weight: bold;
                    color: rgba(27, 27, 27, 1);
                    user-select: none;
                }

                .serving-item-p-block {
                    position: relative;
                    width: 100%;
                    height: auto;
                    padding: 15px 0px;
                    box-sizing: border-box;
                    line-height: 3;
                    display: flex;
                    flex-direction: column;
                }

                .serving-item-row {
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
        }
    }

    .rainbow {
        @include color-rainbow;

        color: black;
    }

    .ring-animation {
        animation: ring-rotate 1s linear infinite;
    }

    @keyframes ring-rotate {
        0% {
            transform: rotate(0deg);
        }

        100% {
            transform: rotate(360deg);
        }
    }
}
</style>
