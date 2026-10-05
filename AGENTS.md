# AGENTS.md

<!-- gentle-shared-skills:orchestration BEGIN -->
## Development Orchestration Rule (shared-skills)

Mandatory layering for ANY development work, regardless of size or domain:

1. **Main conversation (orchestrator)**: ALWAYS start one of the HumanLayer
   workflows before implementing. Entry point: `humanlayer-task-workflow`
   (selects the smallest workflow with the necessary human gates). Finite
   task → `humanlayer-rpi-workflow`; product/system design decisions →
   `humanlayer-prd-tdd-workflow`; recurring or scheduled improvement loops →
   `humanlayer-design-control-loop`. Never implement before the workflow's
   design gate is approved.
2. **Implementation executor**: ALWAYS use the SDD skills
   (`sdd-init/explore/propose/spec/design/tasks/apply/verify/archive`), with
   Strict TDD when the project supports it. This overrides any "SDD only by
   explicit request" default: after the design gate is approved, SDD is the
   implementation route.

Details: shared-skills repo, `SYSTEM_PROMPT.md`.
<!-- gentle-shared-skills:orchestration END -->
