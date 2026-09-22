# DewuClaw Handoff: Scheduling Flow Visualization Redesign

## Objective

Redesign the existing interactive scheduling-flow page so it is visually
clear, polished, and suitable for explaining an industrial dispatch workflow.
This is a frontend presentation task, not a scheduling-logic rewrite.

Before editing, inspect the skills available in DewuClaw and use the strongest
relevant UI/UX, frontend-design, information-visualization, and browser-testing
skills. The current feedback is that the page still looks unattractive and
visually disorganized. Do not limit the work to color or spacing changes;
rethink the information hierarchy and interaction composition.

## Workspace

- Repository: `/Users/admin/Desktop/钢包配包`
- Branch: `feature-1.0`
- Page entry: `visualization/index.html`
- Current redesign commit: `addba71`
- Initial visualization commit: `b083d8d`
- Local preview command:

  ```bash
  python3 -m http.server 4173 --directory visualization
  ```

- Preview URL: `http://127.0.0.1:4173/`

The worktree contains unrelated untracked Trellis, OpenSpec, report, and real
data output files. Preserve them. Only modify files under `visualization/`
unless a directly required frontend asset must be added.

## Business Truth That Must Not Change

1. Preallocation starts 180 minutes before converter blowing/pour preparation.
   It is 180 minutes, not 180 seconds.
2. Heat lifecycle states are `unallocated`, `preallocated`, and `locked`.
3. A locked heat and its existing assignment cannot be overwritten by a
   disturbance response.
4. Supported single disturbances are:
   - `crane_offline`: crane unavailable
   - `ladle_unavailable`: ladle unavailable
   - `facility_unavailable`: facility unavailable
   - `schedule_deviation`: schedule deviation
5. Only affected, non-locked heats enter local rescheduling.
6. The decision tree always runs first.
7. LLM ReAct is allowed only when the decision tree fails and the remaining
   budget is positive.
8. The budget formula is:

   ```text
   earliest_pour_at - occurred_at - 90 seconds
   ```

9. When the budget is zero or negative, the system must not invoke the LLM. It
   returns Frozen plus `human_review_required=true`.
10. An LLM response is usable only after it returns a complete mapping and
    passes the same hard constraints as the decision tree. Timeout, invalid
    JSON, missing or duplicate heats/resources, and constraint violations all
    lead to rejection and human review.
11. This page is an interactive explanation only. It does not call an LLM,
    write production assignments, or represent a live production-control UI.

## Required Interactive States

The page must make these three paths immediately understandable:

### Path A: Decision Tree Success

```text
180-minute preallocation window
-> disturbance
-> exclude locked heats
-> decision-tree local rescheduling succeeds
-> adopt validated decision-tree result
-> LLM is not called
```

### Path B: LLM Fallback Success

```text
disturbance
-> decision-tree local rescheduling fails
-> remaining budget > 0
-> LLM ReAct produces a complete proposal
-> hard-constraint validation passes
-> adopt validated LLM result
```

### Path C: Human Review

Either:

```text
decision tree fails
-> remaining budget <= 0
-> do not call LLM
-> Frozen + human review
```

or:

```text
decision tree fails
-> remaining budget > 0
-> LLM fails, times out, or violates validation
-> Frozen + human review
```

The user must be able to switch paths and select one of the twenty audited
disturbance scenarios,
and change the time remaining until the earliest pour. The visible result,
budget, path, and locked-heat treatment must update consistently.

## Design Direction

- Audience: operations, scheduling, engineering, and product reviewers.
- Tone: quiet, precise, industrial, and work-focused. It should feel like an
  operational explainer, not a marketing landing page.
- The primary visual should be the process itself. Controls and supporting
  details must remain secondary.
- Prefer progressive disclosure and one dominant visual path. Do not show
  every explanation, metric, branch, and state at the same visual weight.
- Make the distinction between the 180-minute preallocation window and the
  90-second safety buffer unmistakable.
- Show locked heats as excluded and unchanged, not as failed work.
- Use restrained color semantics: neutral structure, green for accepted,
  amber for disturbance/wait, blue for LLM computation, red for Frozen/manual
  review. Color must not be the only state signal.
- Avoid nested cards, dashboard KPI filler, oversized headings, decorative
  gradients, bokeh/orbs, excessive rounded pills, and large blocks of visible
  instructional text.
- Use familiar controls: segmented control for scenario paths, native/select
  menu for disturbance type, and slider/input for event timing.
- Text must remain readable and must not overlap at desktop or mobile widths.
- The page should fit naturally at 1440x900 and reflow cleanly at 390x844.

You may replace the current composition completely. Preserving the current CSS
or DOM structure is not required. Keep the business behavior and user-facing
interaction contract.

## Technical Constraints

- Keep the page locally runnable without a backend, API key, or network call.
- Prefer dependency-free HTML/CSS/JavaScript. Do not add a build system unless
  it produces a materially better result and is clearly justified.
- Do not duplicate or reinterpret scheduling logic outside the stated display
  model.
- Do not edit backend scheduling modules.
- Do not include secrets, real API calls, or production-write actions.
- Preserve keyboard accessibility and semantic controls.

## Verification

Before finishing:

1. Open the page in a real browser at 1440x900 and 390x844.
2. Verify there is no horizontal overflow, clipping, text collision, or
   incoherent overlap.
3. Exercise all three response paths.
4. Exercise all four disturbance options.
5. Verify timing changes update the displayed budget using the 90-second
   buffer.
6. Verify the LLM path cannot appear when the budget is exhausted.
7. Verify the locked heat remains excluded in every path.
8. Check the browser console for errors and warnings.
9. Run `git diff --check`.
10. Run the existing backend tests to ensure the frontend-only change did not
    disturb the repository:

    ```bash
    /tmp/ladle-rescheduling-venv/bin/python -m pytest -q
    ```

## Delivery

- Leave the polished page running at `http://127.0.0.1:4173/` for review.
- Summarize the visual hierarchy and interaction changes.
- Report desktop/mobile verification and the three-path behavior checks.
- Commit only the intended visualization files with a focused commit message.
