(function () {
  const FRONTEND_VERSION = 'a-stock-v35-sync-v1';

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

  function renderQuality(section) {
    const chips = [];
    if (section.freshness) chips.push({ label: section.freshness, cls: `fresh-${section.freshness}` });
    if (section.confidence) chips.push({ label: `${section.confidence}置信`, cls: section.confidence === '低' ? 'low' : (section.confidence === '高' ? 'high' : '') });
    if (section.source_date) chips.push({ label: `来源 ${section.source_date}`, cls: 'date' });
    const warnings = section.warnings || [];
    if (warnings.length) chips.push({ label: `提示 ${warnings.length}`, cls: 'warn' });
    if (!chips.length) return '';
    const warnHtml = warnings.length
      ? `<details class="quality-warnings"><summary>查看口径提示</summary><ul>${warnings.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></details>`
      : '';
    return `
      <div class="quality-row">
        ${chips.map(chip => `<span class="quality-pill ${escapeHtml(chip.cls || '')}">${escapeHtml(chip.label)}</span>`).join('')}
      </div>
      ${warnHtml}
    `;
  }

  function pct(value) {
    if (value === null || value === undefined || value === '') {
      return '<span class="neutral">NA</span>';
    }
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

  function chipToggleButton(hiddenCount, scope = 'chip') {
    return hiddenCount > 0
      ? `<button type="button" class="chip chip-more" data-chip-toggle="${escapeHtml(scope)}" data-count="${hiddenCount}" aria-expanded="false">+${hiddenCount}</button>`
      : '';
  }

  function renderChipList(items, renderItem, limit = 4, emptyText = '暂无', scope = 'chip') {
    const rows = items || [];
    const visible = rows.slice(0, limit).map(item => renderItem(item, false)).join('');
    const hidden = rows.slice(limit).map(item => renderItem(item, true)).join('');
    const hiddenCount = Math.max(rows.length - limit, 0);
    return `
      <div class="chip-row compact collapsible-chip-row">
        ${visible}${hidden}${chipToggleButton(hiddenCount, scope) || ''}
        ${rows.length ? '' : `<span class="small">${escapeHtml(emptyText)}</span>`}
      </div>
    `;
  }

  function renderFallback(section) {
    return `<ul>${(section.items || []).map(item => `<li>${linkify(item)}</li>`).join('')}</ul>`;
  }

  function splitGroups(groups, itemKey = 'items') {
    const active = [];
    const empty = [];
    (groups || []).forEach(group => {
      const rows = group[itemKey] || [];
      if (rows.length) active.push(group);
      else empty.push(group);
    });
    return { active, empty };
  }

  function renderEmptyGroups(groups, title = '无命中分组') {
    if (!groups || !groups.length) return '';
    return `
      <details class="empty-groups">
        <summary>${escapeHtml(title)}（${groups.length}个）</summary>
        <div class="chip-row">
          ${groups.map(group => `<span class="chip">${escapeHtml(group.name || '')}</span>`).join('')}
        </div>
      </details>
    `;
  }

  function renderCompactEmpty(text) {
    return `<div class="empty-compact">${escapeHtml(text)}</div>`;
  }

  function num(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
  }

  function renderHighlightTags(tags) {
    const rows = (tags || []).filter(tag => tag && tag.label);
    if (!rows.length) return '';
    return `
      <div class="key-tag-row">
        ${rows.map(tag => `<span class="key-tag ${escapeHtml(tag.type || 'info')}">${escapeHtml(tag.label)}</span>`).join('')}
      </div>
    `;
  }

  function decisionTags(item) {
    const tags = [];
    if (num(item.strength) >= 70) tags.push({ label: '强方向', type: 'hot' });
    if ((item.core_stocks || []).length >= 3) tags.push({ label: '核心票成组', type: 'info' });
    if ((item.evidence || []).length >= 3) tags.push({ label: '证据较足', type: 'ok' });
    return tags;
  }

  function sectorTags(item) {
    const tags = [];
    const breakdown = item.score_breakdown || {};
    if (num(item.score) >= 70) tags.push({ label: '强发酵', type: 'hot' });
    if (num(item.limit_up_count) > 0) tags.push({ label: `涨停${fmt(item.limit_up_count)}`, type: 'hot' });
    if (num(item.flow_days) >= 2) tags.push({ label: `${fmt(item.flow_days)}日连续`, type: 'info' });
    if (item.board_flow_observed && num(item.board_flow_today_yi) > 0) tags.push({ label: '主力净流入', type: 'ok' });
    if (item.board_flow_observed && num(item.board_flow_today_yi) < 0) tags.push({ label: '主力净流出', type: 'warn' });
    if (num(breakdown['价格强度']) >= 6) tags.push({ label: '价格强度', type: 'warn' });
    if (num(breakdown['成交放大']) >= 10) tags.push({ label: '成交放大', type: 'ok' });
    return tags;
  }

  function materialTags(item) {
    const text = String(item.tightness || '');
    const tags = [];
    if (item.display_type === 'full_price_inventory') tags.push({ label: '价格/库存', type: 'info' });
    if (text.includes('紧') || text.includes('断供')) tags.push({ label: '紧缺线索', type: 'hot' });
    if (text.includes('上行') || text.includes('涨价')) tags.push({ label: '涨价线索', type: 'warn' });
    if ((item.news || []).length) tags.push({ label: `消息${item.news.length}`, type: 'ok' });
    return tags;
  }

  function stockTags(stock) {
    const tags = [];
    if (num(stock.change_pct) >= 7) tags.push({ label: '强势', type: 'hot' });
    if (num(stock.vol_ratio) >= 2) tags.push({ label: '放量', type: 'warn' });
    if (num(stock.amount_yi) >= 20) tags.push({ label: '高成交', type: 'info' });
    return tags;
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
        ${renderChipList(
          group.stocks || [],
          (s, hidden = false) => `
            <span class="chip ${hidden ? 'stock-extra' : ''}">${escapeHtml(s.name)}(${escapeHtml(s.code)})${s.board_count ? ` ${escapeHtml(s.board_count)}` : ''}${s.is_one_word_board ? ' 一字' : ''}</span>
          `,
          5,
          '暂无个股明细',
          'limitup-stock'
        )}
      </div>
    `).join('');
    const oneWordRows = section.one_word_boards || [];
    const oneWordHeaders = [
      { label: '代码', key: 'code' },
      { label: '名称', key: 'name' },
      { label: '连板', key: 'board_count' },
      { label: '行业', key: 'industry' },
      { label: '成交额(亿)', key: 'amount_yi' },
      { label: '首次封板', key: 'first_time' },
      { label: '炸板', key: 'break_count' }
    ];
    const oneWord = table(
      oneWordHeaders,
      oneWordRows.slice(0, 10)
    );
    const oneWordMore = oneWordRows.length > 10
      ? `<details class="soft-panel compact-details"><summary>查看全部一字板（${oneWordRows.length}只）</summary>${table(oneWordHeaders, oneWordRows)}</details>`
      : '';
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
      ${oneWordMore}
    `;
  }

  function renderSectorRadar(section) {
    const topThree = (section.top_sectors || []).slice(0, 3);
    const metricCards = topThree.map(item => `
      <div class="metric sector-metric">
        <strong>${fmt(item.score)}</strong>
        <span>${escapeHtml(item.name)} · 连续${fmt(item.flow_days)}日</span>
      </div>
    `).join('');
    const renderStockChip = (stock, hidden = false) => `
      <span class="chip ${hidden ? 'stock-extra' : ''}">${escapeHtml(stock.name || '')}${stock.code ? `(${escapeHtml(stock.code)})` : ''} ${pct(stock.change_pct)}</span>
    `;
    const renderStockChips = (stocks, limit = 4, scope = 'sector-stock') => renderChipList(stocks, renderStockChip, limit, '暂无', scope);
    const renderSignalChips = signals => renderChipList(
      signals || [],
      (text, hidden = false) => `<span class="chip ${hidden ? 'stock-extra' : ''}">${escapeHtml(text)}</span>`,
      3,
      '暂无信号',
      'sector-signal'
    );
    const renderBreakdown = item => {
      const breakdown = item.score_breakdown || {};
      return ['资金连续性', '涨停结构', '价格强度', '成交放大']
        .filter(key => breakdown[key] !== undefined && breakdown[key] !== null)
        .map(key => `<span>${escapeHtml(key)} ${fmt(breakdown[key])}</span>`)
        .join('');
    };
    const renderSectorDetails = (item, compact = false) => `
      <details class="sector-details">
        <summary>${compact ? '信号/核心票' : '信号和个股'}</summary>
        ${renderSignalChips(item.signals)}
        <div class="sector-block">
          <span>核心票</span>
          ${renderStockChips(item.core_stocks, compact ? 3 : 4, 'core-stock')}
        </div>
        ${compact ? '' : `
          <div class="sector-block">
            <span>扩散票</span>
            ${renderStockChips(item.diffusion_stocks, 4, 'diffusion-stock')}
          </div>
        `}
      </details>
    `;
    const renderSectorCard = (item, compact = false) => `
      <div class="sector-card ${compact ? 'compact watch-card' : 'rank-card'}">
        <div class="sector-card-head">
          <div>
            <h3>${escapeHtml(item.name)}</h3>
            <div class="item-meta">
              证据 ${escapeHtml(item.evidence_level || 'NA')}
              ${item.rank_change ? ` · 排名${Number(item.rank_change) > 0 ? '上升' : '下降'}${Math.abs(Number(item.rank_change))}位` : ''}
              ${item.board_flow_observed ? ` · 资金源 ${escapeHtml(item.board_flow_board || item.name)}` : ' · 资金源 回退估算'}
            </div>
          </div>
          <div class="sector-score">${fmt(item.score)}</div>
        </div>
        ${renderHighlightTags(sectorTags(item))}
        <div class="sector-stats">
          <span>连续 ${fmt(item.flow_days)}日</span>
          <span>涨停 ${fmt(item.limit_up_count)}</span>
          <span>强势 ${fmt(item.hot_stock_count)}</span>
          <span>成交 ${fmt(item.amount_yi)}亿</span>
          ${item.board_flow_observed ? `<span>主力今日 ${signed(item.board_flow_today_yi)}亿</span><span>5日 ${signed(item.board_flow_5d_yi)}亿</span>` : ''}
          ${compact ? '' : `<span>催化 ${fmt(item.catalyst_count)}</span>`}
        </div>
        <div class="sector-breakdown">${renderBreakdown(item)}</div>
        ${renderSectorDetails(item, compact)}
      </div>
    `;
    const topCards = topThree.map(item => renderSectorCard(item)).join('');
    const watchCards = (section.watch_sectors || []).map(item => renderSectorCard(item, true)).join('');
    const cooling = (section.cooling_sectors || []).map(item => `
      <span class="chip cooling">${escapeHtml(item.name)} ${fmt(item.previous_score)}→${fmt(item.score)}</span>
    `).join('');
    return `
      <div class="metric-grid">${metricCards || '<div class="small">暂无板块评分。</div>'}</div>
      <h3>综合排名</h3>
      <div class="sector-grid ranking-grid">${topCards || renderFallback(section)}</div>
      ${watchCards ? `<h3>潜伏观察</h3><div class="sector-grid compact watch-row">${watchCards}</div>` : ''}
      ${cooling ? `<h3>降温方向</h3><div class="chip-row">${cooling}</div>` : ''}
    `;
  }

  function renderMaterials(section) {
    const cards = (section.materials || []).map(item => {
      const price = item.price;
      const inventory = item.inventory || {};
      const fullPrice = item.display_type === 'full_price_inventory';
      const allStocks = item.related_stocks || [];
      const stockLimit = fullPrice ? allStocks.length : 4;
      const visibleStocks = allStocks.slice(0, stockLimit).map(s => `
        <span class="chip">${escapeHtml(s.name)} ${pct(s.change_pct)}</span>
      `).join('');
      const hiddenStocks = allStocks.slice(stockLimit).map(s => `
        <span class="chip stock-extra">${escapeHtml(s.name)} ${pct(s.change_pct)}</span>
      `).join('');
      const hiddenCount = Math.max(allStocks.length - stockLimit, 0);
      const moreStocks = hiddenCount ? `<button type="button" class="chip chip-more" data-material-toggle data-count="${hiddenCount}" aria-expanded="false">+${hiddenCount}</button>` : '';
      const stockRow = visibleStocks || hiddenStocks || moreStocks ? `${visibleStocks}${hiddenStocks}${moreStocks}` : '<span class="small">暂无行情</span>';
      const newsRows = item.news || [];
      const leadNews = newsRows[0];
      const news = newsRows.map(n => `
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
          ${renderHighlightTags(materialTags(item))}
          ${fullPrice ? `
            <div class="material-featured-layout">
              <div class="material-metrics-column">
                <div class="fact"><span>价格走势</span><strong>${price ? `${fmt(price.price)} ${escapeHtml(price.unit || '')}<br>${pct(price.change_pct)} · ${escapeHtml(price.trend || '')}` : escapeHtml(item.coverage || '暂无')}</strong></div>
                <div class="fact"><span>库存/仓单</span><strong>${inventory && inventory.value ? `${fmt(inventory.value)} ${inventory.change ? `(${fmt(inventory.change)})` : ''}` : (inventory && inventory.error ? escapeHtml(inventory.error) : '暂无直连数据')}</strong></div>
              </div>
              <div class="material-featured-main">
                <div class="fact material-expansion-wide"><span>扩产难度</span><strong>${escapeHtml(item.expansion || 'NA')}</strong></div>
                <div class="fact material-stocks-wide"><span>相关 A 股</span><div class="chip-row compact expanded">${stockRow}</div></div>
              </div>
            </div>
            ${news ? `<details class="material-details"><summary>材料线索（${newsRows.length}条）</summary><div class="news-list material-news">${news}</div></details>` : ''}
          ` : `
            <div class="material-compact-body">
              <div class="chip-row compact material-stock-row">${stockRow}</div>
              ${leadNews ? `<div class="material-lead-news">${escapeHtml(leadNews.source || '')}：${linkify(leadNews.text || '')}</div>` : '<div class="material-lead-news muted">暂无最新线索</div>'}
              <details class="material-details">
                <summary>扩产与全部线索${newsRows.length ? `（${newsRows.length}条）` : ''}</summary>
                <div class="material-detail-text"><span>扩产难度</span><strong>${escapeHtml(item.expansion || 'NA')}</strong></div>
                ${news ? `<div class="news-list material-news">${news}</div>` : ''}
              </details>
            </div>
          `}
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
    return `<div class="news-list">${rows || renderCompactEmpty('暂无材料突发线索。')}</div>`;
  }

  function renderFutures(section) {
    const diagnostics = (section.diagnostics || []).slice(0, 8).map(item => `<li>${escapeHtml(item)}</li>`).join('');
    const reason = section.empty_reason ? `<div class="small">${escapeHtml(section.empty_reason)}</div>` : '';
    const sourceNote = section.source_note ? `<div class="small">${escapeHtml(section.source_note)}</div>` : '';
    const rows = section.table || [];
    const futuresTable = table(
      [
        { label: '组别', key: 'group' },
        { label: '多单', key: 'long_value' },
        { label: '多单变化', key: 'long_chg', render: r => r.is_history ? '' : signed(r.long_chg) },
        { label: '空单', key: 'short_value' },
        { label: '空单变化', key: 'short_chg', render: r => r.is_history ? '' : signed(r.short_chg) },
        { label: '净值', key: 'net_value', render: r => r.is_history ? '' : signed(r.net_value) },
        { label: '净变化', key: 'net_chg', render: r => r.is_history ? '' : signed(r.net_chg) },
        { label: '方向', key: 'direction' }
      ],
      rows
    );
    const cards = rows.map(row => row.is_history ? `
      <div class="futures-card history">
        <h3>${escapeHtml(row.group || '前五日方向')}</h3>
        <div class="futures-direction">${escapeHtml(row.direction || '')}</div>
      </div>
    ` : `
      <div class="futures-card">
        <div class="futures-card-head">
          <h3>${escapeHtml(row.group || '')}</h3>
          <span class="pill">${escapeHtml(row.direction || 'NA')}</span>
        </div>
        <div class="futures-stats">
          <span>多单 <b>${fmt(row.long_value)}</b></span>
          <span>变化 ${signed(row.long_chg)}</span>
          <span>空单 <b>${fmt(row.short_value)}</b></span>
          <span>变化 ${signed(row.short_chg)}</span>
          <span>净值 ${signed(row.net_value)}</span>
          <span>净变 ${signed(row.net_chg)}</span>
        </div>
      </div>
    `).join('');
    return `
      <div class="futures-table-view">${futuresTable}</div>
      <div class="futures-card-list">${cards || '<div class="small">暂无期指席位数据。</div>'}</div>
      ${sourceNote}
      ${reason}
      ${diagnostics ? `<details class="soft-panel" style="margin-top:8px"><summary>期指数据诊断</summary><ul>${diagnostics}</ul></details>` : ''}
    `;
  }

  function renderReports(section) {
    const groups = section.groups && section.groups.length
      ? section.groups
      : [{ name: '研报/观点', items: section.reports || [] }];
    const { active, empty } = splitGroups(groups, 'items');
    const html = active.map(group => {
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
    return `
      <div class="group-list">
        ${html || renderCompactEmpty('暂无主题研报命中。')}
        ${renderEmptyGroups(empty, '无命中研报分组')}
      </div>
    `;
  }

  function renderFocus(section) {
    const groups = section.groups || [];
    const { active, empty } = splitGroups(groups, 'items');
    const rows = active.map(group => `
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
    return `
      <div class="group-list">
        ${rows || renderCompactEmpty('近48小时暂无重点公司/产业消息命中。')}
        ${renderEmptyGroups(empty, '正在跟踪但暂无命中')}
      </div>
    `;
  }

  function renderEquityMap(section) {
    const rows = (section.groups || []).map(group => `
      <div class="equity-row">
        <div class="equity-row-head">
          <h3>${escapeHtml(group.name)}</h3>
          <span class="small">${fmt((group.stocks || []).length)}只</span>
        </div>
        <div class="equity-strip">
          ${(group.stocks || []).map(s => `
            <div class="equity-stock-card">
              <strong>${escapeHtml(s.name)}(${escapeHtml(s.code)})</strong>
              ${renderHighlightTags(stockTags(s))}
              <div>涨跌 ${pct(s.change_pct)}</div>
              <div>成交 ${fmt(s.amount_yi)}亿 · 量比 ${fmt(s.vol_ratio)}</div>
              <div>市值 ${fmt(s.mcap_yi)}亿</div>
            </div>
          `).join('')}
        </div>
      </div>
    `).join('');
    return `<div class="equity-map">${rows || renderCompactEmpty('暂无 A 股映射。')}</div>`;
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

  function renderDecisionBrief(brief, target) {
    if (!target) return;
    if (!brief || !Object.keys(brief).length) {
      target.style.display = 'none';
      target.innerHTML = '';
      return;
    }
    target.style.display = '';
    const primaryRisk = (brief.risk_flags || [])[0]?.text || '盘中若核心票回落或催化不延续，方向需降级观察。';
    const directions = (brief.top_directions || []).map(item => `
      <div class="decision-card primary compact-decision">
        <div class="decision-card-head">
          <h3>${escapeHtml(item.name || '未命名方向')}</h3>
          <span class="decision-score">${fmt(item.strength)}</span>
        </div>
        ${renderHighlightTags(decisionTags(item))}
        ${renderChipList(
          item.core_stocks || [],
          (stock, hidden = false) => `<span class="chip ${hidden ? 'stock-extra' : ''}">${escapeHtml(stock.name || '')}${stock.code ? `(${escapeHtml(stock.code)})` : ''} ${pct(stock.change_pct)}</span>`,
          3,
          '暂无核心票',
          'decision-core'
        )}
        <div class="decision-snapshot"><span>依据</span><p>${escapeHtml((item.evidence || [])[0] || '等待更多证据确认')}</p></div>
        <div class="decision-snapshot risk"><span>风险</span><p>${escapeHtml(primaryRisk)}</p></div>
        ${(item.evidence || []).length > 1 ? `
          <details class="decision-details">
            <summary>展开证据</summary>
            <ul class="decision-evidence">
              ${(item.evidence || []).slice(1).map(text => `<li>${escapeHtml(text)}</li>`).join('')}
            </ul>
          </details>
        ` : ''}
      </div>
    `).join('');
    const watch = (brief.tomorrow_watchlist || []).map(item => `
      <div class="decision-card watch-compact">
        <h3>${escapeHtml(item.direction || '观察方向')}</h3>
        <div class="decision-line"><span>核心</span><strong>${escapeHtml(item.core || '等待确认')}</strong></div>
        <div class="decision-line compact-line"><span>触发</span><p>${escapeHtml(item.trigger || '')}</p></div>
        <div class="decision-line compact-line"><span>失效</span><p>${escapeHtml(item.invalid || '')}</p></div>
        <button type="button" class="inline-toggle" data-card-toggle aria-expanded="false">展开</button>
      </div>
    `).join('');
    const risks = (brief.risk_flags || []).map(item => `
      <div class="risk-flag ${escapeHtml(item.level || 'note')}">${escapeHtml(item.text || '')}</div>
    `).join('');
    const notes = (brief.data_notes || []).map(item => `
      <span class="quality-pill date">${escapeHtml(item.label || '')}：${escapeHtml(item.value || '')}</span>
    `).join('');
    target.innerHTML = `
      <div class="section-head decision-head">
        <div>
          <h2>${escapeHtml(brief.title || '交易准备卡')}</h2>
          <p>${escapeHtml(brief.summary || '')}</p>
        </div>
      </div>
      <div class="decision-notes">${notes}</div>
      <div class="decision-grid">${directions || '<div class="digest">暂无明确强方向。</div>'}</div>
      <h3>明日观察</h3>
      <div class="decision-grid watch watch-row">${watch || '<div class="small">暂无观察项。</div>'}</div>
      <h3>风险与口径</h3>
      <div class="risk-list">${risks || '<div class="risk-flag note">暂无高优先级异常提示。</div>'}</div>
    `;
  }

  function renderBody(section) {
    switch (section.type) {
      case 'fermentation': return renderFermentation(section);
      case 'sector_radar': return renderSectorRadar(section);
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
    const moduleOrder = {
      fermentation: 1,
      sector_radar: 2,
      equity_map: 3,
      material_radar: 4,
      material_news: 5,
      focus_groups: 6,
      futures_summary: 7,
      reports: 8,
      status: 9
    };
    const orderedSections = [...sections].sort((a, b) => {
      const ao = moduleOrder[a.type] || 99;
      const bo = moduleOrder[b.type] || 99;
      return ao === bo ? sections.indexOf(a) - sections.indexOf(b) : ao - bo;
    });
    target.innerHTML = orderedSections.map((section, index) => `
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
        ${renderQuality(section)}
        ${renderBody(section)}
      </article>
    `).join('');
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('click', event => {
      const chipButton = event.target.closest('[data-material-toggle], [data-chip-toggle]');
      if (chipButton) {
        const row = chipButton.closest('.chip-row');
        if (!row) return;
        const expanded = row.classList.toggle('expanded');
        chipButton.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        chipButton.textContent = expanded ? '收起' : `+${chipButton.dataset.count || ''}`;
        return;
      }
      const cardButton = event.target.closest('[data-card-toggle]');
      if (!cardButton) return;
      const card = cardButton.closest('.decision-card');
      if (!card) return;
      const expanded = card.classList.toggle('expanded');
      cardButton.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      cardButton.textContent = expanded ? '收起' : '展开';
    });
  }

  window.IntelUI = {
    version: FRONTEND_VERSION,
    escapeHtml,
    linkify,
    renderDecisionBrief,
    renderModules,
    renderStatus,
  };
})();
