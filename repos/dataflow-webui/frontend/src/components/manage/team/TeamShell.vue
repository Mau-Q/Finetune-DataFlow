<template>
    <slot v-if="local" />
    <section v-else-if="!ready" class="team-login">
        <div class="login-card">
            <div class="brand">DataFlow</div>
            <h1>{{ development ? '本地开发工作区' : initialized ? '登录团队工作区' : '初始化团队工作区' }}</h1>
            <button v-if="development" class="primary" :disabled="busy" @click="enterDevelopment">进入本地工作区</button>
            <p v-if="!initialized && !development">
                请在部署主机运行管理员初始化命令，然后刷新页面。账号由管理员创建或邀请。
            </p>
            <form v-if="initialized" @submit.prevent="login">
                <label>账号<input v-model="name" autocomplete="username" required /></label
                ><label
                    >密码<input
                        v-model="password"
                        type="password"
                        autocomplete="current-password"
                        required /></label
                ><button class="primary" :disabled="busy">登录</button>
                <details>
                    <summary>接受邀请</summary>
                    <label>一次性邀请码<input v-model="invitation" autocomplete="off" /></label
                    ><button type="button" @click="accept">用上面的密码设置账号</button>
                </details>
            </form>
            <p class="team-error" role="alert">{{ error }}</p>
        </div>
    </section>
    <div v-else class="team-shell" :class="{ dark: theme.theme === 'dark' }">
        <button v-if="!project || !canDevelop" class="team-standalone-logout" @click="logout">退出</button>
        <main>
            <slot v-if="project && canDevelop" /><TeamWorkspace
                v-else-if="project"
                :user="user"
                :project="project"
                :selection="selection"
                @refresh="load"
            />
            <div v-else class="team-empty">
                暂无可用项目，请联系管理员分配项目权限。<TeamWorkspace
                    v-if="user.admin"
                    :user="user"
                    :project="null"
                    @refresh="load"
                />
            </div>
        </main>
        <p v-if="error" class="team-toast" role="alert">{{ error }}</p>
    </div>
</template>
<script setup>
import { ref, computed, onMounted, onBeforeUnmount, provide } from 'vue'
import { team, request } from './client'
import { shouldAutoLogin, markLoggedOut, clearLoggedOut } from './developmentSession.js'
import { useTheme } from '@/stores/theme'
import TeamWorkspace from './TeamWorkspace.vue'
const theme = useTheme(),
    local = ref(false),
    development = ref(false),
    ready = ref(false),
    initialized = ref(false),
    user = ref({ projects: [] }),
    name = ref(''),
    password = ref(''),
    invitation = ref(''),
    error = ref(''),
    busy = ref(false),
    workspace = ref(false)
const selection = ref(null)
const canLeave=()=>window.dispatchEvent(new Event('dataflow-before-workspace-change',{cancelable:true}))
function showWorkspace(value){if(value===workspace.value)return true;if(!canLeave())return false;workspace.value=value;return true}
const onOpen = (e) => {
    if(!canLeave())return
    selection.value = e.detail
    workspace.value = true
}
onMounted(() => window.addEventListener('dataflow-team-open', onOpen))
onBeforeUnmount(() => window.removeEventListener('dataflow-team-open', onOpen))
const project = computed(() => user.value.projects.find((p) => p.id === team.project)),
    roles = computed(() => project.value?.roles || []),
    canDevelop = computed(() => roles.value.some((r) => ['manage', 'develop'].includes(r)))
