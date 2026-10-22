import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {reactive,markRaw,isProxy} from 'vue'
const source=readFileSync(new URL('./index.vue',import.meta.url),'utf8')
const script=source.match(/<script>([\s\S]*?)<\/script>/)[1].replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*\n/gm,'').replace(/^Chart\.register.*$/m,'').replace('export default','return')
class Chart {
 static register(){}
 constructor(canvas,config){this.canvas=canvas;this.config=config;this.destroyed=false}
 destroy(){assert.equal(isProxy(this),false,'Chart methods must never execute on Vue proxies');this.destroyed=true}
}
const options=new Function('mapState','useAppConfig','useTheme','NativeSelect','axios','Chart','markRaw',script)(()=>({}),()=>{},()=>{},{},{},Chart,markRaw)
function context(){
 const vm=reactive({...options.data(),$refs:{chartCanvas:{},nullChartCanvas:{}},theme:'light',local:value=>value})
 for(const [key,method] of Object.entries(options.methods))vm[key]=method.bind(vm)
 return vm
}
test('same-key option echoes retain loaded previews and cannot invalidate the request repeatedly',()=>{
 const vm=context();vm.selectedDataset={key:'draft:one'};vm.handleDatasetChange()
 vm.previewData=[{value:'retained'}];const rows=vm.previewData,version=vm.previewVersion
 vm.handleDatasetChange();assert.equal(vm.previewData,rows);assert.equal(vm.previewVersion,version)
 vm.selectedDataset.key='draft:two';vm.handleDatasetChange();assert.equal(vm.previewData.length,0);assert.equal(vm.previewVersion,version+1)
})
test('chart instances remain raw and cached-page deactivation releases charts and pending previews',()=>{
 const vm=context();vm.previewData=[{value:1},{value:2}];vm.selectedColumn='value';vm.columns=['value'];vm.nullCounts={value:0}
 vm.renderDistributionChart();vm.renderNullChart()
 const distribution=vm.chartInstance,missing=vm.nullChartInstance
 assert.equal(isProxy(distribution),false);assert.equal(isProxy(missing),false)
 vm.loading=true;const version=vm.previewVersion;options.deactivated.call(vm)
 assert.equal(vm.chartInstance,null);assert.equal(vm.nullChartInstance,null)
 assert.equal(distribution.destroyed,true);assert.equal(missing.destroyed,true)
 assert.equal(vm.loading,false);assert.equal(vm.previewVersion,version+1)
 vm.renderDistributionChart();assert.equal(vm.chartInstance,null,'inactive cached pages cannot recreate charts')
})
