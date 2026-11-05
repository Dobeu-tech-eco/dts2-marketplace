# Lane overlap
Spec: two lanes both plan to edit `src/shared.py`. The overlap check must report one file conflict so the head
serialises the lanes instead of running them in parallel. Both lanes then build green.
