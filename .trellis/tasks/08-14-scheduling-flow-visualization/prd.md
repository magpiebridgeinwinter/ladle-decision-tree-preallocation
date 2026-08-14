# 调度流程可视化

## Goal

Provide an interactive, local web page that makes the implemented ladle
preallocation and local-rescheduling control flow understandable at a glance.

## Requirements

- Show the 180-minute preallocation window and the `unallocated`,
  `preallocated`, and `locked` lifecycle states.
- Let a viewer select one of the four supported disturbance kinds and choose
  an event timing relative to the earliest pour.
- Visualize the actual routing: decision tree first; LLM only after a
  non-emergency decision-tree failure; Frozen plus a human-review signal when
  the 90-second buffer has been reached or the LLM cannot produce a valid plan.
- Display the budget formula and a readable per-step execution trace.
- Remain a dependency-free static page that can be opened locally.

## Acceptance Criteria

- [x] Users can interactively switch among successful decision-tree,
  decision-tree-failure/LLM-success, and exhausted-budget/manual-review paths.
- [x] The visualized time semantics distinguish the 180-minute preallocation
  window from the 90-second safety buffer.
- [x] The page presents the four supported disturbance types and excludes
  locked heats from reallocation.
- [x] The page renders cleanly at desktop and mobile widths without requiring
  a backend or API key.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
