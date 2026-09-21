/* Shared DOM perception and demonstration capture. No coordinates or CSS paths are stored. */
(() => {
  if (window.SkillCUA) return;
  const clean = (text) => (text || '').replace(/\s+/g, ' ').trim().slice(0, 300);
  const sensitive = (element) =>
    element.matches('input[type="password"],input[type="hidden"]') ||
    /password|密码|secret|token|api.?key|credit.?card|验证码|one.?time|cc-/i.test(
      [element.name, element.id, element.autocomplete, element.getAttribute('aria-label')].join(
        ' ',
      ),
    );
  function describe(element) {
    let role = element.getAttribute('role');
    if (!role) {
      if (element.matches('button,input[type="submit"],input[type="button"]')) role = 'button';
      else if (element.matches('a[href]')) role = 'link';
      else if (element.matches('select')) role = 'combobox';
      else if (element.matches('input[type="checkbox"]')) role = 'checkbox';
      else if (element.matches('input[type="radio"]')) role = 'radio';
      else if (element.matches('input,textarea,[contenteditable="true"]')) role = 'textbox';
    }
    if (
      !['button', 'link', 'textbox', 'combobox', 'checkbox', 'radio', 'tab'].includes(role) ||
      sensitive(element)
    )
      return null;
    const labelled = (element.getAttribute('aria-labelledby') || '')
      .split(' ')
      .map((id) => document.getElementById(id)?.textContent || '')
      .join(' ');
    const labels = element.labels
      ? Array.from(element.labels)
          .map((label) => {
            const copy = label.cloneNode(true);
            copy
              .querySelectorAll('input,textarea,select,button,[contenteditable]')
              .forEach((child) => child.remove());
            return copy.textContent;
          })
          .join(' ')
      : '';
    const name = clean(
      labelled ||
        element.getAttribute('aria-label') ||
        labels ||
        (['textbox', 'combobox'].includes(role) ? '' : element.textContent) ||
        element.getAttribute('title') ||
        element.getAttribute('placeholder') ||
        (role === 'button' ? element.value : ''),
    );
    if (!name || /password|密码|secret|token|api.?key|credit.?card|验证码/i.test(name)) return null;
    return { role, name };
  }
  const selector =
    'button,a[href],input,textarea,select,[contenteditable="true"],[role="button"],[role="link"],[role="tab"],[role="textbox"],[role="combobox"],[role="checkbox"],[role="radio"]';
  function snapshot() {
    return {
      url: location.href,
      title: document.title,
      timestamp: new Date().toISOString(),
      elements: Array.from(document.querySelectorAll(selector))
        .flatMap((element) => {
          const info = describe(element);
          return info &&
            element.getClientRects().length &&
            getComputedStyle(element).visibility !== 'hidden'
            ? [
                {
                  ...info,
                  disabled: Boolean(
                    element.disabled || element.getAttribute('aria-disabled') === 'true',
                  ),
                },
              ]
            : [];
        })
        .slice(0, 200),
    };
  }
  function emit(action) {
    const event = { ...action, url: location.href, timestamp: Date.now() };
    if (typeof window.__skillcua_emit === 'function') window.__skillcua_emit(event).catch(() => {});
    else if (window.parent !== window)
      window.parent.postMessage({ source: 'skillcua-recorder', action: event }, location.origin);
  }
  function capture(event) {
    const element = event.target instanceof Element ? event.target.closest(selector) : null;
    if (!element) return;
    const target = describe(element);
    if (!target) return;
    if (event.type === 'click' && ['button', 'link', 'tab'].includes(target.role))
      emit({ kind: 'click', target });
    if (event.type === 'input' && target.role === 'textbox')
      emit({
        kind: 'fill',
        target,
        value: element.isContentEditable ? element.textContent : element.value,
      });
    if (event.type === 'change' && target.role === 'combobox')
      emit({ kind: 'select', target, value: element.value });
    if (event.type === 'change' && ['checkbox', 'radio'].includes(target.role))
      emit({ kind: 'check', target, checked: element.checked });
  }
  window.SkillCUA = { describe, snapshot };
  if (window.__skillcua_recording || new URL(location.href).searchParams.has('record')) {
    document.addEventListener('click', capture, true);
    document.addEventListener('input', capture, true);
    document.addEventListener('change', capture, true);
  }
})();
