(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const setDotState = (id, state) => {
    const dot = $(id);
    dot.classList.remove('is-current', 'is-stale', 'is-error');
    dot.classList.add(state);
  };
  const number = new Intl.NumberFormat('ar-QA', { maximumFractionDigits: 1, numberingSystem: 'latn' });
  const wholeNumber = new Intl.NumberFormat('ar-QA', { maximumFractionDigits: 0, numberingSystem: 'latn' });
  const dateOnly = new Intl.DateTimeFormat('ar-QA', { dateStyle: 'medium', numberingSystem: 'latn', timeZone: 'Asia/Qatar' });
  const clockTime = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', numberingSystem: 'latn', timeZone: 'Asia/Qatar',
  });
  const specs = [
    { id: '01a182be-0161-7e73-a20a-8491ca192c18', key: 'laser', name: 'ليزر', color: '#0072b2' },
    { id: '01a18383-0873-7df3-8b67-c1a1c8fe9607', key: 'brainstorm', name: 'عصف ذهني', color: '#d55e00' },
    { id: '01a17e81-dc37-7d93-8a62-4adeac385b20', key: 'pen', name: 'مسار القلم', color: '#009e73' },
    { id: '01a1836f-d720-7950-834a-035a0052411e', key: 'svg', name: 'تنسيق إنتاج SVG', color: '#8a4fa3' },
  ];
  const activeSessionIds = new Set(specs.map(spec => spec.id));
  let latestData = null;
  let request = null;
  let manualRefreshQueued = false;

  const formatNumber = value => Number.isFinite(Number(value)) ? number.format(Number(value)) : '—';
  const formatTokens = value => Number.isFinite(Number(value)) ? wholeNumber.format(Number(value)) : '—';
  const formatPercent = value => Number.isFinite(Number(value)) ? `${formatNumber(value)}٪` : 'غير متاح';
  const formatDate = value => {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '—' : `${dateOnly.format(date)} · ${clockTime.format(date)}`;
  };
  const formatAxisTime = value => clockTime.format(value);
  const lastSample = session => (session?.samples || []).reduce((latest, sample) => {
    const time = Date.parse(sample?.timestamp || '');
    return Number.isFinite(time) && (!latest || time > Date.parse(latest.timestamp)) ? sample : latest;
  }, null);
  const cumulative = (samples, field) => samples.reduce((sum, sample) => sum + (Number(sample.cumulative?.[field]) || 0), 0);

  function createCell(tag, value, className) {
    const cell = document.createElement(tag);
    cell.textContent = value;
    if (className) cell.className = className;
    return cell;
  }

  function renderBreakdown(sessions) {
    const samples = sessions.map(lastSample).filter(Boolean);
    const values = [
      ['المدخلات (الإجمالي)', cumulative(samples, 'input_tokens'), '#087f8c'],
      ['منها مخزنة مؤقتًا', cumulative(samples, 'cached_input_tokens'), '#dc9c39'],
      ['المخرجات (الإجمالي)', cumulative(samples, 'output_tokens'), '#3872c5'],
      ['منها للاستدلال', cumulative(samples, 'reasoning_output_tokens'), '#8b69b1'],
    ];
    const largest = Math.max(1, ...values.map(([, value]) => value));
    const root = $('breakdown');
    root.replaceChildren();
    for (const [label, value, color] of values) {
      const row = document.createElement('div');
      row.className = 'bar-row';
      const labelRow = document.createElement('div');
      labelRow.className = 'bar-label';
      labelRow.append(createCell('strong', label), createCell('em', formatTokens(value)));
      const track = document.createElement('div');
      track.className = 'track';
      track.setAttribute('aria-hidden', 'true');
      const fill = document.createElement('div');
      fill.className = 'fill';
      fill.style.width = `${Math.min(100, value / largest * 100)}%`;
      fill.style.background = color;
      track.append(fill);
      row.append(labelRow, track);
      root.append(row);
    }
  }

  function renderSessionTable(sessions) {
    const body = $('sessions-body');
    const empty = $('sessions-empty');
    body.replaceChildren();
    const current = sessions.filter(session => activeSessionIds.has(session.session_id))
      .map(session => ({ session, sample: lastSample(session) }))
      .filter(item => item.sample)
      .sort((a, b) => (Number(b.sample.cumulative?.total_tokens) || 0) - (Number(a.sample.cumulative?.total_tokens) || 0));

    for (const { session, sample } of current) {
      const row = document.createElement('tr');
      const nameCell = document.createElement('td');
      const name = document.createElement('div');
      name.className = 'session-name';
      name.textContent = session.session_name || 'جلسة';
      name.title = name.textContent;
      const shortId = document.createElement('div');
      shortId.className = 'session-meta';
      shortId.textContent = String(session.session_id || '').slice(0, 8);
      nameCell.append(name, shortId);
      row.append(nameCell);

      const model = createCell('td', sample.model || session.model || 'غير محدد');
      if (String(model.textContent).startsWith('gpt-')) {
        const pill = document.createElement('span');
        pill.className = 'pill';
        pill.textContent = model.textContent;
        model.replaceChildren(pill);
      }
      row.append(model);
      row.append(createCell('td', formatTokens(sample.cumulative?.total_tokens), 'num'));
      row.append(createCell('td', formatPercent(sample.context?.used_percent)));
      row.append(createCell('td', formatDate(sample.timestamp)));
      body.append(row);
    }
    empty.hidden = current.length > 0;
    return current;
  }

  function hourlySessionSeries(sessions) {
    const hour = 60 * 60 * 1000;
    const data = specs.map(spec => {
      const session = sessions.find(item => item.session_id === spec.id);
      const events = [];
      for (const sample of session?.samples || []) {
        const timestamp = Date.parse(sample.timestamp);
        const total = Number(sample.cumulative?.total_tokens);
        if (Number.isFinite(timestamp) && Number.isFinite(total)) events.push({ timestamp, total });
      }
      events.sort((a, b) => a.timestamp - b.timestamp);
      return { spec, events };
    });
    const allEvents = data.flatMap(item => item.events);
    if (!allEvents.length) return { times: [], series: data.map(item => ({ spec: item.spec, values: [] })) };

    const endHour = Math.floor(Math.max(...allEvents.map(event => event.timestamp)) / hour) * hour;
    const startHour = endHour - 35 * hour;
    const times = Array.from({ length: 36 }, (_, index) => startHour + index * hour);
    const series = data.map(({ spec, events }) => {
      let index = 0;
      let latest = null;
      while (index < events.length && events[index].timestamp < startHour) latest = events[index++].total;
      const values = times.map(tick => {
        while (index < events.length && events[index].timestamp < tick + hour) latest = events[index++].total;
        return latest;
      });
      return { spec, values };
    });
    return { times, series };
  }

  function drawTrend(sessions) {
    const canvas = $('trend');
    const context = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = rect.width;
    const height = rect.height;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    const { times, series } = hourlySessionSeries(sessions);
    canvas.trendPoints = times;

    if (!times.length || width < 20 || height < 20) {
      $('trend-summary').textContent = 'لا توجد عينات كافية لعرض الاتجاه حتى الآن.';
      context.fillStyle = '#526a7b';
      context.font = '12px Segoe UI, sans-serif';
      context.textAlign = 'center';
      context.fillText('تظهر الاتجاهات بعد وصول عينات القياس', width / 2, height / 2);
      canvas.plotState = null;
      return;
    }

    const padding = { left: 14, right: 72, top: 15, bottom: 33 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    const allValues = series.flatMap(item => item.values).filter(Number.isFinite);
    const maximum = Math.max(...allValues, 1);
    const x = index => padding.left + (times.length === 1 ? chartWidth / 2 : chartWidth * index / (times.length - 1));
    const y = value => padding.top + chartHeight - value / maximum * chartHeight;
    canvas.plotState = { kind: 'trend', times, series, width, height, padding, chartWidth, chartHeight, x, y };

    context.font = '12px Segoe UI, sans-serif';
    context.textAlign = 'right';
    for (let tick = 0; tick < 4; tick += 1) {
      const yPosition = padding.top + chartHeight * tick / 3;
      context.strokeStyle = '#e7edf1';
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(padding.left, yPosition);
      context.lineTo(width - padding.right, yPosition);
      context.stroke();
      context.fillStyle = '#526a7b';
      context.fillText(formatTokens(maximum * (1 - tick / 3)), width - 4, yPosition - 3);
    }

    for (const item of series) {
      context.beginPath();
      let hasPoint = false;
      item.values.forEach((value, index) => {
        if (!Number.isFinite(value)) return;
        if (!hasPoint) { context.moveTo(x(index), y(value)); hasPoint = true; }
        else context.lineTo(x(index), y(value));
      });
      context.strokeStyle = item.spec.color;
      context.lineWidth = 2.7;
      context.lineJoin = 'round';
      context.lineCap = 'round';
      context.stroke();
    }

    context.fillStyle = '#526a7b';
    context.textAlign = 'center';
    for (const index of [...new Set([0, Math.floor((times.length - 1) / 2), times.length - 1])]) {
      context.fillText(formatAxisTime(new Date(times[index])), x(index), height - 6);
    }

    const summaries = series.map(item => {
      const valid = item.values.filter(Number.isFinite);
      const first = valid[0];
      const final = valid.at(-1);
      return `${item.spec.name}: ${formatTokens(first)} إلى ${formatTokens(final)} توكن تراكمي`;
    });
    $('trend-summary').textContent = `اتجاه الجلسات الأربع خلال آخر 36 ساعة، مع حمل آخر قراءة إلى الساعات التالية: ${summaries.join('؛ ')}.`;
  }

  function plotSession(canvas, samples, color) {
    const context = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = rect.width;
    const height = rect.height;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    canvas.samples = samples;

    if (!samples.length || width < 20 || height < 20) {
      context.fillStyle = '#526a7b';
      context.font = '12px Segoe UI, sans-serif';
      context.textAlign = 'center';
      context.fillText('بانتظار عينات الجلسة', width / 2, height / 2);
      canvas.plotState = null;
      return;
    }

    const padding = { left: 50, right: 75, top: 13, bottom: 30 };
    const chartWidth = Math.max(1, width - padding.left - padding.right);
    const chartHeight = Math.max(1, height - padding.top - padding.bottom);
    const maximum = Math.max(...samples.map(sample => Number(sample.cumulative?.total_tokens) || 0), 1);
    const x = index => padding.left + (samples.length === 1 ? chartWidth / 2 : chartWidth * index / (samples.length - 1));
    const yTotal = value => padding.top + chartHeight - (Number(value) || 0) / maximum * chartHeight;
    const yContext = value => padding.top + chartHeight - Math.max(0, Math.min(100, Number(value) || 0)) / 100 * chartHeight;
    canvas.plotState = { kind: 'session', samples, width, height, padding, chartWidth, chartHeight, x, yTotal, yContext };

    context.font = '12px Segoe UI, sans-serif';
    for (let tick = 0; tick < 3; tick += 1) {
      const yPosition = padding.top + chartHeight * tick / 2;
      context.strokeStyle = '#e7edf1';
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(padding.left, yPosition);
      context.lineTo(width - padding.right, yPosition);
      context.stroke();
      context.fillStyle = '#526a7b';
      context.textAlign = 'right';
      context.fillText(formatTokens(maximum * (1 - tick / 2)), width - 4, yPosition - 3);
      context.textAlign = 'left';
      context.fillText(`${100 - tick * 50}٪`, 2, yPosition - 3);
    }

    const gradient = context.createLinearGradient(0, padding.top, 0, padding.top + chartHeight);
    gradient.addColorStop(0, `${color}26`);
    gradient.addColorStop(1, `${color}00`);
    context.beginPath();
    samples.forEach((sample, index) => index ? context.lineTo(x(index), yTotal(sample.cumulative?.total_tokens)) : context.moveTo(x(index), yTotal(sample.cumulative?.total_tokens)));
    context.lineTo(x(samples.length - 1), padding.top + chartHeight);
    context.lineTo(x(0), padding.top + chartHeight);
    context.closePath();
    context.fillStyle = gradient;
    context.fill();

    context.beginPath();
    samples.forEach((sample, index) => index ? context.lineTo(x(index), yTotal(sample.cumulative?.total_tokens)) : context.moveTo(x(index), yTotal(sample.cumulative?.total_tokens)));
    context.strokeStyle = color;
    context.lineWidth = 2.5;
    context.lineJoin = 'round';
    context.stroke();

    context.beginPath();
    context.setLineDash([4, 4]);
    context.moveTo(padding.left, yContext(80));
    context.lineTo(width - padding.right, yContext(80));
    context.strokeStyle = '#8b4c16';
    context.lineWidth = 1.5;
    context.stroke();
    context.setLineDash([]);

    const contextPoints = samples.map((sample, index) => ({ index, value: Number(sample.context?.used_percent) }))
      .filter(point => Number.isFinite(point.value));
    context.beginPath();
    contextPoints.forEach((point, index) => index ? context.lineTo(x(point.index), yContext(point.value)) : context.moveTo(x(point.index), yContext(point.value)));
    context.strokeStyle = '#a63f60';
    context.lineWidth = 2.5;
    context.stroke();

    context.fillStyle = '#526a7b';
    context.textAlign = 'center';
    const ticks = [...new Set([0, Math.floor((samples.length - 1) / 2), samples.length - 1])];
    for (const index of ticks) {
      context.fillText(formatAxisTime(new Date(samples[index].timestamp)), x(index), height - 5);
    }
  }

  function crossingPoints(samples) {
    let previous = -1;
    const points = [];
    for (const sample of samples) {
      const value = Number(sample.context?.used_percent);
      if (!Number.isFinite(value)) continue;
      if (value >= 80 && previous < 80) points.push(sample);
      previous = value;
    }
    return points;
  }

  function renderPressure(card, samples) {
    let root = card.querySelector('.pressure-foot');
    if (!root) {
      root = document.createElement('div');
      root.className = 'pressure-foot';
      root.setAttribute('aria-label', 'ملخص ضغط السياق');
      card.append(root);
    }
    root.replaceChildren();
    const peak = samples.reduce((best, sample) => {
      const value = Number(sample.context?.used_percent);
      return Number.isFinite(value) && (!best || value > Number(best.context.used_percent)) ? sample : best;
    }, null);

    if (peak) {
      const peakLine = document.createElement('p');
      peakLine.append(document.createTextNode(`أعلى ضغط سياق: ${formatPercent(peak.context.used_percent)} عند ${formatDate(peak.timestamp)}`));
      root.append(peakLine);
    } else {
      const unavailable = document.createElement('p');
      unavailable.textContent = 'لا تتوفر قراءات ضغط السياق لهذه الجلسة.';
      root.append(unavailable);
    }

    const crossings = crossingPoints(samples);
    if (!crossings.length) {
      const note = document.createElement('p');
      note.textContent = 'لم تسجل العينات المعروضة تجاوزًا لضغط سياق 80٪.';
      root.append(note);
      return;
    }
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = `مواضع بلوغ ضغط سياق 80٪ (${number.format(crossings.length)})`;
    const list = document.createElement('ul');
    for (const sample of crossings) {
      const item = document.createElement('li');
      item.textContent = `${formatPercent(sample.context.used_percent)} · ${formatDate(sample.timestamp)}`;
      list.append(item);
    }
    details.append(summary, list);
    root.append(details);
  }

  function renderSessionCharts(sessions) {
    for (const spec of specs) {
      const session = sessions.find(item => item.session_id === spec.id);
      const samples = (session?.samples || [])
        .filter(sample => Number.isFinite(Date.parse(sample.timestamp)) && Number.isFinite(Number(sample.cumulative?.total_tokens)))
        .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
      const canvas = $(`chart-${spec.key}`);
      const card = canvas.closest('.chart-card');
      const last = samples[samples.length - 1];
      const title = session?.session_name || spec.name;
      $(`total-${spec.key}`).textContent = last ? formatTokens(last.cumulative.total_tokens) : '—';
      $(`meta-${spec.key}`).textContent = last
        ? `${session.model || last.model || 'نموذج غير محدد'} · ${number.format(samples.length)} عينة · آخرها ${formatDate(last.timestamp)}`
        : 'لا توجد بيانات لهذه الجلسة';
      $(`empty-${spec.key}`).classList.toggle('show', !samples.length);
      plotSession(canvas, samples, spec.color);

      if (samples.length) {
        const firstTotal = Number(samples[0].cumulative?.total_tokens) || 0;
        const lastTotal = Number(last.cumulative?.total_tokens) || 0;
        const peak = samples.reduce((best, sample) => {
          const value = Number(sample.context?.used_percent);
          return Number.isFinite(value) && (!best || value > Number(best.context.used_percent)) ? sample : best;
        }, null);
        const summaryParts = [`${number.format(samples.length)} عينة زمنية`];
        summaryParts.push(`الإجمالي التراكمي من ${formatTokens(firstTotal)} إلى ${formatTokens(lastTotal)}`);
        if (peak) summaryParts.push(`أعلى ضغط سياق ${formatPercent(peak.context.used_percent)} عند ${formatDate(peak.timestamp)}`);
        $(`summary-${spec.key}`).textContent = `${title}: ${summaryParts.join('؛ ')}.`;
        canvas.setAttribute('aria-label', `مخطط ${title}: إجمالي التوكنز وضغط السياق. استخدم الأسهم للتنقل بين النقاط.`);
      } else {
        $(`summary-${spec.key}`).textContent = `لا توجد عينات متاحة لمخطط ${title}.`;
        canvas.setAttribute('aria-label', `لا توجد بيانات لمخطط ${title}`);
      }
      renderPressure(card, samples);
    }
  }

  function setupChartInteraction(canvas, tooltip, label) {
    const parent = canvas.parentElement;
    const guide = document.createElement('div');
    guide.className = 'chart-hover-guide';
    guide.setAttribute('aria-hidden', 'true');
    const tokenDot = document.createElement('i');
    tokenDot.className = 'chart-hover-dot token-dot';
    const contextDot = document.createElement('i');
    contextDot.className = 'chart-hover-dot context-dot';
    const trendDots = specs.map(spec => {
      const dot = document.createElement('i');
      dot.className = 'chart-hover-dot';
      dot.style.background = spec.color;
      dot.hidden = true;
      return dot;
    });
    guide.append(tokenDot, contextDot, ...trendDots);
    parent.append(guide);
    let selectedIndex = -1;

    function hide() {
      tooltip.hidden = true;
      guide.hidden = true;
      trendDots.forEach(dot => { dot.hidden = true; });
      selectedIndex = -1;
    }

    function show(index, announce = false) {
      const state = canvas.plotState;
      if (!state) return hide();
      const count = state.kind === 'trend' ? state.times.length : state.samples.length;
      if (!count) return hide();
      selectedIndex = Math.max(0, Math.min(count - 1, index));
      const parentRect = parent.getBoundingClientRect();
      const canvasRect = canvas.getBoundingClientRect();
      const localX = state.x(selectedIndex) + canvasRect.left - parentRect.left;
      let localY;
      if (state.kind === 'trend') {
        const timestamp = state.times[selectedIndex];
        localY = state.padding.top + state.chartHeight / 2 + canvasRect.top - parentRect.top;
        tokenDot.hidden = true;
        contextDot.hidden = true;
        const rows = state.series.map((item, index) => {
          const value = item.values[selectedIndex];
          const dot = trendDots[index];
          dot.hidden = !Number.isFinite(value);
          if (Number.isFinite(value)) dot.style.top = `${state.y(value) - state.padding.top}px`;
          return `${item.spec.name}: ${Number.isFinite(value) ? `${formatTokens(value)} توكن` : 'لا توجد عينة'}`;
        });
        tooltip.textContent = `${formatDate(timestamp)} · ${rows.join(' · ')}`;
      } else {
        const sample = state.samples[selectedIndex];
        const tokenY = state.yTotal(sample.cumulative?.total_tokens) + canvasRect.top - parentRect.top;
        const contextValue = Number(sample.context?.used_percent);
        const hasContext = Number.isFinite(contextValue);
        localY = tokenY;
        tokenDot.hidden = false;
        contextDot.hidden = !hasContext;
        tokenDot.style.top = `${state.yTotal(sample.cumulative?.total_tokens) - state.padding.top}px`;
        if (hasContext) contextDot.style.top = `${state.yContext(contextValue) - state.padding.top}px`;
        tooltip.textContent = `${formatDate(sample.timestamp)} · التوكنز: ${formatTokens(sample.cumulative?.total_tokens)} · ضغط السياق: ${formatPercent(contextValue)}`;
      }
      guide.hidden = false;
      guide.style.left = `${localX}px`;
      guide.style.top = `${canvasRect.top - parentRect.top + state.padding.top}px`;
      guide.style.height = `${state.chartHeight}px`;
      tooltip.hidden = false;
      tooltip.style.left = `${Math.max(8, Math.min(parent.clientWidth - 245, localX + 12))}px`;
      tooltip.style.top = `${Math.max(4, Math.min(parent.clientHeight - 58, localY - 44))}px`;
      if (announce) {
        $('chart-announcement').textContent = `${label}: ${tooltip.textContent}. نقطة ${number.format(selectedIndex + 1)} من ${number.format(count)}.`;
      }
    }

    canvas.addEventListener('pointermove', event => {
      if (event.pointerType === 'touch') return;
      const state = canvas.plotState;
      if (!state) return;
      const rect = canvas.getBoundingClientRect();
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      const count = state.kind === 'trend' ? state.times.length : state.samples.length;
      let nearest = -1;
      let distance = Infinity;
      for (let index = 0; index < count; index += 1) {
        if (state.kind === 'trend') {
          for (const item of state.series) {
            const value = item.values[index];
            if (!Number.isFinite(value)) continue;
            const d = Math.hypot(state.x(index) - px, state.y(value) - py);
            if (d < distance) { nearest = index; distance = d; }
          }
        } else {
          const lineY = state.yTotal(state.samples[index].cumulative?.total_tokens);
          const d = Math.hypot(state.x(index) - px, lineY - py);
          if (d < distance) { nearest = index; distance = d; }
          const contextValue = Number(state.samples[index].context?.used_percent);
          if (Number.isFinite(contextValue)) {
            const contextDistance = Math.hypot(state.x(index) - px, state.yContext(contextValue) - py);
            if (contextDistance < distance) { nearest = index; distance = contextDistance; }
          }
        }
      }
      if (distance <= 22) show(nearest);
      else if (document.activeElement !== canvas) hide();
    });
    canvas.addEventListener('pointerleave', () => { if (document.activeElement !== canvas) hide(); });
    canvas.addEventListener('pointerdown', event => {
      if (event.pointerType !== 'touch') return;
      const rect = canvas.getBoundingClientRect();
      const state = canvas.plotState;
      if (!state) return;
      const count = state.kind === 'trend' ? state.times.length : state.samples.length;
      let nearest = 0;
      let delta = Infinity;
      for (let i = 0; i < count; i += 1) {
        const dx = Math.abs(state.x(i) - (event.clientX - rect.left));
        if (dx < delta) { delta = dx; nearest = i; }
      }
      show(nearest);
      window.setTimeout(() => { if (document.activeElement !== canvas) hide(); }, 2500);
    });
    canvas.addEventListener('focus', () => {
      const state = canvas.plotState;
      if (state) show(selectedIndex < 0 ? (state.kind === 'trend' ? state.times.length : state.samples.length) - 1 : selectedIndex);
    });
    canvas.addEventListener('blur', hide);
    canvas.addEventListener('keydown', event => {
      const state = canvas.plotState;
      if (!state) return;
      const count = state.kind === 'trend' ? state.times.length : state.samples.length;
      let next = selectedIndex;
      if (event.key === 'ArrowLeft') next -= 1;
      else if (event.key === 'ArrowRight') next += 1;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = count - 1;
      else if (event.key === 'Escape') { hide(); return; }
      else return;
      event.preventDefault();
      show(next, true);
    });
  }

  function renderWeekly(weekly) {
    if (!weekly || !Number.isFinite(Number(weekly.remaining_percent)) || !Number.isFinite(Number(weekly.used_percent))) {
      $('weekly-empty').classList.add('show');
      $('weekly-reset').textContent = 'لا تتوفر قراءة أسبوعية في السجلات المحلية.';
      $('weekly-remaining').textContent = 'غير متاح';
      $('weekly-used').textContent = '—';
      $('weekly-remaining-foot').textContent = '—';
      $('weekly-fill').style.width = '0%';
      $('weekly-track').setAttribute('aria-valuenow', '0');
      $('weekly-track').setAttribute('aria-valuetext', 'لا تتوفر قراءة أسبوعية');
      return;
    }
    const remaining = Math.max(0, Math.min(100, Number(weekly.remaining_percent)));
    const used = Math.max(0, Math.min(100, Number(weekly.used_percent)));
    $('weekly-remaining').textContent = `${formatPercent(remaining)} متبقية`;
    $('weekly-used').textContent = formatPercent(used);
    $('weekly-remaining-foot').textContent = formatPercent(remaining);
    $('weekly-fill').style.width = `${remaining}%`;
    $('weekly-fill').style.background = remaining <= 20
      ? 'linear-gradient(90deg,#a63f3f,#cc6b55)'
      : remaining <= 40
        ? 'linear-gradient(90deg,#8b5a12,#c08a2b)'
        : 'linear-gradient(90deg,#08756e,#329081)';
    $('weekly-track').setAttribute('aria-valuenow', String(Math.round(remaining * 10) / 10));
    $('weekly-track').setAttribute('aria-valuetext', `${formatPercent(remaining)} متبقية، ${formatPercent(used)} مستخدمة`);
    const reset = Number(weekly.resets_at);
    $('weekly-reset').textContent = `آخر قراءة ${formatDate(weekly.timestamp)}${Number.isFinite(reset) && reset > 0 ? ` · إعادة الضبط ${formatDate(reset * 1000)}` : ''}`;
    $('weekly-empty').classList.remove('show');
  }

  function render(data) {
    latestData = data;
    const sessions = Array.isArray(data.sessions) ? data.sessions : [];
    const activeSessions = sessions.filter(session => activeSessionIds.has(session.session_id));
    const measured = sessions.map(session => ({ session, sample: lastSample(session) })).filter(item => item.sample);
    const activeMeasured = activeSessions.map(session => ({ session, sample: lastSample(session) })).filter(item => item.sample);
    const contextValues = activeMeasured.map(item => Number(item.sample.context?.used_percent)).filter(Number.isFinite);
    const total = measured.reduce((sum, item) => sum + (Number(item.sample.cumulative?.total_tokens) || 0), 0);
    $('total-tokens').textContent = formatTokens(total);
    $('total-token-scope').textContent = `آخر قراءة لـ ${formatNumber(measured.length)} جلسات مسجلة؛ ${formatNumber(activeMeasured.length)} حالية`;
    $('session-count').textContent = formatNumber(activeMeasured.length);
    $('active-note').textContent = `من أصل ${formatNumber(specs.length)} جلسات حالية`;
    $('avg-context').textContent = contextValues.length
      ? formatPercent(contextValues.reduce((sum, value) => sum + value, 0) / contextValues.length)
      : '—';
    $('peak-context').textContent = contextValues.length ? formatPercent(Math.max(...contextValues)) : '—';
    renderBreakdown(sessions);
    renderSessionTable(activeSessions);
    renderWeekly(data.weekly);
    drawTrend(sessions);
    renderSessionCharts(sessions);
    $('generated-at').textContent = `توليد استجابة اللوحة: ${formatDate(data.generated_at)}`;
    $('updated-badge').textContent = `${formatNumber(activeMeasured.length)} جلسات نشطة`;

    const sampleTimes = activeSessions.map(session => Date.parse(lastSample(session)?.timestamp || ''));
    if (data.weekly?.timestamp) sampleTimes.push(Date.parse(data.weekly.timestamp));
    const validSampleTimes = sampleTimes.filter(Number.isFinite);
    const latestSampleTime = validSampleTimes.length ? Math.max(...validSampleTimes) : NaN;
    const sampleAge = Date.now() - latestSampleTime;
    const fresh = Number.isFinite(latestSampleTime) && sampleAge >= 0 && sampleAge < 150000;
    const latestSampleText = Number.isFinite(latestSampleTime) ? formatDate(latestSampleTime) : null;

    setDotState('live-status-dot', 'is-current');
    setDotState('usage-status-dot', fresh ? 'is-current' : 'is-stale');
    $('live-status').textContent = latestSampleText
      ? `قاعدة البيانات متصلة · آخر عينة ${latestSampleText}`
      : 'قاعدة البيانات متصلة · لا توجد عينات محفوظة';
    $('usage-status-state').textContent = fresh ? 'العينة حديثة' : 'العينة قديمة';
    $('usage-status-updated').textContent = latestSampleText
      ? `آخر عينة SQLite: ${latestSampleText}`
      : 'لا توجد عينة محفوظة في SQLite';
  }

  async function refresh(manual = false) {
    if (request) {
      if (manual) manualRefreshQueued = true;
      return request;
    }
    const button = $('refresh');
    if (manual) {
      $('announcement').textContent = 'جار تحديث البيانات…';
      button.textContent = 'جار التحديث…';
    }
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    request = (async () => {
      try {
        const response = await fetch(`/api/dashboard?v=${Date.now()}`, { cache: 'no-store' });
        if (!response.ok) throw new Error('تعذر قراءة قاعدة بيانات القياس المحلية.');
        const data = await response.json();
        render(data);
        if (manual) {
          $('live-status').textContent = 'تم التحديث الآن';
          $('announcement').textContent = 'تم تحديث بيانات القياس الآن.';
        }
      } catch (error) {
        $('live-status').textContent = 'تعذر تحميل القياس المحلي';
        setDotState('live-status-dot', 'is-error');
        $('announcement').textContent = 'تعذر تحميل القياس المحلي. استخدم زر تحديث الآن للمحاولة مجددًا.';
        $('usage-status-state').textContent = 'تعذر التحديث';
        setDotState('usage-status-dot', 'is-error');
        $('usage-status-updated').textContent = 'تحقق من أن المسجل المحلي يعمل ثم أعد المحاولة.';
        if (!latestData) $('sessions-empty').hidden = false;
      } finally {
        button.disabled = false;
        button.removeAttribute('aria-busy');
        button.textContent = 'تحديث الآن ↻';
        request = null;
        if (manualRefreshQueued) {
          manualRefreshQueued = false;
          refresh(true);
        }
      }
    })();
    return request;
  }

  $('refresh').addEventListener('click', () => refresh(true));
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh(false);
  });
  setupChartInteraction($('trend'), $('tooltip-trend'), 'اتجاه الإجمالي');
  for (const spec of specs) setupChartInteraction($(`chart-${spec.key}`), $(`tooltip-${spec.key}`), spec.name);
  window.addEventListener('resize', () => {
    if (!latestData) return;
    drawTrend(latestData.sessions || []);
    renderSessionCharts(latestData.sessions || []);
  });
  refresh();
  window.setInterval(() => refresh(false), 60000);
})();
