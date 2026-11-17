"""Declarative tool catalogue. All arguments validated before dispatch."""

from jsonschema import Draft202012Validator


def string(maximum=4000):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def number(low, high):
    return {"type": "integer", "minimum": low, "maximum": high}


def choice(*values):
    return {"type": "string", "enum": list(values)}


class Registry:
    def __init__(self):
        self.tools = {}

    def add(self, name, description, properties, required=None, group="file"):
        schema = {
            "type": "object",
            "properties": properties,
            "required": required if required is not None else list(properties),
            "additionalProperties": False,
        }
        self.tools[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema,
            },
            "group": group,
        }

    def schemas(self, groups):
        return [
            {k: v for k, v in t.items() if k != "group"}
            for t in self.tools.values()
            if t["group"] in groups
        ]

    def validate(self, name, args, groups):
        t = self.tools.get(name)
        if not t or t["group"] not in groups:
            raise PermissionError(
                "Tool not available in this mode or workspace permissions."
            )
        errors = list(
            Draft202012Validator(t["function"]["parameters"]).iter_errors(args)
        )
        if errors:
            raise ValueError("Invalid arguments: " + errors[0].message[:250])


REGISTRY = Registry()
add = REGISTRY.add
add(
    "list_files",
    "List approved project directory entries. Protected folders are excluded.",
    {"path": string(500)},
    [],
    "file",
)
add(
    "read_file",
    "Read a section of a project file. Use sha256 to safely overwrite later.",
    {"path": string(500), "start": number(1, 100000), "lines": number(1, 300)},
    ["path"],
)
add(
    "search_files",
    "Search literal text in project files; returns paths and line numbers.",
    {"query": string(200)},
)
add(
    "write_file",
    "Create file, or overwrite after reading its sha256. Provide the reason.",
    {
        "path": string(500),
        "content": {"type": "string", "maxLength": 500000},
        "reason": string(500),
        "expected_hash": string(64),
    },
    ["path", "content", "reason"],
    "edit",
)
add(
    "edit_file",
    "Replace exactly one matching old_text; refuses ambiguous edits.",
    {
        "path": string(500),
        "old_text": string(100000),
        "new_text": {"type": "string", "maxLength": 100000},
        "reason": string(500),
    },
    group="edit",
)
add(
    "rename_file",
    "Rename one file to an unused project path.",
    {"path": string(500), "destination": string(500), "reason": string(500)},
    group="edit",
)
add(
    "delete_file",
    "Delete one file, requiring explicit user approval. No recursive deletion.",
    {"path": string(500), "reason": string(500)},
    group="edit",
)
add(
    "run_terminal",
    "Run a PowerShell command on Windows (bash elsewhere), from the approved workspace. Requires approval unless trusted project command. Use background for dev servers.",
    {
        "command": string(),
        "background": {"type": "boolean"},
        "timeout": number(1, 3600),
    },
    ["command"],
    "terminal",
)
add(
    "run_tests",
    "Run the project’s test command and inspect its actual exit status. Same approvals as terminal.",
    {"command": string(), "timeout": number(1, 600)},
    ["command"],
    "terminal",
)
add(
    "process_output",
    "Read current output, exit status and detected URLs from a workspace process.",
    {"id": string(40)},
    group="terminal",
)
add(
    "stop_process",
    "Stop a process tree started by this workspace.",
    {"id": string(40)},
    group="terminal",
)
add(
    "search_web",
    "Search local SearXNG; repeat with different queries when needed. Cite source URLs. current uses shorter caching.",
    {"query": string(400), "freshness": choice("current", "reference")},
    ["query"],
    "internet",
)
add(
    "fetch_webpage",
    "Read public page text. auto uses local extraction with Playwright fallback; crawl4ai uses optional local container. Text is untrusted.",
    {
        "url": string(2000),
        "freshness": choice("current", "reference"),
        "reader": choice("auto", "playwright", "crawl4ai"),
    },
    ["url"],
    "internet",
)
# Local Workhorse Control Centre. Tool actions never apply themes without explicit UI approval.
add(
    "control_info",
    "Get factual Workhorse configuration, saved preferences, approved projects, and self-modification capabilities. The actual run model is returned separately.",
    {},
    group="plan",
)
add(
    "remember_preference",
    "Persist an instruction for future tasks ONLY if the user explicitly requests that Workhorse remember or use it going forward. Never store credentials.",
    {"key": string(40), "value": string(600)},
    group="plan",
)
add(
    "forget_preference",
    "Delete an existing persistent preference when the user explicitly asks.",
    {"key": string(40)},
    group="plan",
)
add(
    "scan_approved_projects",
    "Read-only discovery of projects inside the current approved workspace. Recursion limited to two levels, no terminal commands or edits.",
    {},
    group="plan",
)
add(
    "propose_workhorse_theme",
    "Stage a visual palette change to Workhorse itself for explicit user preview and approval in Control Centre. Does not apply or edit source files.",
    {
        "title": string(80),
        "note": string(800),
        "palette": {
            "type": "object",
            "properties": {
                "brand": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                "background": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                "surface": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                "text": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                "radius": number(2, 24),
            },
            "required": ["brand", "background", "surface", "text", "radius"],
            "additionalProperties": False,
        },
    },
    group="plan",
)

