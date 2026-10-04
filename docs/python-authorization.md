# Python command authorization compatibility

The default wrapper's live-request predicate, coordinate-observation predicate
and authorization report now delegate to Python. Startup live permission remains
immutable; an argument containing an authority-looking flag or a JSON field
cannot grant it. Missing observation is checked before missing live permission.
The original act/app/plan/scenario/desktop-benchmark/l5 cases, preflight overrides,
notice levels/messages, null arguments, case-insensitive comparisons and
presence-based `--after`/`--force` behavior remain unchanged.

The historical public function names and top-level calls remain compatibility
delegates. There is no new dispatch, native action, input, shell, implicit
confirmation or retry. The new module is also usable by the pending Python
top-level Node forwarding owner; this checkpoint does not promote that owner.

`test_authorization_production.py` compares 68 authority/argv cases per actual
PS5.1/PS7 shell against immutable `afd880b`, then the actual delegates and the
Python functions. Boundary cases refuse forged startup fields before dispatch.
All acquisitions are inert. The unchanged source/dispatch/safety invariant
guards remain required.

This candidate removes 2,000 real PowerShell bytes, from 763,043 to 761,043.
It does not connect new macros or complete the 0% goal.
