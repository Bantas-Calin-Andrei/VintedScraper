const DIMS = ['brand', 'type', 'size', 'price_band'];
const CHARTS = {};

async function loadCharts() {
  let data;
  try {
    const response = await fetch('/api/charts');
    if (!response.ok) return;
    data = await response.json();
  } catch (e) { return; }
  for (const dim of DIMS) {
    const series = data[dim] || [];
    const canvas = document.getElementById('chart-' + dim);
    document.getElementById('empty-' + dim).hidden = series.length > 0;
    canvas.parentElement.hidden = series.length === 0;
    const labels = series.map((s) => s.label);
    const values = series.map((s) => s.median_hours);
    if (CHARTS[dim]) {
      CHARTS[dim].$series = series;
      CHARTS[dim].data.labels = labels;
      CHARTS[dim].data.datasets[0].data = values;
      CHARTS[dim].update();
      continue;
    }
    const chart = new Chart(canvas, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Median hours to sell', data: values, backgroundColor: '#4f46e5', borderRadius: 4 }] },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false },
                   tooltip: { callbacks: { afterLabel: (ctx) => `${ctx.chart.$series[ctx.dataIndex].count} sold` } } },
        scales: { x: { beginAtZero: true, title: { display: true, text: 'hours' } } },
      },
    });
    chart.$series = series;
    CHARTS[dim] = chart;
  }
}

document.addEventListener('DOMContentLoaded', () => { loadCharts(); setInterval(loadCharts, 5 * 60 * 1000); });
