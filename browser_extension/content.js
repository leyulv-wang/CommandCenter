(() => {
  const MESSAGE_TYPES = { START_CAPTURE: 'CC_START_CAPTURE', STOP_CAPTURE: 'CC_STOP_CAPTURE', UI_EVENT: 'CC_UI_EVENT' };
  const MAX_MUTATION_RECORDS = 50;
  const MAX_MUTATION_NODES = 100;
  const MAX_EVENTS_PER_WINDOW = 30;
  const EVENT_WINDOW_MS = 1000;
  let capturing = false;
  let observer = null;
  let pendingTimer = null;
  let activeSession = null;
  let eventWindowStartedAt = 0;
  let eventsInWindow = 0;
  let droppedEvents = 0;
  let startingValues = new WeakMap();
  let latestValues = new WeakMap();

  const text = (value) => typeof value === 'string' ? value.trim().slice(0, 500) : null;
  const visible = (element) => element instanceof Element && !element.hidden && getComputedStyle(element).display !== 'none' && getComputedStyle(element).visibility !== 'hidden';
  function sensitive(element) { return element instanceof HTMLInputElement && (element.type === 'password' || element.type === 'file'); }
  function isTrustedExtensionMessage(sender) { return sender.id === chrome.runtime.id && sender.url?.startsWith(chrome.runtime.getURL('')); }

  function associatedLabel(element) {
    if (element.labels?.length) return text([...element.labels].map((label) => label.innerText).join(' '));
    const labelledBy = element.getAttribute('aria-labelledby');
    return labelledBy ? text(labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' ')) : null;
  }

  function describeControl(element) {
    const row = element.closest('tr,[role="row"]');
    const cell = element.closest('td,th,[role="gridcell"],[role="columnheader"]');
    const dialog = element.closest('dialog,[role="dialog"]');
    const section = element.closest('section,[role="region"],fieldset');
    return {
      tag: element.tagName.toLowerCase(), type: element.getAttribute('type'), role: element.getAttribute('role'),
      name: element.getAttribute('name') || element.getAttribute('aria-label'), label: associatedLabel(element),
      placeholder: element.getAttribute('placeholder'), column: text(cell?.getAttribute('aria-colindex') || cell?.cellIndex?.toString()),
      row: text(row?.getAttribute('data-row-id') || row?.getAttribute('aria-rowindex') || row?.rowIndex?.toString()),
      dialog: text(dialog?.getAttribute('aria-label') || dialog?.querySelector('h1,h2,[role="heading"]')?.innerText),
      section: text(section?.getAttribute('aria-label') || section?.querySelector('legend,h1,h2,h3,[role="heading"]')?.innerText),
    };
  }

  function eventFor(actionType, element, valueBefore = null, valueAfter = null) {
    const control = describeControl(element);
    const isSensitive = control.type === 'password' || control.type === 'file';
    return { actionType, control, valueBefore: isSensitive ? null : text(valueBefore), valueAfter: isSensitive ? null : text(valueAfter), timestamp: Date.now() };
  }

  function send(event) {
    const now = Date.now();
    if (now - eventWindowStartedAt >= EVENT_WINDOW_MS) { eventWindowStartedAt = now; eventsInWindow = 0; }
    if (!capturing || !activeSession || eventsInWindow >= MAX_EVENTS_PER_WINDOW) { droppedEvents++; return; }
    eventsInWindow++;
    chrome.runtime.sendMessage({ type: MESSAGE_TYPES.UI_EVENT, sessionId: activeSession.id, event });
  }

  function controlTarget(target) { return target instanceof Element ? target.closest('input,textarea,select,button,[role="button"],[contenteditable="true"]') : null; }
  function flushInput(element) {
    if (!capturing || sensitive(element)) return;
    const after = latestValues.get(element); const before = startingValues.get(element) ?? null;
    if (after !== before) send(eventFor('input', element, before, after));
    startingValues.delete(element); latestValues.delete(element);
  }

  function recordInput(event) {
    const element = controlTarget(event.target);
    if (!element || sensitive(element)) return;
    if (!startingValues.has(element)) startingValues.set(element, element.value ?? element.textContent ?? '');
    latestValues.set(element, element.value ?? element.textContent ?? '');
    clearTimeout(pendingTimer); pendingTimer = setTimeout(() => flushInput(element), 450);
  }

  function recordClick(event) { const element = controlTarget(event.target); if (element && !sensitive(element)) send(eventFor('click', element)); }
  function recordSubmit(event) { const form = event.target instanceof Element ? event.target : null; if (form) send(eventFor('submit', form)); }
  function fingerprint(row) { return text(row.getAttribute('data-row-id') || row.getAttribute('aria-rowindex') || row.id || row.innerText); }

  function observeMutations(records) {
    let examinedNodes = 0;
    for (const record of records.slice(0, MAX_MUTATION_RECORDS)) {
      if (record.type === 'attributes') {
        const element = record.target;
        if (element.matches('dialog,[role="dialog"]') && record.attributeName === 'open') send(eventFor(element.hasAttribute('open') ? 'dialog-open' : 'dialog-close', element));
        if (record.attributeName === 'aria-selected') send(eventFor('selection-change', element));
        continue;
      }
      for (const node of record.addedNodes) {
        if (++examinedNodes > MAX_MUTATION_NODES) { droppedEvents++; return; }
        if (!(node instanceof Element) || !visible(node)) continue;
        if (node.matches('[role="alert"],[role="status"],.toast,.alert')) send(eventFor('notice', node, null, node.innerText));
        if (node.matches('dialog[open],[role="dialog"]')) send(eventFor('dialog-open', node));
        if (node.matches('tr,[role="row"]')) send({ actionType: 'row-change', control: { tag: node.tagName.toLowerCase(), row: fingerprint(node) }, valueBefore: null, valueAfter: null, timestamp: Date.now() });
      }
    }
    if (records.length > MAX_MUTATION_RECORDS) droppedEvents += records.length - MAX_MUTATION_RECORDS;
  }

  function start(session) {
    if (capturing || !session || session.origin !== location.origin) return;
    capturing = true; activeSession = session;
    document.addEventListener('click', recordClick, true); document.addEventListener('input', recordInput, true);
    document.addEventListener('change', recordInput, true); document.addEventListener('submit', recordSubmit, true);
    observer = new MutationObserver(observeMutations);
    observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['open', 'aria-selected'] });
  }

  function stop(sessionId) {
    if (sessionId && sessionId !== activeSession?.id) return;
    capturing = false; activeSession = null; clearTimeout(pendingTimer); observer?.disconnect(); observer = null;
    document.removeEventListener('click', recordClick, true); document.removeEventListener('input', recordInput, true);
    document.removeEventListener('change', recordInput, true); document.removeEventListener('submit', recordSubmit, true);
    startingValues = new WeakMap(); latestValues = new WeakMap();
  }

  chrome.runtime.onMessage.addListener((message, sender) => {
    if (!isTrustedExtensionMessage(sender)) return;
    if (message?.type === MESSAGE_TYPES.START_CAPTURE) start(message.session);
    if (message?.type === MESSAGE_TYPES.STOP_CAPTURE) stop(message.sessionId);
  });
})();
