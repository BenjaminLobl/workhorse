# Design-first mode

Workhorse now routes `Development / Work` tasks to `coding_model` (default `qwen3.8:27b`), or to `design_model` (also `qwen3.8:27b`) when **Design first** is selected. Ordinary chat still uses the manually selected default model. Screenshot review uses `vision_model` (default `gemma4:12b`). Only installed local Ollama models can run.

Design-first instructions prioritize visual hierarchy, typography, coherent components, relevant photography, working controls and desktop/mobile browser previews. A changed website must pass existing test/verification checks and have a screenshot from the active run reviewed by the vision model *after* the latest changes before `finish_task(success)` can be accepted. The model is instructed to inspect both desktop and mobile screenshots and revise as needed; the gate enforces at least one successful review, not a guaranteed quality threshold or automatic unlimited refinement. When visual tools aren't available, it must report the limitation.

These preferences are stored in the existing Workhorse config; model routing occurs in the backend. Screen-sharing and external uploads are not enabled, and existing permissions remain in force. Workhorse still requires a manually approved workspace for website edits and browser permission to inspect rendered pages.
