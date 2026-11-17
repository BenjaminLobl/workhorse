"""Workplace response profiles and passive, thread-scoped progress previews."""
import json
from urllib.parse import urlsplit
from server import now

PROFILES = {
    'general': 'General assistant: help with writing, analysis, research, planning and technical work as requested. Adapt to the user instead of assuming a job title.',
    'manager': 'Management support: make decisions easier with concise briefs, options, tradeoffs, action owners and dates when known. Do not invent metrics, commitments or company policy.',
    'developer': 'Development support: inspect the existing project, explain meaningful changes, use incremental edits, run relevant tests and share early browser previews for visual work.',
    'reception': 'Reception and administration: use warm, clear professional language. Help draft replies, organise requests and prepare handovers. Ask for missing booking/contact details; never claim an appointment, message or system update occurred without a connected tool and its successful result.',
}
CONVERSATION = '''
WORKPLACE CONVERSATION:
Respond naturally and directly. Match the user's requested level of detail and expertise.
For greetings, explanations, brainstorming and drafting, answer conversationally; do not force a coding plan or run tools unnecessarily.
For actionable tasks, use the tools actually available and provide brief progress at meaningful milestones. Avoid repetitive narration and raw tool JSON.
Ask a focused question when missing information changes the outcome; otherwise state a reasonable assumption and proceed.
Distinguish drafts, sample data, proposals, completed actions and verified results. Do not invent access to email, calendars, CRM or company policies.
A work profile changes response guidance only, never permissions. Respect saved preferences and the current request.
For visual application work, run a usable first version early, open it with browser_open and capture incremental progress rather than waiting until the end.
The progress preview is an observation, not evidence that tests or vision review passed. Continue desktop/mobile verification and report actual blockers.
'''

class Workplace:
    def workplace_init(self):
        self.write('CREATE TABLE IF NOT EXISTS progress_previews(thread TEXT PRIMARY KEY, detail TEXT NOT NULL)')

    def workplace_prompt(self):
        profile = self.settings().get('work_profile', 'general')
        return CONVERSATION + '\nPreferred work profile: ' + PROFILES.get(profile, PROFILES['general'])

    def progress_preview(self, thread):
        rows = self.rows('SELECT detail FROM progress_previews WHERE thread=?', (thread,))
        return json.loads(rows[0]['detail']) if rows else None

    def remember_preview(self, run, result):
        # Only local app observations appear in the development preview panel.
        try:
            url = urlsplit(result.get('url', ''))
            if url.scheme not in ('http', 'https') or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.username or url.password:
                return
            safe_url = url._replace(query='', fragment='').geturl()
        except ValueError:
            return
        if not result.get('screenshot'):
            return
        detail = {'screenshot': result['screenshot'], 'url': safe_url,
                  'viewport': result.get('viewport', {}), 'run': run.id,
                  'captured': now(), 'revision': getattr(run, 'revision', 0),
                  'label': 'Work in progress — not a test result'}
        self.write('INSERT OR REPLACE INTO progress_previews VALUES(?,?)', (run.thread, json.dumps(detail)))

    def capture_progress(self, run, action, args, result):
        if not self.settings().get('progress_preview', True):
            return result
        if result.get('screenshot'):
            self.remember_preview(run, result)
            return result
        if action not in ('browser_open', 'browser_reload', 'browser_resize', 'browser_click'):
            return result
        tab = result.get('tab') or args.get('tab')
        try:
            url = urlsplit(result.get('url', ''))
            if not tab or url.hostname not in ('127.0.0.1', 'localhost', '::1'):
                return result
            shot = self.browser.call(run.workspace, 'browser_screenshot', {'tab': tab}, run.online and self.workspace(run.workspace)['permissions']['internet'])
            self.write('INSERT INTO screenshots VALUES(?,?,?,?)', (shot['screenshot'], run.workspace, run.id, now()))
            self.write('INSERT INTO visual_evidence VALUES(?,?,?,?,?,0)', (shot['screenshot'], run.id, getattr(run, 'revision', 0), shot.get('viewport', {}).get('width', 0), shot.get('viewport', {}).get('height', 0)))
            self.remember_preview(run, shot)
            return dict(result, preview=shot['screenshot'])
        except Exception:
            # A failed progress capture must not turn a successful action into a retry.
            return dict(result, preview_warning='Progress capture unavailable. Use browser_screenshot to inspect the failure.')
