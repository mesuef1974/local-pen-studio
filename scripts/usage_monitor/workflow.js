(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const stages = [
    { code: 'queued', label: 'في الطابور' },
    { code: 'assigned', label: 'مسندة' },
    { code: 'in_progress', label: 'قيد التنفيذ' },
    { code: 'blocked', label: 'متعذرة' },
    { code: 'returned', label: 'معادة للتنفيذ' },
    { code: 'delivered', label: 'تم التحقق من الدفع' },
    { code: 'verifying', label: 'قيد فحوص الجودة بعد الدفع' },
    { code: 'completed', label: 'مكتملة' },
    { code: 'failed', label: 'فشلت' },
    { code: 'archived', label: 'مؤرشفة' },
  ];
  const boardStages = stages.filter(stage => !['completed', 'failed', 'blocked', 'archived'].includes(stage.code));
  const terminalLabels = { completed: 'مكتملة', failed: 'فشلت', blocked: 'متعذرة', archived: 'مؤرشفة' };
  const arabicNumber = new Intl.NumberFormat('ar-QA', { maximumFractionDigits: 1, numberingSystem: 'latn' });
  const dateTime = new Intl.DateTimeFormat('ar-QA', {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    hourCycle: 'h23', numberingSystem: 'latn', timeZone: 'Asia/Qatar',
  });
  const priorityLabels = { low: 'منخفضة', normal: 'عادية', high: 'عالية', urgent: 'عاجلة' };
  const eventLabels = {
    card_created: 'إنشاء البطاقة', card_assigned: 'إسناد إلى جلسة', blocker_observed: 'تسجيل عائق',
    status_transition: 'تغيير الحالة', delivery_attempt: 'محاولة تسليم', validation_result: 'نتيجة تحقق',
    quality_run: 'تشغيل فحوص الجودة', session_started: 'بدء التنفيذ', progress_update: 'تحديث التقدم',
    acceptance_criteria_imported: 'تسجيل معايير الإنجاز', card_queued_to_session: 'إرسال البطاقة للجلسة',
    card_reassigned: 'إعادة إسناد البطاقة', completion_policy_corrected: 'تحديث سياسة الإكمال',
    deliverable_registered: 'تسجيل مخرج', delivery_verification_recorded: 'تسجيل التحقق من التسليم',
    git_commit: 'تسجيل الالتزام', git_push: 'تسجيل الدفع إلى Git', owner_decision_recorded: 'تسجيل قرار المالك',
    review_finding: 'نتيجة المراجعة', session_opinion_recorded: 'تسجيل رأي الجلسة',
    terminal_assignment_closed: 'إغلاق إسناد منتهٍ',
  };
  const issueLabels = {
    path_limit_mismatch: 'اختلاف حد المسارات', cpu_bound_centerline: 'بطء استخراج الخط المركزي',
    routing_test_fixture_missing: 'ملف اختبار توجيه مفقود',
  };
  const criterionLabels = {
    automated_delivery_qa: 'فحوص جودة التسليم الآلية', path_limit_contract: 'توحيد حد المسارات',
    centerline_profile_fidelity: 'قياس أداء الخط المركزي ومطابقة المخرجات', routing_fixture_ci: 'اختبار التوجيه في CI',
    fresh_main_delivery: 'تسليم من main حديث', 'API loopback': 'واجهة API المحلية',
    'SQLite v4 migration': 'ترحيل SQLite v4',
  };
  const checkMethodLabels = {
    automated_quality_gate: 'بوابة جودة آلية', automated_tests: 'اختبارات آلية',
    benchmark_and_fidelity_report: 'قياس أداء ومطابقة', ci_test: 'اختبار التكامل المستمر',
    git_remote_ref: 'التحقق من الفرع البعيد', git_remote_sha_match: 'مطابقة الالتزام مع الفرع البعيد',
    migration_tests_and_integrity: 'اختبارات الترحيل وسلامة البيانات',
    unit_tests_and_backup_integrity: 'اختبارات الوحدات وسلامة النسخة الاحتياطية',
    unit_tests_and_live_api: 'اختبارات الوحدات وواجهة API',
  };
  const outcomeLabels = { pass: 'اجتاز', passed: 'اجتاز', fail: 'فشل', failed: 'فشل', pending: 'قيد الانتظار', accepted: 'مقبول', sent: 'أُرسل', unresolved: 'غير محلول', resolved: 'تم الحل' };
  const outboxStates = {
    pending: ['بانتظار الإرسال', 'pending'], queued: ['في الطابور', 'pending'],
    processing: ['قيد الإرسال', 'processing'], sent: ['وُضع في الجلسة', 'sent'],
    retry: ['ستُعاد المحاولة', 'retry'], dead_letter: ['تعذر الإرسال آليًا', 'failed'],
    failure: ['فشل الإرسال', 'failed'], failed: ['فشل الإرسال', 'failed'],
  };
  let currentBoard = null;
  let currentCardId = null;
  let boardController = null;
  let searchTimer = 0;
  let commandIdempotencyKey = null;
  let commandPayloadSignature = null;

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function safeText(value, fallback = '—') {
    return value === null || value === undefined || String(value).trim() === '' ? fallback : String(value);
  }

  function formatDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? safeText(value) : dateTime.format(date);
  }

  function formatDuration(value) {
    if (value === null || value === undefined || value === '') return '—';
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds < 0) return '—';
    if (seconds < 60) return `${arabicNumber.format(seconds)} ث`;
    const minutes = seconds / 60;
    if (minutes < 60) return `${arabicNumber.format(minutes)} د`;
    const hours = minutes / 60;
    if (hours < 48) return `${arabicNumber.format(hours)} س`;
    return `${arabicNumber.format(hours / 24)} يوم`;
  }

  function formatPercent(value) {
    if (value === null || value === undefined || value === '') return '—';
    const number = Number(value);
    return Number.isFinite(number) ? `${arabicNumber.format(number)}٪` : '—';
  }

  function describe(value) {
    if (value === null || value === undefined || value === '') return '';
    let parsed = value;
    if (typeof parsed === 'string') {
      try { parsed = JSON.parse(parsed); } catch { return parsed; }
    }
    if (Array.isArray(parsed)) return parsed.map(describe).filter(Boolean).join(' · ');
    if (parsed && typeof parsed === 'object') {
      const preferred = ['message', 'summary', 'note', 'description', 'reason', 'impact_summary']
        .map(key => parsed[key]).filter(item => item !== null && item !== undefined && item !== '');
      if (preferred.length) return preferred.map(describe).join(' · ');
      return Object.entries(parsed).map(([key, item]) => `${key}: ${describe(item)}`).filter(Boolean).join(' · ');
    }
    return String(parsed);
  }

  async function requestJSON(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && options.method !== 'GET') {
      headers.set('Content-Type', 'application/json');
      headers.set('X-Workflow-Request', '1');
      const csrfCookie = document.cookie.split('; ').find((cookie) => cookie.startsWith('csrftoken='));
      if (csrfCookie) headers.set('X-CSRFToken', decodeURIComponent(csrfCookie.slice('csrftoken='.length)));
    }
    const response = await fetch(url, { cache: 'no-store', ...options, headers });
    let data;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok) {
      const message = data?.error?.message || `تعذر إتمام الطلب (HTTP ${response.status}).`;
      throw new Error(message);
    }
    return data;
  }

  function setConnection(state, label) {
    const root = $('workflow-connection');
    root.dataset.state = state;
    root.querySelector('span').textContent = label;
  }

  function setLoading(loading) {
    $('workflow-loading').hidden = !loading;
    $('workflow-board-scroll').hidden = loading || !currentBoard;
    $('workflow-empty').hidden = true;
    $('workflow-error').hidden = true;
    $('workflow-board').setAttribute('aria-busy', String(loading));
    $('workflow-refresh').disabled = loading;
    $('workflow-refresh').setAttribute('aria-busy', String(loading));
    if (loading) setConnection('busy', 'جار الاتصال بالخدمة…');
  }

  function statusLabel(card) {
    const code = card.status_code || card.current_status_code || '';
    const stage = stages.find(item => item.code === code);
    return safeText(card.status_label, terminalLabels[code] || stage?.label || code || 'حالة غير معروفة');
  }

  function statusCode(card) {
    return card.status_code || card.current_status_code || '';
  }

  function isSessionActor(session) {
    return session.active !== false;
  }

  function fillFilters(sessions) {
    const actor = $('workflow-actor');
    const selected = actor.value;
    actor.replaceChildren(new Option('كل الجهات', ''));
    actor.add(new Option('المالك', 'owner'));
    for (const session of sessions) {
      if (!isSessionActor(session)) continue;
      actor.add(new Option(safeText(session.display_name, session.actor_id), session.actor_id));
    }
    if ([...actor.options].some(option => option.value === selected)) actor.value = selected;
    const status = $('workflow-status');
    const current = status.value;
    status.replaceChildren(new Option('كل الحالات', ''));
    boardStages.forEach(stage => status.add(new Option(stage.label, stage.code)));
    if (boardStages.some(stage => stage.code === current)) status.value = current;
  }

  function cardButton(card) {
    const titleText = safeText(card.display_title || card.title, 'بطاقة بلا عنوان');
    const button = element('button', undefined, 'workflow-card');
    button.type = 'button';
    button.dataset.cardId = card.card_id;
    button.dataset.status = statusCode(card);
    button.setAttribute('aria-label', `${safeText(card.card_id)}، ${titleText}، ${statusLabel(card)}. عرض التفاصيل`);
    const id = element('span', safeText(card.card_id), 'workflow-card-id');
    const title = element('span', titleText, 'workflow-card-title');
    const meta = element('span', undefined, 'workflow-card-meta');
    const status = element('span', statusLabel(card), 'workflow-status-label');
    status.dataset.status = statusCode(card);
    const hasPassedCriteria = card.criteria_passed !== null && card.criteria_passed !== undefined;
    const progress = Number(card.criteria_total) > 0
      ? `${hasPassedCriteria ? `${arabicNumber.format(Number(card.criteria_passed) || 0)}/` : ''}${arabicNumber.format(Number(card.criteria_total))} معيار`
      : safeText(card.priority_code, '');
    meta.append(status, element('span', progress));
    const foot = [];
    if (card.branch_name) foot.push(card.branch_name);
    if (card.commit_sha) foot.push(`Commit مسجل · SHA ${String(card.commit_sha).slice(0, 8)}`);
    if (card.qa_outcome) foot.push(`QA ${card.qa_outcome}`);
    if (card.owner_command) foot.push('أمر المالك');
    if (card.owner_target_name) foot.push(`التنفيذ لدى ${safeText(card.owner_target_name)}`);
    button.append(id, title, meta);
    if (foot.length) button.append(element('span', foot.join(' · '), 'workflow-card-meta'));
    button.addEventListener('click', () => openCard(card.card_id));
    return button;
  }

  function renderBoard(board) {
    const allCards = Array.isArray(board.cards) ? board.cards : [];
    const commandRootIds = new Set(allCards.filter(card => allCards.some(child => child.parent_card_id === card.card_id)).map(card => card.card_id));
    const cards = allCards.filter(card => !commandRootIds.has(card.card_id)
      && !['completed', 'failed', 'blocked', 'archived'].includes(statusCode(card)));
    const ownerCards = (Array.isArray(board.owner_cards) ? board.owner_cards : [])
      .filter(card => !['completed', 'failed', 'blocked', 'archived'].includes(statusCode(card)));
    const sessions = Array.isArray(board.sessions) ? board.sessions : [];
    fillFilters(sessions);
    $('workflow-card-count').textContent = `${arabicNumber.format(cards.length)} تنفيذ · ${arabicNumber.format(ownerCards.length)} للمالك`;
    const root = $('workflow-board-grid');
    root.replaceChildren();
    const header = element('div', undefined, 'workflow-grid-header');
    header.append(element('div', 'المالك / الجلسة'));
    boardStages.forEach(stage => header.append(element('div', stage.label)));
    root.append(header);

    const ownerLane = {session: {actor_id: 'owner', display_name: 'المالك', charter: 'أوامر المالك؛ وتظهر مهامها في صف الجلسة المسندة.'}, cards: ownerCards};
    const sessionLanes = sessions.filter(isSessionActor).map(session => ({ session, cards: cards.filter(card => card.assigned_actor_id === session.actor_id) }));
    const knownActors = new Set(sessionLanes.map(lane => lane.session.actor_id));
    const unassigned = cards.filter(card => !card.assigned_actor_id || !knownActors.has(card.assigned_actor_id));
    const terminalStatuses = new Set(['completed', 'failed', 'blocked', 'archived']);
    const awaitingRouting = unassigned.filter(card => !terminalStatuses.has(statusCode(card)));
    const terminalUnassigned = unassigned.filter(card => terminalStatuses.has(statusCode(card)));
    const lanes = [ownerLane];
    if (awaitingRouting.length) lanes.push({
      session: { actor_id: '', display_name: 'غير مسندة', charter: 'بانتظار توجيه المنسق' },
      cards: awaitingRouting,
    });
    if (terminalUnassigned.length) lanes.push({
      session: { actor_id: '', display_name: 'أوامر المالك المنتهية', charter: 'سجلات مكتملة أو مؤرشفة؛ لا تحتاج إلى توجيه' },
      cards: terminalUnassigned,
    });
    lanes.push(...sessionLanes);

    for (const lane of lanes) {
      const row = element('div', undefined, 'workflow-lane');
      const count = lane.cards.length;
      const name = element('strong', `${safeText(lane.session.display_name)} · ${arabicNumber.format(count)}`);
      const charter = element('small', safeText(lane.session.charter, 'جلسة نشطة'));
      const label = element('div', undefined, 'workflow-lane-title');
      label.append(name, charter);
      row.append(label);
      boardStages.forEach(stage => {
        const cell = element('div', undefined, 'workflow-stage-cell');
        const items = lane.cards.filter(card => card.status_code === stage.code);
        if (!items.length) cell.setAttribute('aria-label', `لا توجد بطاقات في مرحلة ${stage.label}`);
        items.forEach(card => cell.append(cardButton(card)));
        row.append(cell);
      });
      root.append(row);
    }
    if (!lanes.length) root.append(element('p', 'لا توجد جلسات مسجلة في خدمة التدفق.', 'workflow-empty-cell'));
    $('workflow-error').hidden = true;
    $('workflow-empty').hidden = cards.length + ownerCards.length > 0;
    $('workflow-board-scroll').hidden = lanes.length === 0;
    if (!cards.length) {
      const filtered = Boolean($('workflow-query').value.trim() || $('workflow-status').value || $('workflow-actor').value);
      $('workflow-empty').querySelector('h3').textContent = filtered ? 'لا توجد بطاقات تطابق الفلاتر' : 'لم تُسجل بطاقات بعد';
      $('workflow-empty').querySelector('p').textContent = filtered
        ? 'غيّر البحث أو أزل بعض الفلاتر لعرض بطاقات أخرى.'
        : 'ستظهر هنا أوامر المالك وبطاقاتها بعد تسجيلها في خدمة التدفق.';
    }
    setConnection('ready', `متصل · آخر تحديث ${formatDate(board.generated_at)}`);
    renderKPIs(board);
    renderCompletionSummary(board.completion_summary);
    renderArchive(board.session_history_groups, board.status_groups);
  }

  function renderArchive(groups, statuses) {
    const root = $('wf-archive-groups');
    root.replaceChildren();
    const records = [
      ...(Array.isArray(groups) ? groups : []).map(group => ({ ...group, kind: 'session' })),
      { actor_id: '__failed__', display_name: 'فشلت', kind: 'failed', cards: statuses?.failed || [] },
      { actor_id: '__blocked__', display_name: 'متعذرة', kind: 'blocked', cards: statuses?.blocked || [] },
      { actor_id: '__archived__', display_name: 'مؤرشفة', kind: 'archived', cards: statuses?.archived || [] },
    ];
    records.forEach(group => {
      const panel = element('section', undefined, 'workflow-archive-session');
      if (group.kind === 'failed') panel.classList.add('is-failed');
      if (group.kind === 'blocked') panel.classList.add('is-blocked');
      panel.setAttribute('aria-label', group.kind === 'session'
        ? `البطاقات المكتملة لجلسة ${safeText(group.display_name)}` : `البطاقات ${safeText(group.display_name)}`);
      panel.append(element('h4', safeText(group.display_name, 'جلسة سابقة')));
      const list = element('div', undefined, 'workflow-archive-list');
      const cards = Array.isArray(group.cards) ? group.cards : [];
      if (!cards.length) {
        const emptyLabel = { session: 'لا توجد بطاقات مكتملة.', failed: 'لا توجد بطاقات فاشلة.',
          blocked: 'لا توجد بطاقات متعذرة.', archived: 'لا توجد بطاقات مؤرشفة.' }[group.kind];
        list.append(element('p', emptyLabel, 'workflow-archive-empty'));
      } else {
        cards.forEach(card => {
          const button = element('button', safeText(card.title, 'بطاقة بلا عنوان'), 'workflow-archive-card');
          button.type = 'button';
          const context = group.kind === 'session' ? `في جلسة ${safeText(group.display_name)}` : `ضمن حالة ${safeText(group.display_name)}`;
          button.setAttribute('aria-label', `فتح بطاقة ${safeText(card.title)} ${context}`);
          button.addEventListener('click', () => openCard(card.card_id));
          list.append(button);
        });
      }
      panel.append(list);
      root.append(panel);
    });
  }

  function renderCompletionSummary(summary) {
    const ownerCommands = Array.isArray(summary?.completed_owner_commands) ? summary.completed_owner_commands : [];
    const sessions = Array.isArray(summary?.session_completions) ? summary.session_completions : [];
    $('wf-owner-commands-completed').textContent = arabicNumber.format(Number(summary?.owner_commands_completed) || 0);

    const sessionCounts = $('wf-session-completions');
    sessionCounts.replaceChildren();
    sessions.forEach(session => {
      const item = element('span', undefined, 'workflow-session-completion');
      item.setAttribute('role', 'listitem');
      item.append(
        element('span', safeText(session.display_name)),
        element('strong', arabicNumber.format(Number(session.completed_count) || 0)),
      );
      sessionCounts.append(item);
    });

    const history = $('wf-completed-history');
    history.replaceChildren();
    if (!ownerCommands.length) {
      history.append(element('p', 'لا توجد أوامر مالك مكتملة بعد.', 'workflow-completed-empty'));
      return;
    }
    ownerCommands.forEach(card => {
      const item = element('button', undefined, 'workflow-completed-item');
      item.type = 'button';
      item.setAttribute('aria-label', `فتح تفاصيل الأمر المكتمل ${safeText(card.card_id)}`);
      item.append(
        element('span', safeText(card.title, 'أمر مالك')),
        element('small', safeText(card.card_id)),
      );
      item.addEventListener('click', () => openCard(card.card_id));
      history.append(item);
    });
  }

  function renderKPIs(board) {
    const allCards = Array.isArray(board.cards) ? board.cards : [];
    const cards = allCards.filter(card => !['completed', 'failed', 'blocked', 'archived'].includes(statusCode(card)));
    const count = (...codes) => cards.filter(card => codes.includes(statusCode(card))).length;
    $('wf-kpi-total').textContent = arabicNumber.format(cards.length);
    $('wf-kpi-active').textContent = arabicNumber.format(count('assigned', 'in_progress', 'returned'));
    $('wf-kpi-blocked').textContent = arabicNumber.format(allCards.filter(card => statusCode(card) === 'blocked').length);
    $('wf-kpi-push-verified').textContent = arabicNumber.format(count('delivered'));
    $('wf-kpi-qa-in-progress').textContent = arabicNumber.format(count('verifying'));
  }

  function renderMetrics(data) {
    const summary = data?.summary || {};
    $('wf-metric-assignment').textContent = formatDuration(summary.median_assignment_seconds);
    $('wf-metric-cycle').textContent = formatDuration(summary.median_cycle_seconds);
    const rate = value => {
      if (value === null || value === undefined || value === '') return null;
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed * (parsed <= 1 ? 100 : 1) : null;
    };
    $('wf-metric-qa').textContent = formatPercent(rate(summary.first_pass_qa_rate));
    $('wf-metric-push').textContent = formatPercent(rate(summary.push_verified_rate));
    $('wf-metrics-updated').textContent = data?.generated_at ? `آخر احتساب ${formatDate(data.generated_at)}` : 'المؤشرات غير متاحة';
  }

  async function loadMetrics() {
    try { renderMetrics(await requestJSON('/api/workflow/metrics')); }
    catch {
      renderMetrics(null);
      $('wf-metrics-updated').textContent = 'تعذر تحميل المؤشرات؛ أعد تحديث اللوحة.';
    }
  }

  async function loadBoard({ showLoading = true } = {}) {
    if (boardController) boardController.abort();
    boardController = new AbortController();
    const params = new URLSearchParams();
    if ($('workflow-status').value) params.set('status', $('workflow-status').value);
    if ($('workflow-actor').value) params.set('actor_id', $('workflow-actor').value);
    if ($('workflow-query').value.trim()) params.set('q', $('workflow-query').value.trim());
    const url = `/api/workflow/board${params.size ? `?${params}` : ''}`;
    if (showLoading) setLoading(true);
    try {
      const board = await requestJSON(url, { signal: boardController.signal });
      currentBoard = board;
      $('workflow-loading').hidden = true;
      $('workflow-error').hidden = true;
      $('workflow-board').setAttribute('aria-busy', 'false');
      $('workflow-refresh').disabled = false;
      $('workflow-refresh').removeAttribute('aria-busy');
      renderBoard(board);
      await loadMetrics();
    } catch (error) {
      if (error.name === 'AbortError') return;
      $('workflow-loading').hidden = true;
      $('workflow-board-scroll').hidden = true;
      $('workflow-empty').hidden = true;
      $('workflow-error').hidden = false;
      $('workflow-error-message').textContent = error.message || 'تعذر الاتصال بخدمة التدفق المحلية.';
      $('workflow-board').setAttribute('aria-busy', 'false');
      $('workflow-refresh').disabled = false;
      $('workflow-refresh').removeAttribute('aria-busy');
      setConnection('error', 'الخدمة غير متاحة');
    }
  }

  function section(title, items, renderItem, emptyText) {
    const wrapper = element('section', undefined, 'workflow-detail-section');
    wrapper.append(element('h3', title));
    if (!Array.isArray(items) || items.length === 0) {
      wrapper.append(element('p', emptyText || 'لا توجد سجلات بعد.', 'workflow-detail-empty'));
      return wrapper;
    }
    const list = element('ol');
    items.forEach(item => list.append(renderItem(item)));
    wrapper.append(list);
    return wrapper;
  }

  function detailItem(title, detail, time) {
    const item = element('li');
    item.append(element('strong', safeText(title, 'حدث')));
    const detailText = describe(detail);
    if (detailText) item.append(element('div', detailText));
    if (time) {
      const timeNode = element('time', formatDate(time));
      timeNode.dateTime = time;
      item.append(timeNode);
    }
    return item;
  }

  function appendFacts(root, card, deliveries = []) {
    const facts = element('div', undefined, 'workflow-detail-facts');
    const latestDelivery = deliveries[deliveries.length - 1];
    const branchName = card.branch_name || latestDelivery?.branch_name;
    const commitSha = card.commit_sha || latestDelivery?.commit_sha;
    const pairs = [
      ['الحالة', statusLabel(card)], ['الجلسة المسؤولة', safeText(card.assigned_actor_name)],
      ['النطاق', safeText(card.scope)], ['الأولوية', priorityLabels[card.priority_code] || safeText(card.priority_code)],
      ['الفرع', safeText(branchName)], ['Commit', safeText(commitSha)],
      ['التحقق من الدفع', deliverySummary(deliveries)], ['نتيجة QA', outcomeLabels[card.qa_outcome] || safeText(card.qa_outcome)],
      ['تاريخ الإنشاء', formatDate(card.created_at)], ['آخر تحديث', formatDate(card.updated_at)],
    ];
    for (const [label, value] of pairs) {
      const fact = element('div');
      fact.append(element('span', label), element('strong', value));
      facts.append(fact);
    }
    root.append(facts);
  }

  function deliverySummary(deliveries) {
    const latest = deliveries[deliveries.length - 1];
    if (!latest) return 'لا توجد محاولة تسليم مسجلة';
    const verified = Boolean(latest.verified_at && latest.remote_commit_sha && latest.commit_sha
      && latest.remote_commit_sha.toLowerCase() === latest.commit_sha.toLowerCase());
    if (verified) return 'تم التحقق من تطابق SHA مع origin';
    if (latest.outcome === 'failed') return 'فشل التحقق من الدفع';
    if (latest.outcome) return 'محاولة مسجلة؛ لم يثبت الدفع بعد';
    return 'لا توجد محاولة تسليم مسجلة';
  }

  function outboxItem(item) {
    const code = String(item.state_code || '').toLowerCase();
    const [label, style] = outboxStates[code] || [safeText(item.state_code, 'حالة غير معروفة'), 'pending'];
    const session = (currentBoard?.sessions || []).find(actor => actor.actor_id === item.target_actor_id);
    const target = safeText(item.target_actor_name || session?.display_name, 'جلسة سابقة');
    const count = Number.isFinite(Number(item.attempt_count)) ? arabicNumber.format(Number(item.attempt_count)) : '—';
    const timing = item.sent_at ? `وقت الإرسال: ${formatDate(item.sent_at)}` : item.available_at ? `متاح للإرسال: ${formatDate(item.available_at)}` : '';
    const command = item.command_code === 'card_assignment' ? 'إسناد بطاقة' : 'إرسال تكليف';
    const detail = [`الجهة: ${target}`, `عدد المحاولات: ${count}`, timing, item.last_error_code && `رمز الخطأ: ${item.last_error_code}`].filter(Boolean).join(' · ');
    const row = detailItem(command, detail, item.sent_at || item.available_at);
    row.insertBefore(element('span', label, `workflow-outbox-state is-${style}`), row.firstChild);
    return row;
  }

  function renderCardDetails(data) {
    const card = data.card || {};
    $('workflow-detail-title').textContent = `${safeText(card.card_id, currentCardId)} · ${safeText(card.display_title || card.title, 'بطاقة')}`;
    const root = $('workflow-detail-content');
    root.replaceChildren();
    const lead = element('div', undefined, 'workflow-detail-lead');
    lead.append(element('strong', 'طلب المالك'), element('p', safeText(card.owner_request, 'لا يوجد نص لطلب المالك.')));
    root.append(lead);
    const ownerCommand = data.owner_command;
    if (ownerCommand) {
      root.append(section('أمر المالك المرتبط', [ownerCommand], item =>
        detailItem(`${item.display_title || item.title} · ${item.card_id}`, item.owner_request, item.created_at), 'لا يوجد أمر مرتبط.'));
    }
    appendFacts(root, card, data.deliveries || []);
    const children = (currentBoard?.cards || []).filter(item => item.parent_card_id === card.card_id);
    if (children.length) {
      root.append(section('بطاقات الجلسات المسندة', children, item => {
        const progress = Number(item.criteria_total) > 0
          ? ` · ${item.criteria_passed === null || item.criteria_passed === undefined ? arabicNumber.format(item.criteria_total) : `${arabicNumber.format(item.criteria_passed)}/${arabicNumber.format(item.criteria_total)}`} معيار`
          : '';
        return detailItem(`${safeText(item.assigned_actor_name, 'جلسة غير محددة')} · ${safeText(item.title)}`, `${statusLabel(item)}${progress}`, item.updated_at);
      }, 'لا توجد بطاقات فرعية.'));
    }
    const criteria = (data.criteria || []).slice().sort((a, b) => (Number(a.sort_order) || 0) - (Number(b.sort_order) || 0));
    root.append(section('معايير الإنجاز', criteria, item => detailItem(`${criterionLabels[item.criterion_code] || item.title}${item.required ? ' · مطلوب' : ''}`, [item.description, checkMethodLabels[item.check_method] || (item.check_method ? 'فحص مسجل' : '')].filter(Boolean).join(' · ')), 'لا توجد معايير مسجلة.'));
    const events = (data.events || []).slice().sort((a, b) => Date.parse(a.recorded_at || '') - Date.parse(b.recorded_at || ''));
    root.append(section('الخط الزمني', events, item => detailItem(`${eventLabels[item.event_type] || 'حدث'}${item.actor_name ? ` · ${item.actor_name}` : ''}`, item.localized_details || item.details, item.recorded_at), 'لا توجد أحداث مسجلة.'));
    root.append(section('سجل الإسناد', data.assignments, item => detailItem(`${item.assigned_actor_name || 'جلسة سابقة'}${item.reason_code ? ` · ${item.reason_label || 'سبب مسجل'}` : ''}`, item.assigned_by_actor_name ? `أُسندت بواسطة ${item.assigned_by_actor_name}` : '', item.assigned_at), 'لا يوجد سجل إسناد.'));
    root.append(section('العوائق', data.issues, item => detailItem(`${issueLabels[item.cause_code] || 'عائق مسجل'}${item.cause_resolution ? ` · ${outcomeLabels[item.cause_resolution] || 'حالة مسجلة'}` : ''}`, item.localized_impact_summary || item.impact_summary, item.observed_at), 'لا توجد عوائق مسجلة.'));
    root.append(section('Git والتسليمات', data.deliveries, item => {
      const verified = Boolean(item.verified_at && item.remote_commit_sha && item.remote_commit_sha.toLowerCase() === String(item.commit_sha || '').toLowerCase());
      const proof = verified
        ? `تم التحقق من تطابق Commit مع origin في ${formatDate(item.verified_at)} · Remote SHA ${item.remote_commit_sha}`
        : item.outcome === 'failed'
          ? `لم يثبت تطابق Commit على origin${item.remote_commit_sha ? ` · Remote SHA ${item.remote_commit_sha}` : ''}`
          : 'لم يثبت الدفع على origin بعد.';
      const detail = [item.commit_sha && `Commit ${item.commit_sha}`, item.summary, (item.changed_paths || []).join('، '), proof].filter(Boolean).join(' · ');
      return detailItem(`${item.branch_name || 'فرع غير محدد'} · المحاولة ${arabicNumber.format(item.attempt_number || item.attempt_id || 0)}`, detail, item.submitted_at);
    }, 'لا توجد تسليمات مسجلة.'));
    root.append(section('فحوص الجودة', data.validations, item => detailItem(`${criterionLabels[item.criterion || item.check_code] || 'فحص مسجل'} · ${outcomeLabels[item.outcome] || 'نتيجة غير محددة'}`, item.evidence_ref, item.recorded_at), 'لا توجد نتائج تحقق مسجلة.'));
    root.append(section('طابور إرسال التكليفات', data.outbox, outboxItem, 'لا توجد تكليفات في طابور الإرسال.'));
    $('workflow-detail-loading').hidden = true;
    $('workflow-detail-error').hidden = true;
    root.hidden = false;
  }

  async function openCard(cardId) {
    currentCardId = cardId;
    $('workflow-detail-title').textContent = `${cardId} · تحميل التفاصيل…`;
    $('workflow-detail-content').hidden = true;
    $('workflow-detail-error').hidden = true;
    $('workflow-detail-loading').hidden = false;
    $('workflow-detail-dialog').showModal();
    await loadCardDetails();
  }

  async function loadCardDetails() {
    const cardId = currentCardId;
    try {
      const data = await requestJSON(`/api/workflow/cards/${encodeURIComponent(cardId)}`);
      if (cardId === currentCardId) renderCardDetails(data);
    } catch (error) {
      if (cardId !== currentCardId) return;
      $('workflow-detail-loading').hidden = true;
      $('workflow-detail-content').hidden = true;
      $('workflow-detail-error').hidden = false;
      $('workflow-detail-error').querySelector('p').textContent = error.message || 'تعذر تحميل تفاصيل هذه البطاقة.';
    }
  }

  function openCommandDialog() {
    $('workflow-command-error').hidden = true;
    $('workflow-command-dialog').showModal();
    $('command-owner-request').focus();
  }

  async function submitCommand(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const submit = $('workflow-command-submit');
    const errorBox = $('workflow-command-error');
    submit.disabled = true;
    submit.textContent = 'جارٍ الإنشاء والتوجيه…';
    errorBox.hidden = true;
    const commandPayload = {
      owner_request: $('command-owner-request').value.trim(),
    };
    const signature = JSON.stringify(commandPayload);
    if (!commandIdempotencyKey || commandPayloadSignature !== signature) {
      commandIdempotencyKey = globalThis.crypto?.randomUUID?.() || `owner-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      commandPayloadSignature = signature;
    }
    const payload = { ...commandPayload, idempotency_key: commandIdempotencyKey };
    try {
      const result = await requestJSON('/api/workflow/commands', { method: 'POST', body: JSON.stringify(payload) });
      commandIdempotencyKey = null;
      commandPayloadSignature = null;
      $('workflow-command-dialog').close();
      form.reset();
      $('workflow-query').value = '';
      $('workflow-status').value = '';
      $('workflow-actor').value = '';
      await loadBoard();
      const cardId = result.root_card_id || result.card_id;
      if (cardId) openCard(cardId);
      const targetNames = (currentBoard?.cards || [])
        .filter(card => (result.child_card_ids || result.session_card_ids || []).includes(card.card_id))
        .map(card => card.assigned_actor_name).filter(Boolean);
      const routed = targetNames.length ? ` إلى ${targetNames.join('، ')}` : '';
      $('workflow-connection').querySelector('span').textContent = result.created === false
        ? 'تم استرجاع الأمر المسجل سابقًا بأمان.'
        : `أُنشئ الأمر ${cardId || ''} وُجّه${routed}.`;
    } catch (error) {
      errorBox.textContent = error.message || 'تعذر إنشاء الأمر. لم تتغير اللوحة.';
      errorBox.hidden = false;
      errorBox.focus();
    } finally {
      submit.disabled = false;
      submit.textContent = 'إنشاء وتوجيه';
    }
  }

  $('workflow-refresh').addEventListener('click', () => loadBoard());
  $('workflow-retry').addEventListener('click', () => loadBoard());
  $('workflow-filters').addEventListener('submit', event => { event.preventDefault(); loadBoard(); });
  $('workflow-status').addEventListener('change', () => loadBoard());
  $('workflow-actor').addEventListener('change', () => loadBoard());
  $('workflow-query').addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => loadBoard({ showLoading: false }), 250);
  });
  $('workflow-clear').addEventListener('click', () => {
    $('workflow-query').value = '';
    $('workflow-status').value = '';
    $('workflow-actor').value = '';
    loadBoard();
  });
  $('workflow-command-open').addEventListener('click', openCommandDialog);
  document.querySelectorAll('[data-open-command]').forEach(button => button.addEventListener('click', openCommandDialog));
  $('workflow-command-form').addEventListener('submit', submitCommand);
  $('workflow-command-close').addEventListener('click', () => $('workflow-command-dialog').close());
  $('workflow-command-cancel').addEventListener('click', () => $('workflow-command-dialog').close());
  $('workflow-detail-close').addEventListener('click', () => $('workflow-detail-dialog').close());
  $('workflow-detail-retry').addEventListener('click', loadCardDetails);
  $('workflow-command-dialog').addEventListener('click', event => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
  $('workflow-detail-dialog').addEventListener('click', event => {
    if (event.target === event.currentTarget) event.currentTarget.close();
  });
  $('workflow-command-form').addEventListener('reset', () => { $('workflow-command-error').hidden = true; });
  $('workflow-command-form').addEventListener('keydown', event => {
    if (event.key === 'Escape') $('workflow-command-dialog').close();
  });
  $('workflow-detail-dialog').addEventListener('close', () => { currentCardId = null; });

  loadBoard();

  window.setInterval(() => {
    loadBoard({ showLoading: false });
  }, 60000);
})();
