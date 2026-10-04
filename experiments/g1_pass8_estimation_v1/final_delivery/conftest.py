"""M5 final-delivery scoped pytest adapter; preserve original standalone tests.

Only the original basename is excluded from recursive collection. The uniquely
named adapter runs all43 checks, with the import guard in a fresh interpreter.
"""
collect_ignore = ["test_final_verification.py"]
