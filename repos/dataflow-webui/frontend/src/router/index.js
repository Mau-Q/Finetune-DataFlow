import { createRouter, createWebHashHistory } from 'vue-router'

import tool from './tools'

import Manage from './Manage'

import home from '@/views/client/home/index.vue'

const router = createRouter({
    history: createWebHashHistory(import.meta.env.BASE_URL),
    routes: [
        {
            path: '/',
            name: 'home',
            component: home,
            meta: {
                title: 'Dataflow'
            }
        },
        Manage
    ]
})

router.afterEach((to, from, failure) => {
    if (!failure && to.meta.title) {
        document.title = to.meta.title
    }
})

export default router
