"""Pipeline orchestration package (Phase 4).

Contains the in-process worker plumbing that ties the OCR layer (Phase 2)
to the LLM layer (Phase 3): result store, pipeline state, OCR worker, LLM
worker, and idle watchdog. See docs/plan.md §3 + §6.6 for architecture
and the per-task table.
"""
