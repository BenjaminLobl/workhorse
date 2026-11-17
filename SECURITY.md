# Workhorse permission boundaries

## Intended deployment

One trusted user on one computer, bound to IPv4 loopback. No public hosting, multi-user isolation or remote administration. The server uses a per-start HttpOnly/SameSite cookie, Host and Origin checks, JSON-only writes and a same-origin content policy. This reduces browser-origin attacks; it does not defend against software already running under your account. Keep Python, Chromium, Ollama and Docker updated.

## Files and commands are different boundaries

Filesystem tools reject absolute paths, traversal, symlinks/junctions, hard-linked files and protected secret/dependency folders. They operate under a directory explicitly approved in the UI. Approved paths are resolved when registered. These checks are not a kernel sandbox and cannot defeat every concurrent filesystem race by a hostile local process.

Native shell commands run as your Windows user, with a workspace working directory and a reduced environment. They can still read/write outside the workspace, access your home directory, run project scripts, reach networks and launch other programs. A command's working directory does not confine its effects. Enabling terminal alone does not auto-approve commands; every command is reviewed unless the separate routine-script trust option is enabled. Do not enable that option for downloaded/untrusted projects. Commands outside the narrow trusted set always require approval. There is no regex that makes arbitrary shell execution safe.

Browser automation uses an isolated, unauthenticated browser profile. Access to local URLs is restricted to approved origins or detected managed dev servers; control ports are always blocked. Public URLs require Internet permission and public-address checks. The default non-browser page reader additionally pins IP addresses across DNS resolution. Playwright DNS checks are request-level checks, not an egress firewall; optional Crawl4AI has weaker redirect/subresource restrictions and requires approval. Do not use either renderer as an enterprise network-isolation boundary. Browser contexts are suspended offline between runs; Chromium has its own background networking behaviour.

## Prompt injection and data

Retrieved pages/files are labelled untrusted in the agent prompt. Schema validation and tool permissions are enforced in code, but a model can still be persuaded to misuse allowed actions. Review commands and diffs. Approval is tied to one concrete pending action and expires; rejected actions are not silently run.

Known secret paths are excluded and obvious credential patterns are redacted in results/logs. Command output also masks values found in root `.env*` files. This is best-effort detection, not comprehensive data-loss prevention. Do not paste credentials into prompts, command arguments, forms or source files intended for model reading. Screenshots mask password inputs, but can contain other private page content. Conversation imports and prompts are locally stored as supplied by you.

SQLite, audits and screenshots are unencrypted local files. Redaction does not encrypt them. Deleting a chat retains workspace tool/change history for review. Stop the server before backup/reset. No automatic Git push, commit or deployment occurs; scripts you explicitly approve can themselves perform external actions.

## Before unattended/business use

Use a dedicated low-privilege account and preferably a container/VM command runner, constrain outbound networks, pin service versions, set backup/retention rules and conduct a security review. This release intentionally does not claim hardened multi-tenant or untrusted-code isolation.
