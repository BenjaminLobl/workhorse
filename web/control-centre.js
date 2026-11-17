/* Workhorse Control Centre. Uses the existing same-origin session and /api endpoints. */
(() => {
  'use strict';
  const byId = (id) => document.getElementById(id);
  const elem = (tag, text, className) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (className) n.className = className;
    return n;
  };
  const api = async (path, body) => {
    const r = await fetch('/api/' + path, {
      method: body ? 'POST' : 'GET',
      credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Unable to complete request');
    return d;
  };
  const dialog = elem('dialog', undefined, 'cc-dialog');
  dialog.id = 'control-centre-dialog';
  const header = elem('div', undefined, 'cc-head');
  const title = elem('div');
  title.append(
    elem('span', 'YOUR LOCAL CONTROL CENTRE', 'cc-eyebrow'),
    elem('h2', 'Workhorse Control Centre'),
  );
  const close = elem('button', '×', 'cc-close');
  close.type = 'button';
  close.setAttribute('aria-label', 'Close Control Centre');
  header.append(title, close);
  const tabs = elem('div', undefined, 'cc-tabs');
  const body = elem('div', undefined, 'cc-content');
  const status = elem('p', '', 'cc-status');
  status.setAttribute('role', 'status');
  dialog.append(header, tabs, body, status);
  document.body.append(dialog);
  const trigger = elem('button', 'Control Centre', 'subtle cc-launch');
  trigger.type = 'button';
  const aside = document.querySelector('aside');
  const settings = byId('settings');
  if (aside) aside.insertBefore(trigger, aside.querySelector('.aside-foot') || null);
  else document.body.append(trigger);
  let data = null,
    current = 'projects';
  const refreshCSS = () => {
    let l = byId('cc-theme-style');
    if (l) {
      l.remove();
    }
    l = document.createElement('link');
    l.rel = 'stylesheet';
    l.id = 'cc-theme-style';
    l.href = '/api/control-theme.css?t=' + Date.now();
    document.head.appendChild(l);
  };
  function call(action, params = {}) {
    return api('control-centre', { action, ...params })
      .then(async (result) => {
        data = await api('control-centre');
        render();
        return result;
      })
      .catch((err) => {
        status.textContent = err.message;
      });
  }
  const row = (label, sub) => {
    const r = elem('div', undefined, 'cc-row');
    const content = elem('div');
    content.append(elem('strong', label));
    if (sub) content.append(elem('small', sub));
    r.append(content);
    return r;
  };
  function preview(proposal) {
    stopPreview();
    const link = document.createElement('link');
    link.id = 'cc-preview-style';
    link.rel = 'stylesheet';
    link.href = '/api/control-theme-preview.css?id=' + encodeURIComponent(proposal.id);
    document.head.append(link);
  }
  function stopPreview() {
    byId('cc-preview-style')?.remove();
  }
  function render() {
    if (!data) return;
    status.textContent = '';
    tabs.replaceChildren();
    body.replaceChildren();
    [
      ['projects', 'Projects'],
      ['preferences', 'Preferences'],
      ['appearance', 'Appearance'],
      ['runtime', 'Environment'],
      ['lab', 'Appearance Lab'],
    ].forEach(([key, name]) => {
      const b = elem('button', name, 'cc-tab' + (current === key ? ' selected' : ''));
      b.type = 'button';
      b.onclick = () => {
        stopPreview();
        current = key;
        render();
      };
      tabs.append(b);
    });
    if (current === 'projects') {
      body.append(
        elem(
          'p',
          'Browse only the directories you have explicitly approved in Workhorse. Discovery scans folders three levels deep; it does not run project code.',
          'cc-muted',
        ),
      );
      if (!data.workspaces.length)
        body.append(
          elem(
            'p',
            'No approved workspaces. Use “Approve workspace” in the sidebar first.',
            'cc-empty',
          ),
        );
      const search = elem('input');
      search.placeholder = 'Search projects, frameworks and notes';
      search.setAttribute('aria-label', 'Search projects');
      body.append(search);
      search.oninput = () => {
        body
          .querySelectorAll('.cc-project')
          .forEach(
            (row) =>
              (row.hidden = !row.textContent
                .toLowerCase()
                .includes(search.value.toLowerCase())),
          );
      };
      data.workspaces.forEach((w) => {
        const item = row(w.name, w.path);
        const scan = elem('button', 'Scan projects', 'cc-secondary');
        scan.type = 'button';
        scan.onclick = () => call('scan_projects', { workspace_id: w.id });
        item.append(scan);
        body.append(item);
        const found = (data.projects || []).filter((x) => x.workspace === w.id);
        found.forEach((p) => {
          const pRow = row(p.name, p.stack + ' · ' + p.path);
          if (p.description) pRow.querySelector('div')?.append(elem('small', p.description));
          pRow.classList.add('cc-project');
          pRow
            .querySelector('div')
            .append(
              elem('small', p.status + ' · ' + (p.history || []).length + ' associated runs'),
              elem('small', p.note || ''),
            );
          const evidence = elem('details');
          evidence.append(
            elem('summary', 'Evidence and work history'),
            elem(
              'pre',
              JSON.stringify(
                { todos: p.todos, history: p.history, manifests: p.evidence },
                null,
                2,
              ),
            ),
          );
          pRow.querySelector('div').append(evidence);
          const note = elem('button', 'Edit note', 'cc-secondary');
          note.onclick = () => {
            const value = prompt('Project note (not a completion claim)', p.note || '');
            if (value !== null)
              call('project_note', { workspace: w.id, path: p.path, note: value });
          };
          pRow.append(note);
          body.append(pRow);
        });
        if (!found.length)
          body.append(elem('p', 'Not indexed yet. Click Scan projects.', 'cc-muted'));
      });
    }
    if (current === 'preferences') {
      body.append(
        elem(
          'p',
          'These instructions are stored in local SQLite and automatically included in future tasks. Save preferences such as tone, formatting or design style—never passwords.',
          'cc-muted',
        ),
      );
      [
        ...Object.entries(data.preferences).map(([key, value]) => ({
          key,
          value,
          workspace: '',
        })),
        ...(data.scoped_preferences || []),
      ].forEach(({ key, value, workspace }) => {
        const item = row(
          key +
            (workspace
              ? ' · ' + (data.workspaces.find((w) => w.id === workspace)?.name || 'Workspace')
              : ' · Global'),
          value,
        );
        const edit = elem('button', 'Edit', 'cc-secondary');
        edit.onclick = () => {
          const next = prompt('Update this instruction', value);
          if (next !== null) call('save_preference', { key, value: next, workspace });
        };
        item.append(edit);
        const del = elem('button', 'Remove', 'cc-secondary');
        del.onclick = () => {
          if (confirm('Remove saved preference “' + key + '”?'))
            call('delete_preference', { key, workspace });
        };
        item.append(del);
        body.append(item);
      });
      const form = elem('form', undefined, 'cc-form');
      const key = elem('input');
      key.placeholder = 'Preference key, e.g. reply_style';
      key.required = true;
      key.maxLength = 40;
      const val = elem('textarea');
      val.placeholder = 'e.g. Write concise, natural replies without emojis. Focus on results.';
      val.required = true;
      val.maxLength = 600;
      const scope = elem('select');
      scope.setAttribute('aria-label', 'Preference scope');
      scope.append(new Option('All conversations and models', ''));
      data.workspaces.forEach((w) => scope.append(new Option(w.name, w.id)));
      const btn = elem('button', 'Save preference', 'cc-primary');
      btn.type = 'submit';
      form.append(
        elem('label', 'Scope'),
        scope,
        elem('label', 'Preference name'),
        key,
        elem('label', 'Instruction for future tasks'),
        val,
        btn,
      );
      form.onsubmit = (e) => {
        e.preventDefault();
        call('save_preference', {
          key: key.value.trim(),
          value: val.value.trim(),
          workspace: scope.value,
        });
      };
      body.append(form);
    }
    if (current === 'appearance') {
      body.append(
        elem(
          'p',
          'Appearance changes are proposed by your agent or here, then explicitly reviewed before being applied. Theme tokens change; Workhorse source files do not.',
          'cc-muted',
        ),
      );
      body.append(
        elem(
          'div',
          'Current theme: ' +
            Object.entries(data.theme)
              .map(([k, v]) => k + ' ' + v)
              .join(' · '),
          'cc-current',
        ),
      );
      for (const p of data.theme_proposals.filter((x) => x.status === 'pending')) {
        const item = row(p.title, p.note || 'Appearance proposal');
        const tools = elem('div', undefined, 'cc-actions');
        const view = elem('button', 'Preview', 'cc-secondary');
        view.onclick = () => preview(p);
        const approve = elem('button', 'Apply', 'cc-primary');
        approve.onclick = async () => {
          if (!confirm('Apply theme “' + p.title + '”? You can roll back in this panel.'))
            return;
          await call('apply_theme', { proposal_id: p.id });
          stopPreview();
          refreshCSS();
        };
        const reject = elem('button', 'Reject', 'cc-secondary');
        reject.onclick = () => {
          stopPreview();
          call('reject_theme', { proposal_id: p.id });
        };
        tools.append(view, approve, reject);
        item.append(tools);
        body.append(item);
      }
      const restore = elem('button', 'Rollback previous appearance', 'cc-secondary');
      restore.onclick = async () => {
        if (confirm('Restore the previous saved theme?')) {
          await call('rollback_theme');
          stopPreview();
          refreshCSS();
        }
      };
      body.append(restore);
      const form = elem('form', undefined, 'cc-form');
      form.append(elem('h3', 'Propose an appearance change'));
      const name = elem('input');
      name.placeholder = 'e.g. Refined charcoal';
      name.required = true;
      name.maxLength = 80;
      form.append(elem('label', 'Theme name'), name);
      const inputs = {};
      for (const [k, v] of Object.entries(data.theme)) {
        const inp = elem('input');
        inp.type = k === 'radius' ? 'number' : 'color';
        inp.value = v;
        if (k === 'radius') {
          inp.min = 2;
          inp.max = 24;
        }
        inputs[k] = inp;
        form.append(elem('label', k), inp);
      }
      const note = elem('textarea');
      note.maxLength = 800;
      note.placeholder = 'Why should the interface use these colours and spacing?';
      form.append(elem('label', 'Design note'), note);
      const b = elem('button', 'Stage for approval', 'cc-primary');
      form.append(b);
      form.onsubmit = (e) => {
        e.preventDefault();
        const palette = Object.fromEntries(
          Object.entries(inputs).map(([k, v]) => [
            k,
            k === 'radius' ? Number(v.value) : v.value,
          ]),
        );
        call('propose_theme', { title: name.value, note: note.value, palette });
      };
      body.append(form);
    }
    if (current === 'runtime') {
      body.append(
        elem(
          'p',
          'These values are read from the local Workhorse configuration, not inferred by the language model.',
          'cc-muted',
        ),
      );
      const check = elem('button', 'Check local services and models', 'cc-secondary');
      const facts = elem('pre', JSON.stringify(data.runtime, null, 2));
      check.onclick = async () => {
        check.disabled = true;
        try {
          facts.textContent = JSON.stringify(await api('runtime-facts'), null, 2);
        } catch (e) {
          status.textContent = e.message;
        } finally {
          check.disabled = false;
        }
      };
      body.append(check, facts);
      Object.entries(data.models).forEach(([k, v]) => {
        body.append(row(k, String(v)));
      });
      Object.entries(data.capabilities).forEach(([k, v]) => {
        body.append(row(k, v ? 'Available' : 'Not available in this upgrade'));
      });
      body.append(
        elem(
          'p',
          'Appearance Lab supports reviewed CSS-only source proposals. Backend and JavaScript self-editing remain unavailable.',
          'cc-muted',
        ),
      );
    }
    if (current === 'lab') {
      body.append(
        elem(
          'p',
          'Experimental CSS-only source changes. Preview uses an isolated copy with fake data; your live conversations stay private. Backend and JavaScript changes are blocked.',
          'cc-muted',
        ),
      );
      const list = elem('div');
      body.append(list);
      const reload = async () => {
        try {
          const d = await api('appearance-lab');
          list.replaceChildren();
          for (const p of d.proposals) {
            const card = row(p.title, p.status + ' · ' + p.path);
            card.classList.add('cc-lab-card');
            const details = elem('details');
            details.append(
              elem('summary', 'Source diff and checks'),
              elem('pre', p.diff),
              elem('pre', (p.checks || []).join('\n')),
            );
            card.append(details);
            if (p.error) card.append(elem('p', p.error));
            for (const shot of p.screenshots) {
              const img = elem('img');
              img.src =
                '/api/appearance-shot?id=' +
                encodeURIComponent(p.id) +
                '&name=' +
                encodeURIComponent(shot);
              img.alt = p.title + ' ' + shot;
              card.append(img);
            }
            for (const action of p.status === 'applied'
              ? ['rollback']
              : ['staged', 'failed', 'ready'].includes(p.status)
                ? ['preview', ...(p.status === 'ready' ? ['apply'] : [])]
                : []) {
              const button = elem(
                'button',
                action === 'apply'
                  ? 'Approve and apply'
                  : action === 'preview'
                    ? 'Run preview checks'
                    : 'Rollback',
                'cc-secondary',
              );
              button.onclick = async () => {
                if (action !== 'preview' && !confirm(action + ' this CSS source change?'))
                  return;
                button.disabled = true;
                status.textContent = 'Running ' + action + '…';
                try {
                  await api('appearance-lab', { action, id: p.id });
                  if (action === 'apply' || action === 'rollback') {
                    const link = document.querySelector(
                      'link[href*="workhorse-appearance.css"]',
                    );
                    if (link) link.href = '/workhorse-appearance.css?t=' + Date.now();
                  }
                  await reload();
                  status.textContent = 'Finished ' + action + '.';
                } catch (e) {
                  status.textContent = e.message;
                } finally {
                  button.disabled = false;
                }
              };
              card.append(button);
            }
            list.append(card);
          }
        } catch (e) {
          status.textContent = e.message;
        }
      };
      reload();
      const form = elem('form', undefined, 'cc-form');
      const title = elem('input');
      title.placeholder = 'Proposal title';
      title.required = true;
      const css = elem('textarea');
      css.placeholder = 'body { background-color: #f6f7f4; }';
      css.required = true;
      const submit = elem('button', 'Stage CSS proposal', 'cc-primary');
      form.append(elem('label', 'Title'), title, elem('label', 'Restricted CSS'), css, submit);
      form.onsubmit = async (e) => {
        e.preventDefault();
        try {
          await api('appearance-lab', { action: 'stage', title: title.value, css: css.value });
          await reload();
        } catch (error) {
          status.textContent = error.message;
        }
      };
      body.append(form);
    }
  }
  async function open() {
    if (dialog.open) return;
    current = 'projects';
    try {
      data = await api('control-centre');
      render();
      dialog.showModal();
    } catch (e) {
      alert('Unable to open Control Centre: ' + e.message);
    }
  }
  trigger.onclick = open;
  close.onclick = () => dialog.close();
  dialog.addEventListener('close', stopPreview);
  refreshCSS();
})();
