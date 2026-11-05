### Changed
- AC-2: `delegate.py` owns the complexity policy (`COMPLEXITY_ORDER`, `highest_complexity`, `builder_recommendation`); `handoff-write.recommended_agent()` calls it instead of keeping its own tier and effort tables.