provide('teamWorkspace', { active: workspace, user, project, selection, show: showWorkspace, refresh: load, logout })
async function action(fn) {
    busy.value = true
    error.value = ''
    try {
        await fn()
    } catch (e) {
        error.value = e.message
    } finally {
        busy.value = false
    }
}
async function load() {
    user.value = await request('/team/me')
    team.viewer = user.value.id
    team.csrf = user.value.csrf
    team.project = user.value.project || ''
    const preferences=await request('/api/v1/preferences/')
    theme.reviseTheme(preferences.theme||'light')
    ready.value = true
}
async function login() {
    await action(async () => {
        const r = await request('/team/login', { name: name.value, password: password.value })
        team.csrf = r.csrf
        password.value = ''
        clearLoggedOut(sessionStorage)
        await load()
        if (!team.project && user.value.projects.length) {
            await request('/team/project', { project: user.value.projects[0].id })
            await load()
        }
    })
}
async function accept() {
    await action(async () => {
        await request('/team/accept', { invitation: invitation.value, password: password.value })
        invitation.value = ''
        password.value = ''
        error.value = '账号已设置，请登录。'
    })
}
async function logout() {
    if(!canLeave())return
    await action(async () => {
        await request('/team/logout', {})
        markLoggedOut(sessionStorage)
        window.location.reload()
    })
}
async function enterDevelopment() {
    await action(async () => {
        const result = await request('/team/dev-login', {})
        team.csrf = result.csrf
        clearLoggedOut(sessionStorage)
        initialized.value = true
        await load()
    })
}
onMounted(async () => {
    await action(async () => {
        const r = await fetch('/team/status')
        if (!r.ok) {
            local.value = true
            return
        }
        const status = await r.json()
        if (status.mode !== 'lan') {
            local.value = true
            return
        }
        team.enabled = true
        development.value = status.development === true
        team.development = development.value
        initialized.value = status.initialized
        if (initialized.value) {
            try { await load(); return }
            catch (e) { if (e.status !== 401) throw e }
        }
        if (shouldAutoLogin(status, sessionStorage)) {
            const result = await request('/team/dev-login', {})
            team.csrf = result.csrf
            initialized.value = true
            await load()
        }
    })
})
</script>
<style>
.team-shell,
.team-login {
    font-family:
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        'Segoe UI',
        sans-serif;
    color: #263047;
    background: #f7f8fc;
    --team-border: #e0e4ed;
    --team-panel: #fff;
    --team-muted: #67738a;
    --team-accent: #5163d1;
}
.team-shell.dark {
    color: #e5e8f2;
    background: #171b24;
    --team-border: #394052;
    --team-panel: #222836;
    --team-muted: #a0abc2;
    --team-accent: #a4b0ff;
}
.team-shell {
    height: 100dvh;
    display: flex;
    flex-direction: column;
}
.team-standalone-logout { position: fixed; top: 12px; right: 18px; z-index: 10; }
.team-shell > main {
    position: relative;
    flex: 1;
    min-height: 0;
    overflow: auto;
}
.team-shell #app {
    height: 100%;
}
.team-shell button,
.team-shell select,
.team-login button,
.team-login input {
    font: inherit;
    color: inherit;
    border: 1px solid var(--team-border, #dce1ed);
    border-radius: 6px;
    padding: 7px 12px;
    background: var(--team-panel, #fff);
}
.team-shell button,
.team-login button {
    cursor: pointer;
}
.team-shell button:hover {
    background: color-mix(in srgb, var(--team-accent) 8%, transparent);
}
.team-shell button.selected {
    color: var(--team-accent);
    background: color-mix(in srgb, var(--team-accent) 10%, transparent);
    border-color: transparent;
}
.team-login {
    height: 100dvh;
    display: grid;
    place-items: center;
}
.login-card {
    width: min(420px, 90vw);
    padding: 36px;
    background: white;
    border: 1px solid #e0e4ed;
    border-radius: 12px;
    box-shadow: 0 12px 40px #2434570a;
}
.brand {
    color: #5163d1;
    font-size: 26px;
    font-weight: 700;
}
.login-card h1 {
    font-size: 22px;
    margin: 20px 0;
}
.login-card p {
    line-height: 1.7;
}
.login-card label {
    display: grid;
    gap: 8px;
    margin: 18px 0;
}
.login-card input {
    width: 100%;
}
.login-card details {
    margin-top: 24px;
}
.primary {
    background: #5163d1 !important;
    border-color: #5163d1 !important;
    color: white !important;
}
.team-error {
    color: #b23d36;
    white-space: pre-wrap;
}
.team-toast {
    position: fixed;
    bottom: 18px;
    left: 25%;
    padding: 12px 24px;
    background: #fff1ee;
    color: #a72e28;
    border-radius: 8px;
    z-index: 10000;
}
.team-empty {
    padding: 48px;
    color: var(--team-muted);
}
</style>
