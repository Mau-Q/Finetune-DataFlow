<template>
    <div class="manage-container" :class="[{ dark: theme === 'dark' }]">
        <div class="manage-content-block">
            <aside class="manage-sidebar" :style="{ width: isExpand ? '240px' : '50px' }">
            <fv-navigation-view
                :theme="theme"
                v-model="currentNav"
                :title="''"
                :options="navigationOptions"
                v-model:expand="isExpand"
                :foreground="color"
                :background="theme === 'dark' ? 'rgba(36, 36, 36, 1)' : ''"
                expand-width="240"
                :flyout-display="1368"
                :mobile-display="1024"
                class="navigation-view"
                :show-back="false"
                :show-search="false"
                :setting-title="local('设置')"
                @item-click="handleItemClick"
                @setting-click="handleSettingClick"
                @back="$Back()"
            >
                <template v-slot:banner>
                    <div class="title-block name">
                        <img class="nav-icon" :src="img.logo" alt="" />
                        <p v-show="isExpand" class="title">{{ local(`DataFlow`) }}</p>
                    </div>
                </template>
                <template v-slot:listItem="x">
                    <div
                        class="nav-item"
                        :class="{
                            collapse: !isExpand,
                            'nav-group': x.item.type === 'header',
                            'is-active': x.item.type !== 'header' && (teamWorkspace?.active.value ? x.item.key === 'team-workspace' : currentNav.key === x.item.key)
                        }"
                        :title="x.valueTrigger(x.item.name)"
                    >
                        <svg
                            v-if="x.item.type !== 'header'"
                            class="nav-item-icon"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.7"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            aria-hidden="true"
                        >
                            <path :d="x.item.svg" />
                        </svg>
                        <p class="name">{{ x.valueTrigger(x.item.name) }}</p>
                    </div>
                </template>
            </fv-navigation-view>
            <div v-if="teamWorkspace && teamEnabled" class="sidebar-account" :class="{ compact: !isExpand }">
                <span v-if="isExpand" class="sidebar-account-name">{{ teamWorkspace.user.value.name }}</span>
                <button type="button" title="退出登录" aria-label="退出登录" @click="teamWorkspace.logout">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M9 4H4v16h5 M13 8l4 4-4 4 M8 12h13" /></svg>
                    <span v-if="isExpand">退出</span>
                </button>
            </div>
            </aside>
            <div v-if="teamWorkspace?.active.value" class="team-workspace-content">
                <TeamWorkspace
                    :user="teamWorkspace.user.value"
                    :project="teamWorkspace.project.value"
                    :selection="teamWorkspace.selection.value"
                    @refresh="teamWorkspace.refresh"
                />
            </div>
            <router-view v-else v-slot="{ Component }">
                <KeepAlive>
                    <component :is="Component" />
                </KeepAlive>
            </router-view>
        </div>
    </div>
</template>

<script>
import { mapState } from 'pinia'
import { useAppConfig } from '@/stores/appConfig'
import { useTheme } from '@/stores/theme'

import logo from '@/assets/logo/logo.png'
import TeamWorkspace from '@/components/manage/team/TeamWorkspace.vue'
import { team } from '@/components/manage/team/client'

export default {
    name: 'ManageShell',
    components: { TeamWorkspace },
    inject: { teamWorkspace: { default: null } },
    data() {
        return {
            currentNav: {
                key: 0,
                name: () => this.local('DataFlow'),
                icon: 'World',
                route: '/m/'
            },
            isExpand: window.innerWidth >= 1368,
            navList: [
                { key: 'flow-heading', name: () => this.local('流程'), type: 'header' },
                {
                    key: 0,
                    name: () => this.local('数据工作流'),
                    svg: 'M3 3h6v6H3z M15 15h6v6h-6z M15 3h6v6h-6z M9 6h6 M6 9v9h9',
                    route: '/m/'
                },
                { key: 0.3, name: () => this.local('模型训练'), svg: 'M4 4h16v16H4z M8 8h8v8H8z M12 1v3 M12 20v3', route: '/m/training' },
                { key: 'data-heading', name: () => this.local('数据'), type: 'header' },
                {
                    key: 0.1,
                    name: () => this.local('原始数据集'),
                    svg: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h5',
                    route: '/m/materials'
                },
                {
                    key: 0.2,
                    name: () => this.local('生成数据集'),
                    svg: 'M4 4h16v16H4z M4 9h16 M9 9v11 M13 13h4 M13 16h4',
                    route: '/m/training-datasets'
                },
                { key: 'resources-heading', name: () => this.local('资源管理'), type: 'header' },
                {
                    key: 2,
                    name: () => this.local('Prompt 模板'),
                    svg: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z M7 7h10 M7 11h7',
                    route: '/m/prompts'
                },
                {
                    key: 2.5,
                    name: () => this.local('JSON Schema'),
                    svg: 'M8 3H6v6l-3 3 3 3v6h2 M16 3h2v6l3 3-3 3v6h-2 M10 9h4 M10 15h4',
                    route: '/m/schemas'
                },
                {
                    key: 1,
                    name: () => this.local('模型服务'),
                    svg: 'M3 3h18v7H3z M3 14h18v7H3z M7 6.5h.01 M7 17.5h.01 M12 6.5h5 M12 17.5h5',
                    route: '/m/serving'
                },
                { key: 'analysis-heading', name: () => this.local('分析'), type: 'header' },
                {
                    key: 2.7,
                    name: () => this.local('数据可视化'),
                    svg: 'M3 3v18h18 M7 17v-4 M12 17V7 M17 17v-7',
                    route: '/m/dataviz'
                },
                {
                    key: 3,
                    name: () => this.local('数据分析'),
                    svg: 'M3 3v18h18 M6 15l5-5 4 3 6-8 M17 5h4v4',
                    route: '/m/analysis'
                },
                { key: 'home', name: () => this.local('Home'), route: '/', show: false }
            ],
            img: {
                logo: logo
            }
        }
    },
    watch: {
        $route() {
            this.routeFormat()
        }
    },
    computed: {
        teamEnabled() { return team.enabled },
        navigationOptions() {
            if (!team.enabled) return this.navList
            const items = [...this.navList]
            const index = items.findIndex(item => item.key === 'resources-heading')
            items.splice(index, 0, {
                key: 'team-workspace',
                name: () => this.local('协作与人工评测'),
                svg: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M22 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75',
                workspace: true
            })
            return items
        },
        ...mapState(useAppConfig, ['local']),
        ...mapState(useTheme, ['color', 'gradient', 'theme'])
    },
    mounted() {
        this.routeFormat()
    },
    methods: {
        handleItemClick(item) {
            if (item.workspace) {
                if (!this.teamWorkspace.show(true)) this.routeFormat()
                return
            }
            if (!item.route) return
            if (this.teamWorkspace && !this.teamWorkspace.show(false)) {
                this.currentNav = this.navigationOptions.find(item => item.workspace)
                return
            }
            // Navigation-view may emit selection while initializing. Keep canvas query state.
            if (item.route.replace(/\/$/, '') === this.$route.path.replace(/\/$/, '')) return
            this.$Go(`${item.route}`)
        },
        routeFormat() {
            let path = this.$route.path
            for (let item of this.navList) {
                if (!item.route || item.type === 'header') continue
                let targetPath = item.route
                if (path.replace(/\/$/, '') === targetPath.replace(/\/$/, '')) {
                    this.currentNav = item
                    break
                }
            }
        },
        handleSettingClick() {
            if (this.teamWorkspace && !this.teamWorkspace.show(false)) return
            this.$Go('/m/settings')
        }
    }
}
</script>

