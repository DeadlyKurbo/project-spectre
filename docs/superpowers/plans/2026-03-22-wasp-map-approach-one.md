# WASP Map Approach One Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the WASP interactive map first, then improve visual quality, then ship QoL improvements while staying in the existing architecture.

**Architecture:** Keep the current `templates/wasp_map.html` + `static/js/wasp_engine.js` structure and apply targeted in-place fixes. Prioritize event/input correctness and state sync reliability in Phase A, then improve icon/label rendering and panel ergonomics without introducing new runtime dependencies.

**Tech Stack:** Vanilla JS (ES modules), Three.js sprites/canvas textures, HTML/CSS template UI.

---

### Task 1: Phase A - Interaction correctness and sync hardening

**Files:**
- Modify: `static/js/wasp_engine.js`
- Test: Manual browser verification in `/wasp-map`

- [ ] **Step 1: Add failing behavior checks (manual repro list)**
  - Click detection misses when canvas is offset/scrolled.
  - Click events can fire while pointer interaction starts in panel overlays.
  - State sync conflict can reset local changes during active edits.

- [ ] **Step 2: Implement minimal fixes**
  - Use renderer container bounds for pointer-to-NDC conversion.
  - Track pointerdown origin and only map-click when pointer started on map.
  - Add sync guard to avoid applying stale remote state while local changes are pending.
  - Keep mode/selection transitions deterministic when moving/deleting units.

- [ ] **Step 3: Verify Phase A manually**
  - Select/move/delete/spawn remains consistent.
  - Right-click menu and panel interactions no longer trigger accidental map actions.
  - Two-tab shared state no longer clobbers in-progress local interactions.

### Task 2: Phase C - Visual quality refresh

**Files:**
- Modify: `static/js/wasp_engine.js`

- [ ] **Step 1: Improve icon generation**
  - Replace rough silhouettes with cleaner geometric symbols.
  - Add side-color accent ring for immediate faction recognition.

- [ ] **Step 2: Improve labels and clustering legibility**
  - Better label contrast/size for distance readability.
  - Less noisy overlap behavior and clearer cluster badges.

- [ ] **Step 3: Verify visual output**
  - Icons remain distinct at different zoom levels.
  - Label/cluster readability improves without performance regression.

### Task 3: Phase B - QoL and screen real estate improvements

**Files:**
- Modify: `templates/wasp_map.html`
- Modify: `static/js/wasp_engine.js`

- [ ] **Step 1: Improve map-first layout**
  - Make admin panel more compact and add visible state chips.
  - Keep fullscreen and panel collapse behavior robust.

- [ ] **Step 2: Add operator affordances**
  - Add reset-view action and shortcut hints.
  - Improve mode/status messaging clarity.

- [ ] **Step 3: Verify UX flow**
  - Main interactions require fewer clicks.
  - Operators can recover camera/mode state quickly.

### Task 4: Validation and cleanup

**Files:**
- Modify: `static/js/wasp_engine.js` (as needed)
- Modify: `templates/wasp_map.html` (as needed)

- [ ] **Step 1: Run static checks**
  - `node --check static/js/wasp_engine.js`

- [ ] **Step 2: Run targeted tests for map state API stability**
  - `pytest tests/test_wasp_map_state_module.py tests/test_wasp_map_state_api.py -q`

- [ ] **Step 3: Fix regressions and document outcomes**
  - Resolve any syntax/runtime issues and summarize behavior changes.
