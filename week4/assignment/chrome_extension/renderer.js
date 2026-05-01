export class Renderer {
  constructor(container) {
    this.container = container;
    this.charts = [];
  }

  render(spec) {
    this.container.innerHTML = '';
    this.charts.forEach(c => c.destroy());
    this.charts = [];

    if (!spec || spec.template !== 'dashboard') {
      this.container.innerHTML = '<div class="empty-state">Invalid dashboard spec</div>';
      return;
    }

    const params = spec.params;
    const titleEl = document.createElement('h2');
    titleEl.className = 'card-title';
    titleEl.textContent = params.title || 'Dashboard';
    this.container.appendChild(titleEl);

    if (params.tabs && params.tabs.length > 0) {
      this.renderTabs(params.tabs);
    }
  }

  renderTabs(tabs) {
    const header = document.createElement('div');
    header.className = 'tabs-header';
    
    const content = document.createElement('div');
    content.className = 'tabs-content';

    tabs.forEach((tab, i) => {
      const btn = document.createElement('button');
      btn.className = `tab-btn ${i === 0 ? 'active' : ''}`;
      btn.textContent = tab.name;
      btn.onclick = () => {
        header.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        content.querySelectorAll('.tab-pane').forEach(p => p.classList.add('hidden'));
        pane.classList.remove('hidden');
      };
      header.appendChild(btn);

      const pane = document.createElement('div');
      pane.className = `tab-pane ${i === 0 ? '' : 'hidden'}`;
      this.renderWidgets(tab.widgets, pane);
      content.appendChild(pane);
    });

    this.container.appendChild(header);
    this.container.appendChild(content);
  }

  renderWidgets(widgets, parent) {
    if (!widgets) return;
    widgets.forEach(w => {
      const widgetEl = document.createElement('div');
      widgetEl.className = 'card widget-card';
      
      const kind = (w.kind || w.type || w.widget || '').toLowerCase();
      switch (kind) {
        case 'stat':
          widgetEl.innerHTML = `
            <div class="stat-item">
              <span class="stat-label">${w.label || ''}</span>
              <span class="stat-value">${w.value || ''}</span>
              ${w.sub ? `<span class="stat-sub">${w.sub}</span>` : ''}
            </div>
          `;
          break;
        case 'table':
          const tableWrap = document.createElement('div');
          tableWrap.className = 'table-container';
          if (w.title) tableWrap.innerHTML = `<h3 class="widget-title">${w.title}</h3>`;
          const table = document.createElement('table');
          const cols = w.columns || [];
          table.innerHTML = `
            <thead><tr>${cols.map(c => `<th>${c}</th>`).join('')}</tr></thead>
            <tbody>
              ${(w.rows || []).map(row => `
                <tr>${(Array.isArray(row) ? row : cols.map(c => row[c] || '')).map(cell => `<td>${cell}</td>`).join('')}</tr>
              `).join('')}
            </tbody>
          `;
          tableWrap.appendChild(table);
          widgetEl.appendChild(tableWrap);
          break;
        case 'line':
        case 'bar':
          const canvas = document.createElement('canvas');
          widgetEl.appendChild(canvas);
          this.renderChart(w, canvas, kind);
          break;
        case 'text':
          widgetEl.innerHTML = `
            ${w.heading ? `<h3 class="widget-title">${w.heading}</h3>` : ''}
            <p class="stat-sub" style="opacity: 0.8">${w.body || w.text || ''}</p>
          `;
          break;
        default:
          widgetEl.textContent = `Unknown widget: ${kind || 'undefined'}`;
          console.warn('Unknown widget spec:', w);
      }
      parent.appendChild(widgetEl);
    });
  }

  renderChart(w, canvas, kind) {
    const ctx = canvas.getContext('2d');
    const labels = w.data.map(d => d[w.x_key]);
    const datasets = w.y_keys.map(key => ({
      label: key,
      data: w.data.map(d => d[key]),
      borderColor: '#38bdf8',
      backgroundColor: kind === 'bar' ? 'rgba(56, 189, 248, 0.5)' : 'transparent',
      tension: 0.3
    }));

    const chart = new Chart(ctx, {
      type: kind,
      data: { labels, datasets },
      options: {
        responsive: true,
        plugins: { legend: { display: w.show_legend } },
        scales: {
          y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } },
          x: { grid: { display: false }, ticks: { color: '#94a3b8' } }
        }
      }
    });
    this.charts.push(chart);
  }
}
