'use strict';
(() => {
  const make = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  const box = make('section', undefined, 'workplace-controls');
  const label = make('label', 'Working style');
  label.htmlFor = 'work-profile';
  const select = make('select');
  select.id = 'work-profile';
  [
    ['general', 'General assistant'],
    ['manager', 'Management'],
    ['developer', 'Development'],
    ['reception', 'Reception & admin'],
  ].forEach(([value, text]) => select.append(new Option(text, value)));
  const note = make('small', 'Changes guidance, not permissions. Saved on this computer.');
  const status = make('p');
  status.setAttribute('role', 'status');
  box.append(label, select, note, status);
  const anchor = document.querySelector('.aside-foot');
  if (anchor) anchor.before(box);
  let saving = false;
  async function save(body) {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Could not save setting');
    return d;
  }
  select.onchange = async () => {
    saving = true;
    select.disabled = true;
    try {
      await save({ work_profile: select.value });
      suggestions(select.value);
      status.textContent = 'Working style saved for future replies.';
    } catch (e) {
      status.textContent = e.message;
    } finally {
      saving = false;
      select.disabled = false;
    }
  };
  const panel = document.querySelector('.file-panel');
  if (!panel) return;
  const preview = make('section', undefined, 'progress-preview');
  preview.id = 'progress-preview';
  const heading = make('h2', 'Progress preview');
  const caption = make('p', 'A preview appears when the agent opens your local app.');
  const toggleLabel = make('label', undefined, 'preview-toggle');
  const toggle = make('input');
  toggle.type = 'checkbox';
  toggle.checked = true;
  toggleLabel.append(toggle, document.createTextNode('Capture local app progress'));
  const image = make('img');
  image.alt = 'Latest captured view of the application being built';
  image.hidden = true;
  const expand = make('button', 'Expand capture');
  expand.type = 'button';
  expand.className = 'preview-expand';
  expand.hidden = true;
  const dialog = make('dialog', undefined, 'preview-dialog');
  const close = make('button', 'Close preview');
  close.type = 'button';
  const large = make('img');
  large.alt = 'Expanded application progress capture';
  dialog.append(close, large);
  document.body.append(dialog);
  close.onclick = () => dialog.close();
  expand.onclick = () => {
    large.src = image.src;
    dialog.showModal();
  };
  const open = make('a', 'Open interactive app');
  open.target = '_blank';
  open.rel = 'noopener noreferrer';
  open.hidden = true;
  const hint = make(
    'small',
    'Captured browser view, not a live video or a passed test. The interactive app opens in a separate tab.',
  );
  preview.append(heading, toggleLabel, caption, image, expand, open, hint);
  panel.prepend(preview);
  const button = document.getElementById('panel-toggle');
  if (button) {
    button.textContent = 'Preview & files';
    button.addEventListener('click', () => {
      if (window.innerWidth <= 700)
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }
  const starters = {
    general: [
      [
        'Draft a reply',
        'Help me draft a clear professional reply. Ask me for the message and intended outcome.',
      ],
      [
        'Summarise a document',
        'Summarise the document I attach, keeping decisions and action items separate.',
      ],
      [
        'Research a question',
        'Help me research a question using sources. First ask what I need to know.',
      ],
      ['Plan my work', 'Help me prioritise my work. Ask what is on my list and any deadlines.'],
    ],
    manager: [
      [
        'Prepare a briefing',
        'Help me prepare a concise team briefing. Ask for the context and audience.',
      ],
      [
        'Compare options',
        'Help me compare options for a decision. Ask about the options and criteria.',
      ],
      [
        'Turn notes into actions',
        'Turn the notes I provide into actions, with owners and deadlines only where stated.',
      ],
      [
        'Draft an update',
        'Help me write a natural project update covering progress, blockers and next steps.',
      ],
    ],
    developer: [
      [
        'Build with a preview',
        'Help me build an application in the selected workspace. Ask what I want to build, then share an early browser preview and test the result.',
      ],
      [
        'Fix a problem',
        'Inspect the selected project, reproduce the problem I describe, fix it and run relevant tests.',
      ],
      [
        'Review code',
        'Review the selected project for concrete issues. Explain findings before changing files.',
      ],
      [
        'Explain a project',
        'Inspect the selected project and explain how it works in plain language.',
      ],
    ],
    reception: [
      [
        'Draft a response',
        'Help me draft a friendly professional response to an enquiry. Ask me for the enquiry and relevant policy.',
      ],
      [
        'Prepare a handover',
        'Turn the notes I provide into a clear reception handover, marking anything awaiting confirmation.',
      ],
      [
        'Organise requests',
        'Help me organise the requests I provide by urgency and required follow-up.',
      ],
      [
        'Prepare an appointment reply',
        'Draft an appointment response using the details I provide. Do not claim anything has been booked.',
      ],
    ],
  };
  let profile = '';
  function suggestions(value) {
    if (profile === value) return;
    profile = value;
    const holder = document.querySelector('.suggestions');
    if (!holder) return;
    holder.replaceChildren();
    (starters[value] || starters.general).forEach(([title, prompt]) => {
      const b = make('button');
      b.type = 'button';
      b.append(make('b', title), make('span', 'Start a conversation'));
      b.onclick = () => {
        const input = document.getElementById('prompt');
        if (input && !input.disabled) {
          input.value = prompt;
          input.focus();
        }
      };
      holder.append(b);
    });
  }
  toggle.onchange = async () => {
    toggle.disabled = true;
    try {
      await save({ progress_preview: toggle.checked });
      if (!toggle.checked) {
        image.hidden = true;
        expand.hidden = true;
        open.hidden = true;
        caption.textContent = 'Automatic progress previews are off.';
      }
    } catch (e) {
      caption.textContent = e.message;
      toggle.checked = !toggle.checked;
    } finally {
      toggle.disabled = false;
    }
  };
  window.addEventListener('workhorse:snapshot', (event) => {
    const d = event.detail;
    if (d.config) {
      if (!saving) select.value = d.config.work_profile || 'general';
      toggle.checked = d.config.progress_preview !== false;
      suggestions(d.config.work_profile || 'general');
    }
    const p = d.progress_preview;
    if (!p || !toggle.checked) {
      image.hidden = true;
      expand.hidden = true;
      open.hidden = true;
      caption.textContent = toggle.checked
        ? 'A preview appears when the agent opens your local app.'
        : 'Automatic progress previews are off.';
      return;
    }
    const source = '/api/screenshot?id=' + encodeURIComponent(p.screenshot);
    if (image.getAttribute('src') !== source) image.src = source;
    image.hidden = false;
    expand.hidden = false;
    caption.textContent =
      'Captured ' +
      new Date(p.captured).toLocaleTimeString() +
      ' · ' +
      (p.viewport.width || '?') +
      ' × ' +
      (p.viewport.height || '?') +
      ' · ' +
      (d.run ? 'Task in progress' : 'Last capture');
    try {
      const u = new URL(p.url);
      if (
        !['http:', 'https:'].includes(u.protocol) ||
        !['localhost', '127.0.0.1', '[::1]'].includes(u.hostname)
      )
        throw Error();
      open.href = u.href;
      open.hidden = false;
    } catch {
      open.hidden = true;
    }
  });
})();
