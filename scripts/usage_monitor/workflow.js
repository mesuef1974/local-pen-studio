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
    git_integration_state: 'تقدم الدمج الآلي', git_integration_completed: 'اكتمال الدمج ومزامنة main',
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
  let criteriaCatalog = null;

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

  function fillCommandSessions(sessions) {
    const select = $('command-target-actor');
    const selected = select.value;
    const available = sessions.filter(session => isSessionActor(session) && Number(session.dispatchable) === 1);
    select.replaceChildren(new Option(available.length ? 'اختر الجلسة' : 'لا توجد جلسات جاهزة للاستلام', ''));
    for (const session of available) {
      select.add(new Option(safeText(session.display_name, session.actor_id), session.actor_id));
    }
    if (available.some(session => session.actor_id === selected)) select.value = selected;
    updateCommandPreview();
  }

  const criterionCategories = {
    quality: 'الجودة والتحقق', delivery: 'التسليم والنطاق', research: 'المصادر والمحتوى',
    interface: 'الواجهة وإمكانية الوصول', general: 'معايير عامة',
  };
  const criterionMethods = {
    automated_quality_gate: 'بوابة جودة آلية', automated_tests: 'اختبارات آلية', scope_match: 'مراجعة نطاق التسليم',
    manual_evidence: 'دليل يرفقه المنفذ', source_review: 'مراجعة المصادر', accessibility_review: 'مراجعة RTL وإمكانية الوصول',
  };

  function renderCriterionCatalog(items) {
    const root = $('command-criteria-list');
    root.replaceChildren();
    const groups = new Map();
    for (const item of items) {
      if (!groups.has(item.category_code)) groups.set(item.category_code, []);
      groups.get(item.category_code).push(item);
    }
    for (const [category, categoryItems] of groups) {
      root.append(element('h4', criterionCategories[category] || category, 'workflow-criterion-category'));
      for (const item of categoryItems) {
        const card = element('article', undefined, 'workflow-criterion-card');
        card.dataset.criterionCode = item.criterion_code;
        const include = document.createElement('input');
        include.type = 'checkbox'; include.checked = Boolean(item.default_required); include.dataset.role = 'include';
        const title = element('span', item.title);
        const main = element('label', undefined, 'workflow-criterion-main');
        const includeId = `criterion-${item.criterion_code}`; include.id = includeId; main.htmlFor = includeId;
        main.append(include, title);
        card.append(main, element('p', item.description),
          element('p', `طريقة التحقق: ${criterionMethods[item.check_method] || item.check_method}`));
        const required = document.createElement('input');
        required.type = 'checkbox'; required.checked = Boolean(item.default_required); required.disabled = !include.checked; required.dataset.role = 'required';
        const requiredLabel = element('label', undefined, 'workflow-criterion-required');
        requiredLabel.append(required, document.createTextNode('يُطلب اجتيازه لإكمال البطاقة'));
        card.append(requiredLabel);
        include.addEventListener('change', () => { required.disabled = !include.checked; updateCommandPreview(); });
        required.addEventListener('change', updateCommandPreview);
        root.append(card);
      }
    }
    $('command-criteria-status').textContent = items.length
      ? 'اختر ما ينطبق على المهمة. المعايير الافتراضية المطلوبة محددة مسبقًا؛ ويمكنك تعديل الإلزام لكل معيار.'
      : 'لا توجد معايير نشطة في قاعدة البيانات؛ أضف معيارًا يدويًا أو راجع كتالوج الإدارة.';
    updateCommandPreview();
  }

  function selectedCriteria() {
    const templates = [...$('command-criteria-list').querySelectorAll('.workflow-criterion-card')]
      .filter(card => card.querySelector('[data-role="include"]').checked)
      .map(card => ({criterion_code: card.dataset.criterionCode,
        required: card.querySelector('[data-role="required"]').checked}));
    const custom = [...$('command-custom-criteria').querySelectorAll('.workflow-custom-row')]
      .map(row => ({title: row.querySelector('[data-role="title"]').value.trim(),
        description: row.querySelector('[data-role="description"]').value.trim(),
        check_method: row.querySelector('[data-role="method"]').value,
        required: row.querySelector('[data-role="required"]').checked}))
      .filter(item => item.title);
    return [...templates, ...custom];
  }

  function updateCommandPreview() {
    const selectedId = $('command-target-actor')?.value;
    const session = (currentBoard?.sessions || []).find(item => item.actor_id === selectedId);
    const sessionPanel = $('command-session-duties');
    if (session) {
      sessionPanel.replaceChildren(element('strong', `${session.display_name} · اختصاصها المسجل`),
        element('p', `النطاق: ${session.assignment_scope}`),
        element('p', `مسؤوليتها: ${session.flow_responsibility}`),
        element('p', `المخرجات: ${session.required_outputs}`));
      sessionPanel.hidden = false;
      $('command-preview-session').textContent = `الإسناد: ${session.display_name} — وفق الاختصاص والمسؤولية الظاهرة أعلاه.`;
    } else {
      sessionPanel.replaceChildren(); sessionPanel.hidden = true;
      $('command-preview-session').textContent = 'اختر الجلسة لعرض اختصاصها.';
    }
    const items = selectedCriteria();
    const requiredCount = items.filter(item => item.required).length;
    const titles = [...$('command-criteria-list').querySelectorAll('.workflow-criterion-card')]
      .filter(card => card.querySelector('[data-role="include"]').checked)
      .map(card => card.querySelector('.workflow-criterion-main span').textContent)
      .concat([...$('command-custom-criteria').querySelectorAll('[data-role="title"]')]
        .map(input => input.value.trim()).filter(Boolean));
    $('command-preview-criteria').textContent = items.length
      ? `المعايير المختارة (${items.length}، إلزامي ${requiredCount}): ${titles.join('، ')}`
      : 'لم تُحدد معايير؛ سيضيف النظام معيار التحقق الآلي الافتراضي.';
  }

  function addCustomCriterion(initial = null, suppressFocus = false) {
    const row = element('div', undefined, 'workflow-custom-row');
    const titleLabel = element('label', 'اسم المعيار', 'workflow-custom-title');
    const title = document.createElement('input'); title.type = 'text'; title.maxLength = 300; title.required = true;
    title.placeholder = 'مثال: توثيق كل مصدر خارجي'; title.dataset.role = 'title'; title.value = initial?.title || ''; titleLabel.append(title);
    const descriptionLabel = element('label', 'طريقة الفحص أو الدليل المطلوب');
    const description = document.createElement('textarea'); description.rows = 2; description.maxLength = 2000;
    description.placeholder = 'ما الدليل الذي يثبت اجتياز هذا المعيار؟'; description.dataset.role = 'description'; description.value = initial?.description || ''; descriptionLabel.append(description);
    const methodLabel = element('label', 'نوع التحقق');
    const method = document.createElement('select'); method.dataset.role = 'method';
    for (const [value, label] of [['manual_evidence','دليل يرفقه المنفذ'],['automated_quality_gate','فحص آلي'],['automated_tests','اختبارات آلية'],['github_checks','فحوص GitHub']]) method.add(new Option(label, value));
    if (initial?.check_method) method.value = initial.check_method;
    methodLabel.append(method);
    const requiredLabel = element('label', undefined, 'workflow-check');
    const required = document.createElement('input'); required.type = 'checkbox'; required.checked = initial?.required !== false; required.dataset.role = 'required';
    requiredLabel.append(required, document.createTextNode('مطلوب اجتيازه'));
    const remove = element('button', 'حذف المعيار', 'btn workflow-custom-remove'); remove.type = 'button';
    remove.addEventListener('click', () => { row.remove(); updateCommandPreview(); });
    for (const input of [title, description, method, required]) input.addEventListener('input', updateCommandPreview);
    row.append(titleLabel, descriptionLabel, methodLabel, requiredLabel, remove);
    $('command-custom-criteria').append(row);
    if (!suppressFocus) title.focus();
    updateCommandPreview();
  }

  function renderProposals(proposals, available = true) {
    const root = $('wf-proposal-list');
    const rows = Array.isArray(proposals) ? proposals : [];
    root.replaceChildren();
    if (!available) {
      $('wf-proposal-count').textContent = 'بانتظار التحديث';
      root.append(element('p', 'يتطلب هذا المسار تحديث مخطط قاعدة البيانات وجامع القياس قبل تفعيله. بقيت أوامر المالك المعتادة متاحة.', 'workflow-proposal-empty'));
      return;
    }
    $('wf-proposal-count').textContent = `${arabicNumber.format(rows.filter(row => row.status_code === 'pending_owner').length)} بانتظار المالك`;
    if (!rows.length) {
      root.append(element('p', 'لا توجد توصيات متابعة مسجلة.', 'workflow-proposal-empty'));
      return;
    }
    rows.forEach(proposal => {
      const card = element('article', undefined, 'workflow-proposal-card');
      card.dataset.proposalId = proposal.proposal_id;
      const heading = element('div', undefined, 'workflow-proposal-heading');
      heading.append(element('h4', safeText(proposal.title)), element('span', ({
        pending_owner: 'بانتظار قرار المالك', approved: 'معتمدة · لم تصدر', rejected: 'مرفوضة', issued: 'صدرت منها بطاقة',
      })[proposal.status_code] || proposal.status_code, `workflow-proposal-status is-${proposal.status_code}`));
      const meta = element('p', undefined, 'workflow-proposal-meta');
      meta.append(document.createTextNode(`من ${safeText(proposal.proposed_by_name)} · البطاقة الأصلية `));
      const sourceButton = element('button', safeText(proposal.source_card_id), 'workflow-proposal-source');
      sourceButton.type = 'button'; sourceButton.addEventListener('click', () => openCard(proposal.source_card_id));
      meta.append(sourceButton);
      if (proposal.suggested_assignee_name) meta.append(document.createTextNode(` · الجلسة المقترحة: ${proposal.suggested_assignee_name} (اقتراح فقط)`));
      card.append(heading, meta, element('p', safeText(proposal.rationale), 'workflow-proposal-rationale'));
      card.append(element('p', `رأي الجلسة: ${safeText(proposal.source_opinion)}`, 'workflow-proposal-opinion'));
      card.append(element('p', `التوصية: ${safeText(proposal.session_recommendation)}`, 'workflow-proposal-recommendation'));
      if (proposal.decision_notes) card.append(element('p', `ملاحظة المالك: ${proposal.decision_notes}`, 'workflow-proposal-owner-note'));
      const request = element('details', undefined, 'workflow-proposal-details');
      request.append(element('summary', 'تفاصيل المهمة والنطاق والمعايير'));
      request.append(element('p', safeText(proposal.owner_request)));
      request.append(element('p', `النطاق: ${safeText(proposal.scope)}`));
      if (proposal.criteria?.length) {
        const list = element('ul');
        proposal.criteria.forEach(item => list.append(element('li', `${item.title}${item.required ? ' · مطلوب' : ''}${item.description ? ` — ${item.description}` : ''}`)));
        request.append(list);
      }
      card.append(request);
      if (proposal.status_code === 'pending_owner') {
        const notes = document.createElement('textarea');
        notes.className = 'workflow-proposal-notes'; notes.rows = 2; notes.maxLength = 4000;
        notes.placeholder = 'ملاحظة قرار المالك (اختيارية)'; notes.setAttribute('aria-label', `ملاحظة قرار التوصية ${proposal.proposal_id}`);
        const actions = element('div', undefined, 'workflow-proposal-actions');
        const reject = element('button', 'رفض التوصية', 'btn'); reject.type = 'button'; reject.dataset.proposalDecision = 'reject';
        const approve = element('button', 'اعتماد التوصية', 'btn workflow-primary'); approve.type = 'button'; approve.dataset.proposalDecision = 'approve';
        actions.append(reject, approve);
        card.append(notes, actions);
      } else if (proposal.status_code === 'approved') {
        const issue = element('button', 'تجهيز أمر المالك وإصدار البطاقة', 'btn workflow-primary');
        issue.type = 'button'; issue.dataset.prepareProposal = proposal.proposal_id;
        card.append(issue);
      } else if (proposal.status_code === 'issued' && proposal.issued_root_card_id) {
        const issued = element('button', `فتح أمر المالك ${proposal.issued_root_card_id}`, 'btn');
        issued.type = 'button'; issued.addEventListener('click', () => openCard(proposal.issued_root_card_id));
        card.append(issued);
      }
      root.append(card);
    });
  }

  async function decideProposal(button) {
    const card = button.closest('[data-proposal-id]');
    const note = card.querySelector('.workflow-proposal-notes')?.value.trim() || '';
    const decision = button.dataset.proposalDecision;
    const actions = card.querySelectorAll('[data-proposal-decision]');
    actions.forEach(item => { item.disabled = true; });
    try {
      await requestJSON(`/api/workflow/proposals/${encodeURIComponent(card.dataset.proposalId)}/decision`, {
        method: 'POST', body: JSON.stringify({ actor_id: 'owner', decision, notes: note }),
      });
      await loadBoard({ showLoading: false });
    } catch (error) {
      const feedback = element('p', error.message || 'تعذر حفظ قرار المالك.', 'workflow-proposal-error');
      card.append(feedback);
      actions.forEach(item => { item.disabled = false; });
    }
  }

  function prepareProposal(proposal) {
    openCommandDialog(proposal);
  }

  async function ensureCriterionCatalog() {
    if (criteriaCatalog) return;
    $('command-criteria-status').textContent = 'جارٍ تحميل المعايير من قاعدة البيانات…';
    try {
      const data = await requestJSON('/api/workflow/criteria');
      criteriaCatalog = Array.isArray(data.criteria) ? data.criteria : [];
      renderCriterionCatalog(criteriaCatalog);
    } catch (error) {
      $('command-criteria-status').textContent = error.message || 'تعذر تحميل المعايير من قاعدة البيانات.';
      throw error;
    }
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
    fillCommandSessions(sessions);
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
    renderProposals(board.card_proposals, board.proposal_workflow_available !== false);
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
    const integrationLabels = {
      pending: 'بانتظار المعالجة', processing: 'قيد المعالجة', awaiting_checks: 'بانتظار فحوص GitHub',
      awaiting_review: 'بانتظار مراجعة GitHub', merged_sync_pending: 'دُمجت؛ بانتظار مزامنة main',
      completed: 'اكتمل الدمج ومزامنة main', returned: 'أُعيدت للتنفيذ', blocked: 'متوقفة عند عائق',
    };
    root.append(section('الدمج ومزامنة main', data.git_integrations, item => {
      const detail = [
        item.pull_request_url && `PR ${item.pull_request_number}: ${item.pull_request_url}`,
        item.head_branch && `الفرع ${item.head_branch}`,
        item.head_sha && `Commit ${item.head_sha}`,
        item.merge_sha && `Merge ${item.merge_sha}`,
        item.local_main_sha && `main المحلي ${item.local_main_sha}`,
        item.remote_main_sha && `origin/main ${item.remote_main_sha}`,
        item.last_error_code && `رمز العائق ${item.last_error_code}`,
      ].filter(Boolean).join(' · ');
      return detailItem(integrationLabels[item.state_code] || safeText(item.state_code), detail, item.updated_at || item.created_at);
    }, 'لا يوجد تكامل Git بانتظار التنفيذ.'));
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

  async function openCommandDialog(proposal = null) {
    $('workflow-command-error').hidden = true;
    $('workflow-command-dialog').showModal();
    if (proposal) {
      $('command-title').value = proposal.title;
      $('command-owner-request').value = proposal.owner_request;
      $('command-scope').value = proposal.scope;
      $('command-proposal-id').value = proposal.proposal_id;
      $('command-target-actor').value = '';
      $('command-custom-criteria').replaceChildren();
      (proposal.criteria || []).forEach(item => addCustomCriterion(item, true));
      $('workflow-command-title').textContent = 'مراجعة التوصية وإصدار أمر المالك';
      $('command-proposal-context').textContent = proposal.suggested_assignee_name
        ? `الجلسة المقترحة من ${safeText(proposal.proposed_by_name)} هي ${proposal.suggested_assignee_name}؛ هذا اقتراح فقط، اختر بنفسك من القائمة.`
        : 'اختر بنفسك جلسة التنفيذ من القائمة؛ لم تقترح الجلسة المرسلة جهة تنفيذ.';
      $('command-proposal-context').hidden = false;
    } else {
      $('workflow-command-title').textContent = 'إضافة أمر إلى المصنع';
      $('workflow-command-form').reset();
      $('command-custom-criteria').replaceChildren();
      if (criteriaCatalog) renderCriterionCatalog(criteriaCatalog);
      $('command-proposal-id').value = '';
      $('command-proposal-context').hidden = true;
      $('command-target-actor').focus();
    }
    updateCommandPreview();
    try { await ensureCriterionCatalog(); }
    catch { /* the owner can still add a custom criterion while the catalog is unavailable */ }
  }

  async function submitCommand(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    try { await ensureCriterionCatalog(); }
    catch (error) { $('workflow-command-error').textContent = error.message; $('workflow-command-error').hidden = false; return; }
    const submit = $('workflow-command-submit');
    const errorBox = $('workflow-command-error');
    submit.disabled = true;
    submit.textContent = 'جارٍ إصدار الأمر وإسناده…';
    errorBox.hidden = true;
    const commandPayload = {
      title: $('command-title').value.trim(),
      owner_request: $('command-owner-request').value.trim(),
      scope: $('command-scope').value.trim(),
      proposal_id: $('command-proposal-id').value,
      target_actor_ids: [$('command-target-actor').value],
      criteria: selectedCriteria(),
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
      $('workflow-command-title').textContent = 'إضافة أمر إلى المصنع';
      $('command-proposal-context').hidden = true;
      $('command-custom-criteria').replaceChildren();
      renderCriterionCatalog(criteriaCatalog || []);
      updateCommandPreview();
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
      submit.textContent = 'إصدار الأمر وإسناده';
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
  $('workflow-command-open').addEventListener('click', () => openCommandDialog());
  document.querySelectorAll('[data-open-command]').forEach(button => button.addEventListener('click', () => openCommandDialog()));
  $('workflow-command-form').addEventListener('submit', submitCommand);
  $('wf-proposal-list').addEventListener('click', event => {
    const decision = event.target.closest('[data-proposal-decision]');
    if (decision) { decideProposal(decision); return; }
    const prepare = event.target.closest('[data-prepare-proposal]');
    if (prepare) {
      const proposal = (currentBoard?.card_proposals || []).find(item => item.proposal_id === prepare.dataset.prepareProposal);
      if (proposal) prepareProposal(proposal);
    }
  });
  $('command-criterion-add').addEventListener('click', addCustomCriterion);
  $('command-target-actor').addEventListener('change', updateCommandPreview);
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