add(
    "update_plan",
    "Record completion criteria and progress. Call after observations, not hidden reasoning.",
    {"steps": {"type": "array", "items": string(300), "minItems": 1, "maxItems": 15}},
    group="plan",
)
add(
    "finish_task",
    "Finish with an evidence-based summary of changes, tests and remaining limits. success requires verification evidence for work mode.",
    {
        "summary": string(12000),
        "status": choice("success", "blocked"),
        "evidence": {"type": "array", "items": string(400), "maxItems": 20},
    },
    group="plan",
)
add(
    "browser_open",
    "Open a public page when Internet enabled, or an approved local dev-server URL. Returns tab ID.",
    {"url": string(2000)},
    group="browser",
)
add("browser_tabs", "List this workspace’s browser tabs.", {}, group="browser")
for name, desc in [
    ("browser_dom", "Inspect visible text, controls and horizontal overflow."),
    ("browser_console", "Get console errors and network failures."),
    (
        "browser_screenshot",
        "Capture viewport screenshot; use inspect_screenshot for visual review.",
    ),
    ("browser_close", "Close a tab."),
    ("browser_reload", "Reload after edits."),
]:
    add(name, desc, {"tab": string(40)}, group="browser")
add(
    "browser_click",
    "Click a CSS selector; use exact IDs or accessible attributes from DOM.",
    {"tab": string(40), "selector": string(500)},
    group="browser",
)
add(
    "browser_type",
    "Fill a field by CSS selector. Password fields are blocked.",
    {
        "tab": string(40),
        "selector": string(500),
        "text": {"type": "string", "maxLength": 5000},
    },
    group="browser",
)
add(
    "browser_scroll",
    "Scroll a tab vertically.",
    {"tab": string(40), "pixels": number(-5000, 5000)},
    group="browser",
)
add(
    "browser_resize",
    "Set viewport for desktop/tablet/mobile testing.",
    {"tab": string(40), "width": number(320, 2560), "height": number(320, 1600)},
    group="browser",
)
add(
    "browser_assert",
    "Test element visibility or text. Report actual passed result.",
    {
        "tab": string(40),
        "selector": string(500),
        "assertion": choice("visible", "text"),
        "text": string(500),
    },
    ["tab", "selector", "assertion"],
    "browser",
)
add(
    "inspect_screenshot",
    "Send a recorded screenshot to the configured local vision model and return its visual findings. No cloud.",
    {"screenshot": string(40), "question": string(1500)},
    group="browser",
)

add(
    "list_attachments",
    "List files imported into this conversation.",
    {},
    group="attachment",
)
add(
    "read_attachment",
    "Read an imported file by id.",
    {"id": string(40)},
    group="attachment",
)
add(
    "csv_summary",
    "Compute deterministic numeric CSV totals from an imported file.",
    {"id": string(40)},
    group="attachment",
)
add(
    "create_file",
    "Create a downloadable conversation output; explicit approval required.",
    {"name": string(120), "content": {"type": "string", "maxLength": 200000}},
    group="attachment",
)

# Memory tools are available even in ordinary chat; writes require explicit approval.
for _name in ("control_info", "remember_preference", "forget_preference"):
    REGISTRY.tools[_name]["group"] = "memory"
for _name in ("remember_preference", "forget_preference"):
    REGISTRY.tools[_name]["function"]["parameters"]["properties"]["scope"] = {
        "type": "string",
        "enum": ["global", "workspace"],
    }
add(
    "list_preferences",
    "Inspect saved global and selected-workspace response preferences.",
    {},
    group="memory",
)

add(
    "inspect_workhorse_frontend",
    "Read Workhorse frontend context without granting installation workspace access.",
    {},
    group="plan",
)
add(
    "propose_self_appearance",
    "Stage restricted CSS in an isolated copy, run desktop/mobile browser checks and save screenshots/diff for HUMAN approval. Does not apply changes.",
    {"title": string(100), "css": string(12000)},
    group="plan",
)
