import { defineAsyncComponent, h } from 'vue'
import loading from "@/components/general/loading.vue";

const AsyncLoad = function (component) {
    const AsyncComp = defineAsyncComponent({
        loader: component,
        loadingComponent: loading,
        errorComponent: {render(){return h('section', {role:'alert',style:'padding:32px'}, [h('p','页面加载失败，请检查本地服务后重试。'),h('button',{onClick:()=>window.location.reload()},'重新加载')])}},
        delay: 200,
        timeout: 10000
    });
    return Promise.resolve({
        render() {
            return h(AsyncComp);
        }
    });
};

export default {
    AsyncLoad
};