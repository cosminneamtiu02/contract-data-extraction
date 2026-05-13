"""LLM inference layer — Ollama-backed extraction (plan §6.5).

Concrete components implement extraction via ``OllamaLlmClient`` in ``client``
and are wired by the Phase 4 pipeline. Tasks 3.2-3.7 add prompt building,
schema validation, retry logic, and timeout handling in subsequent commits.

``__all__`` is intentionally empty at the task-3.1 stage; later tasks re-export
the stable public surface (``OllamaLlmClient`` at minimum) once all layer-A
peers have landed and the module's public contract is finalised.
"""

__all__: list[str] = []
