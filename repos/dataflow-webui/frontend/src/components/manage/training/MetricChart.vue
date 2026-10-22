<template>
    <div>
        <p v-if="!series.length">
            未提供可绘制的 {{ kind === 'training' ? '训练' : '策略' }} 指标。
        </p>
        <div v-else class="chart">
            <canvas
                ref="canvas"
                :aria-label="kind === 'training' ? '训练指标曲线' : '策略指标曲线'"
                role="img"
            />
        </div>
    </div>
</template>
<script>
import { Chart, registerables } from 'chart.js'
Chart.register(...registerables)
function flatten(row, prefix = '') {
    const out = {}
    for (const [k, v] of Object.entries(row)) {
        const name = prefix ? prefix + '.' + k : k
        if (typeof v === 'number' && Number.isFinite(v)) out[name] = v
        else if (v && typeof v === 'object') Object.assign(out, flatten(v, name))
    }
    return out
}
export default {
    props: {
        rows: { type: Array, default: () => [] },
        kind: { default: 'training' },
        theme: String
    },
    computed: {
        series() {
            const flat = this.rows.map((r) => flatten(r))
            const keys = [...new Set(flat.flatMap(Object.keys))].filter(
                (k) => !['step', 'current_steps', 'global_step'].includes(k)
            )
            return keys.map((key, i) => ({
                label: key,
                data: flat.map((r, index) => ({
                    x: r.step ?? r.current_steps ?? r.global_step ?? index,
                    y: r[key] ?? null
                })),
                yAxisID: key === 'learning_rate' ? 'lr' : 'y',
                borderColor: ['#8995ff', '#e8ab69', '#69c9b9', '#c894e1'][i % 4],
                pointRadius: 2,
                tension: 0.1
            }))
        }
    },
    mounted() {
        this.draw()
    },
    activated() {
        this.$nextTick(() => this.draw())
    },
    beforeUnmount() {
        this.chart?.destroy()
    },
    watch: {
        rows: {
            deep: true,
            handler() {
                this.$nextTick(() => this.draw())
            }
        },
        theme() {
            this.$nextTick(() => this.draw())
        }
    },
    methods: {
        draw() {
            this.chart?.destroy()
            if (!this.$refs.canvas || !this.series.length) return
            const color = this.theme === 'dark' ? '#dfe5ef' : '#46516a'
            const grid = this.theme === 'dark' ? '#414957' : '#e1e5ed'
            const scales = {
                x: {
                    type: 'linear',
                    title: { display: true, text: 'step / record index', color },
                    ticks: { color },
                    grid: { color: grid }
                },
                y: { beginAtZero: false, ticks: { color }, grid: { color: grid } }
            }
            if (this.series.some((s) => s.yAxisID === 'lr'))
                scales.lr = {
                    position: 'right',
                    title: { display: true, text: 'learning rate', color },
                    ticks: { color },
                    grid: { drawOnChartArea: false }
                }
            this.chart = new Chart(this.$refs.canvas, {
                type: 'line',
                data: { datasets: this.series },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    parsing: false,
                    animation: false,
                    scales,
                    plugins: { legend: { labels: { color } } }
                }
            })
        }
    }
}
</script>
<style scoped>
.chart {
    position: relative;
    height: 280px;
    width: 100%;
    min-width: 0;
}
canvas {
    width: 100% !important;
    height: 100% !important;
}
</style>
