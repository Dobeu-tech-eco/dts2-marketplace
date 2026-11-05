### Changed
- AC-1: `profiles.py` (`Profiles.load/get/model/token_burn/lead_eligible`) is the one profile loader; roster, delegate, council, agent-memory and failover use it, and tests can inject a dict-built `Profiles`.