<style lang="scss">
.manage-container {
    @include app;

    background: rgba(250, 250, 250, 1);
    display: flex;
    flex-direction: column;

    .manage-sidebar {
        display: flex;
        flex-direction: column;
        flex-shrink: 0;
        min-height: 0;
        .navigation-view { flex: 1; min-height: 0; height: 0; }
    }
    .sidebar-account {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        min-height: 54px;
        border-top: 1px solid #e0e4ed;
        color: #67738a;
        font-size: 13px;
        .sidebar-account-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
        button { display: flex; align-items: center; gap: 6px; padding: 6px; background: transparent; border: 0; border-radius: 6px; color: inherit; cursor: pointer; font: inherit; }
        button:hover { color: #535fd6; background: #ebeefd; }
        svg { width: 17px; height: 17px; }
        &.compact { padding: 10px 8px; justify-content: center; }
    }
    &.dark .sidebar-account { border-color: #394052; color: #a0abc2; button:hover { background: #323c61; color: #b7c0ff; } }

    .team-workspace-content {
        flex: 1;
        min-width: 0;
        overflow: auto;
    }

    &.dark {
        background: rgba(36, 36, 36, 1);

        .manage-content-block {
            .navigation-view {
                .title-block {
                    .title {
                        color: whitesmoke;
                    }
                }
            }
        }
    }

    .manage-content-block {
        position: relative;
        width: 100%;
        flex: 1;
        box-sizing: border-box;
        display: flex;
        overflow: hidden;

        .navigation-view {
            z-index: 2;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;

            .title-block {
                @include Vcenter;

                position: relative;
                width: 100%;
                height: 60px;
                padding: 0px 10px;
                user-select: none;

                .nav-icon {
                    width: 28px;
                    height: auto;
                    margin-left: 5px;
                    object-fit: cover;
                }

                .title {
                    @include color-dataflow-title;

                    margin-left: 5px;
                    font-size: 20px;
                    font-weight: 600;
                    color: rgba(0, 0, 0, 1);
                }
            }

            .navigation-list .list-view-item {
                border-radius: 7px;
                margin: 2px 6px;
                width: calc(100% - 12px);
                &:hover {
                    background: rgba(90, 101, 218, 0.06);
                }
                &:has(.nav-group) {
                    margin-top: 18px;
                    pointer-events: none;
                }
                &:first-child {
                    margin-top: 0;
                }
            }

            .nav-item {
                @include Vcenter;
                position: relative;
                width: 100%;
                height: 42px;
                gap: 10px;
                color: #39465d;
                user-select: none;
                border-radius: 7px;
                .name {
                    padding: 0;
                    font-size: 14px;
                    color: inherit;
                }
                &.is-active {
                    background: #ebeefd;
                    color: #535fd6;
                    .name {
                        font-weight: 600;
                    }
                }
                &.nav-group {
                    height: 28px;
                    padding-left: 14px;
                    box-sizing: border-box;
                    color: #8690a1;
                    .name {
                        font-size: 12px;
                        font-weight: 500;
                    }
                }
                &.collapse {
                    justify-content: center;
                    .nav-item-icon {
                        margin-left: 0;
                    }
                }
                .nav-item-icon {
                    width: 18px;
                    height: 18px;
                    margin-left: 14px;
                    flex-shrink: 0;
                }
            }
        }
    }
    &.dark .navigation-view .nav-item {
        color: #c9d1df;
        &.nav-group {
            color: #939eaf;
        }
        &.is-active {
            background: #323c61;
            color: #b7c0ff;
        }
    }
}
</style>
