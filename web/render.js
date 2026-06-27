(function () {
  function escapeHtml(text) {
    return String(text ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[ch]);
  }

  function linkify(text) {
    return escapeHtml(text).replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
  }

  function fmt(value) {
    if (value === null || value === undefined || value === '') return 'NA';
    if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.00$/, '');
    return escapeHtml(value);
  }

  function signed(value) {
    const n = Number(value || 0);
    const cls = n > 0 ? 'pos' : (n < 0 ? 'neg' : 'neutral');
    const sign = n > 0 ? '+' : '';
    return `<span class="${cls}">${sign}${fmt(n)}</span>`;
  }

  function pct(value) {
    const n = Number(value || 0);
    const cls = n > 0 ? 'pos' : (n < 0 ? 'neg' : 'neutral');
    const sign = n > 0 ? '+' : '';
    return `<span class="${cls}">${sign}${fmt(n)}%</span>`;
  }

  function table(headers, rows) {
    if (!rows || !rows.length) return '<div class="small">暂无表格数据。</div>';
    return `
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>${headers.map(h => `<th>${escapeHtml(h.label)}</th>`).join('')}</tr></thead>
          <tbody>
            ${rows.map(row => `<tr>${headers.map(h => `<td>${h.render ? h.render(row) : fmt(row[h.key])}</td>`).join('')}</tr>`).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderFallback(section) {
    return `<ul>${(section.items || []).map(item => `<li>${linkify(item)}</li>`).join('')}</ul>`;
  }

  function renderFermentation(section) {
    const metrics = (section.metrics || []).map(m => `
      <div class="metric"><strong>${fmt(m.value)}</strong><span>${escapeHtml(m.label)}</span></div>
    `).join('');
    const tags = (section.tags || []).map(t => `<span class="chip">${escapeHtml(t.name)} <b>${fmt(t.count)}</b></span>`).join('');
    const industries = (section.industries || []).map(t => `<span class="chip">${escapeHtml(t.name)} <b>${fmt(t.count)}</b></span>`).join('');
    const topIndustries = (section.top_limitup_industries || []).map(group => `
      <div class="group-card">
        <h3>${escapeHtml(group.name)} <span class="small">${fmt(group.count)}只涨停</span></h3>
        <div class="chip-row">
          ${(group.stocks || []).map(s => `
            <span class="chip">${escapeHtml(s.name)}(${escapeHtml(s.code)})${s.board_count ? ` ${escapeHtml(s.board_count)}` : ''}${s.is_one_word_board ? ' 一字' : ''}</span>
          `).join('') || '<span class="small">暂无个股明细</span>'}
        </div>
      </div>
    `).join('');
    const oneWord = table(
      [
        { label: '代码', key: 'code' },
        { label: '名称', key: 'name' },
        { label: '连板', key: 'board_count' },
        { label: '行业', key: 'industry' },
        { label: '成交额(亿)', key: 'amount_yi' },
        { label: '首次封板', key: 'first_time' },
        { label: '炸板', key: 'break_count' }
      ],
      section.one_word_boards || []
    );
    return `
      <div class="metric-grid">${metrics}</div>
      <div class="small">题材词频</div>
      <div class="chip-row">${tags || '<span class="small">暂无</span>'}</div>
      <div class="small">涨停行业集中</div>
      <div class="chip-row">${industries || '<span class="small">暂无</span>'}</div>
      <h3>前三集中板块涨停股</h3>
      <div class="group-list">${topIndustries || '<div class="small">暂无板块明细。</div>'}</div>
      <h3>一字板明细</h3>
      ${oneWord}
    `;
  }

  function renderMaterials(section) {
    const cards = (section.materials || []).map(item => {
      const price = item.price;
      const inventory = item.inventory || {};
      const fullPrice = item.display_type === 'full_price_inventory';
      const allStocks = item.related_stocks || [];
      const stockLimit = fullPrice ? 8 : 5;
      const visibleStocks = allStocks.slice(0, stockLimit).map(s => `
        <span class="chip">${escapeHtml(s.name)} ${pct(s.change_pct)}</span>
      `).join('');
      const hiddenStocks = allStocks.slice(stockLimit).map(s => `
        <span class="chip stock-extra">${escapeHtml(s.name)} ${pct(s.change_pct)}</span>
      `).join('');
      const hiddenCount = Math.max(allStocks.length - stockLimit, 0);
      const moreStocks = hiddenCount ? `<button type="button" class="chip chip-more" data-material-toggle data-count="${hiddenCount}" aria-expanded="false">+${hiddenCount}</button>` : '';
      const stockRow = visibleStocks || hiddenStocks || moreStocks ? `${visibleStocks}${hiddenStocks}${moreStocks}` : '<span class="small">暂无行情</span>';
      const news = (item.news || []).slice(0, fullPrice ? 2 : 1).map(n => `
        <div class="item-text">${escapeHtml(n.source || '')}：${linkify(n.text || '')}${n.link ? ` <a href="${escapeHtml(n.link)}" target="_blank" rel="noopener noreferrer">链接</a>` : ''}</div>
      `).join('');
      return `
        <div class="material-card ${fullPrice ? 'featured' : 'compact'}">
          <div class="material-top">
            <div>
              <h3>${escapeHtml(item.name)}</h3>
              <div class="small">${escapeHtml(item.category || '')}</div>
            </div>
            <span class="pill ${String(item.tightness || '').includes('紧') || String(item.tightness || '').includes('上行') ? 'hot' : ''}">${escapeHtml(item.tightness || 'NA')}</span>
          </div>
          ${fullPrice ? `
            <div class="material-facts">
              <div class="fact"><span>价格走势</span><strong>${price ? `${fmt(price.price)} ${escapeHtml(price.unit || '')} · ${pct(price.change_pct)} · ${escapeHtml(price.trend || '')}` : escapeHtml(item.coverage || '暂无')}</strong></div>
              <div class="fact"><span>库存/仓单</span><strong>${inventory && inventory.value ? `${fmt(inventory.value)} ${inventory.change ? `(${fmt(inventory.change)})` : ''}` : (inventory && inventory.error ? escapeHtml(inventory.error) : '暂无直连数据')}</strong></div>
              <div class="fact"><span>扩产难度</span><strong>${escapeHtml(item.expansion || 'NA')}</strong></div>
              <div class="fact"><span>相关 A 股</span><div class="chip-row compact">${stockRow}</div></div>
            </div>
          ` : `
            <div class="material-compact-body">
              <div class="chip-row compact">${stockRow}</div>
              <div class="material-note">${escapeHtml(item.expansion || 'NA')}</div>
            </div>
          `}
          ${news ? `<div class="news-list material-news">${news}</div>` : ''}
        </div>
      `;
    }).join('');
    return `<div class="material-grid">${cards || '<div class="small">暂无材料数据。</div>'}</div>`;
  }

  function renderMaterialNews(section) {
    const rows = (section.news || []).map(item => `
      <div class="news-item">
        <div class="item-meta">${escapeHtml(item.material || '')} · ${escapeHtml(item.signal || '')} · ${escapeHtml(item.source || '')}${item.date ? ` · ${escapeHtml(item.date)}` : ''}</div>
        <div class="item-title">${linkify(item.text || '')}${item.link ? ` <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer">链接</a>` : ''}</div>
      </div>
    `).join('');
    return `<div class="news-list">${rows || '<div class="small">暂无材料突发线索。</div>'}</div>`;
  }

  function renderFutures(section) {
    const diagnostics = (section.diagnostics || []).slice(0, 8).map(item => `<li>${escapeHtml(item)}</li>`).join('');
    const reason = section.empty_reason ? `<div class="small">${escapeHtml(section.empty_reason)}</div>` : '';
    return table(
      [
        { label: '组别', key: 'group' },
        { label: '多单', key: 'long_value' },
        { label: '多单变化', key: 'long_chg', render: r => signed(r.long_chg) },
        { label: '空单', key: 'short_value' },
        { label: '空单变化', key: 'short_chg', render: r => signed(r.short_chg) },
        { label: '净值', key: 'net_value', render: r => signed(r.net_value) },
        { label: '净变化', key: 'net_chg', render: r => signed(r.net_chg) },
        { label: '方向', key: 'direction' }
      ],
      section.table || []
    ) + `
      ${reason}
      ${diagnostics ? `<details class="soft-panel" style="margin-top:8px"><summary>期指数据诊断</summary><ul>${diagnostics}</ul></details>` : ''}
    `;
  }

  function renderReports(section) {
    const groups = section.groups && section.groups.length
      ? section.groups
      : [{ name: '研报/观点', items: section.reports || [] }];
    const html = groups.map(group => {
      const rows = (group.items || []).map(item => {
        const link = item.pdf_url || item.url || item.link;
        const linkText = item.pdf_url ? 'PDF' : (link ? '链接' : '');
        return `
          <div class="report-item">
            <div class="item-meta">${escapeHtml([item.kind, item.date || item.time, item.org || item.source, item.analyst, item.target_sector, item.sentiment, item.rating, item.industry].filter(Boolean).join(' / '))}</div>
            <div class="item-title">${escapeHtml(item.title || '')}${link ? ` <a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">${linkText}</a>` : ''}</div>
            ${item.summary ? `<div class="item-text">${escapeHtml(item.summary)}</div>` : ''}
          </div>
        `;
      }).join('');
      return `
        <div class="group-card">
          <h3>${escapeHtml(group.name)}</h3>
          <div class="report-list">${rows || '<div class="small">暂无命中。</div>'}</div>
        </div>
      `;
    }).join('');
    return `<div class="group-list">${html || '<div class="small">暂无主题研报命中。</div>'}</div>`;
  }

  function renderFocus(section) {
    const rows = (section.groups || []).map(group => `
      <div class="group-card">
        <h3>${escapeHtml(group.name)}</h3>
        <div class="news-list">
          ${(group.items || []).map(item => {
            if (typeof item === 'string') return `<div class="news-item">${linkify(item)}</div>`;
            const link = item.link || item.url || item.pdf_url;
            return `
              <div class="news-item">
                <div class="item-meta">${escapeHtml([item.kind, item.time, item.source].filter(Boolean).join(' / '))}</div>
                <div class="item-title">${escapeHtml(item.title || item.text || '')}${link ? ` <a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">链接</a>` : ''}</div>
                ${item.content ? `<div class="item-text">${escapeHtml(item.content)}</div>` : ''}
              </div>
            `;
          }).join('') || '<div class="small">暂无近48小时命中</div>'}
        </div>
      </div>
    `).join('');
    return `<div class="group-list">${rows || renderFallback(section)}</div>`;
  }

  function renderEquityMap(section) {
    const rows = (section.groups || []).map(group => `
      <div class="stock-group">
        <h3>${escapeHtml(group.name)}</h3>
        <div class="stock-grid">
          ${(group.stocks || []).map(s => `
            <div class="stock">
              <strong>${escapeHtml(s.name)}(${escapeHtml(s.code)})</strong><br>
              涨跌 ${pct(s.change_pct)} · 成交 ${fmt(s.amount_yi)}亿<br>
              市值 ${fmt(s.mcap_yi)}亿 · 量比 ${fmt(s.vol_ratio)}
            </div>
          `).join('')}
        </div>
      </div>
    `).join('');
    return `<div class="stock-groups">${rows || '<div class="small">暂无 A 股映射。</div>'}</div>`;
  }

  function renderStatus(section) {
    const rows = (section.statuses || []).map(s => `
      <div class="source">
        <span class="badge ${s.ok ? 'ok' : 'fail'}">${s.ok ? 'OK' : 'FAIL'}</span>
        <div><strong>${escapeHtml(s.name)}</strong>${s.error ? `<div class="small">${escapeHtml(s.error)}</div>` : ''}</div>
        <span class="small">${fmt(s.elapsed_ms)}ms</span>
      </div>
    `).join('');
    return `<div class="status-grid">${rows || '<div class="small">暂无状态。</div>'}</div>`;
  }

  function renderBody(section) {
    switch (section.type) {
      case 'fermentation': return renderFermentation(section);
      case 'material_radar': return renderMaterials(section);
      case 'material_news': return renderMaterialNews(section);
      case 'futures_summary': return renderFutures(section);
      case 'reports': return renderReports(section);
      case 'focus_groups': return renderFocus(section);
      case 'equity_map': return renderEquityMap(section);
      case 'status': return renderStatus(section);
      default: return renderFallback(section);
    }
  }

  function renderModules(sections, target) {
    if (!sections || !sections.length) {
      target.innerHTML = '<div class="digest">暂无模块数据。</div>';
      return;
    }
    target.innerHTML = sections.map((section, index) => `
      <article class="module-card ${escapeHtml(section.type || '')}">
        <div class="module-head">
          <div class="module-title">
            <span class="module-index">${index + 1}</span>
            <div>
              <h2>${escapeHtml(section.title || `模块 ${index + 1}`)}</h2>
              ${section.summary ? `<p class="module-summary">${escapeHtml(section.summary)}</p>` : ''}
            </div>
          </div>
        </div>
        ${renderBody(section)}
      </article>
    `).join('');
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-material-toggle]');
      if (!button) return;
      const row = button.closest('.chip-row');
      if (!row) return;
      const expanded = row.classList.toggle('expanded');
      button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      button.textContent = expanded ? '收起' : `+${button.dataset.count || ''}`;
    });
  }

  window.IntelUI = {
    escapeHtml,
    linkify,
    renderModules,
    renderStatus,
  };
})();
