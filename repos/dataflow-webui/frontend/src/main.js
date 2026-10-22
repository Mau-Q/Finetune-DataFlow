import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import TeamShell from './components/manage/team/TeamShell.vue'
import { h } from 'vue'
import router from './router'

import VueFluent from "@creatorsn/vfluent3";
import '@creatorsn/vfluent3/style.css';

import apiPlugin from '@/axios'

import { installInteractions } from '@/components/general/interactions'

const app = createApp({render:()=>h(TeamShell,null,{default:()=>h(App)})})
installInteractions(app)
app.use(VueFluent);

app.use(createPinia())
app.use(router)

app.config.globalProperties.$Go = (str) => {
    router.push(str)
}

app.config.globalProperties.$Back = () => {
    router.back()
}

app.config.globalProperties.$Jump = (str) => {
    window.open(str)
}

app.config.globalProperties.$Guid = () => {
    let guid = app.config.globalProperties.$SUtility.Guid();
    guid = guid.split('-')[0];
    return guid;
}

app.use(apiPlugin);

app.mount('#app')
