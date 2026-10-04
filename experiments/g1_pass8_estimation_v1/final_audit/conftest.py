"""M5-only pytest discovery adapter; historical M4 evidence is unchanged.

The original M5 standalone script remains executable and byte-preserved. Its
assertion-identical, uniquely named adapter is the recursive pytest entrypoint.
"""
collect_ignore = ["test_independent_final_audit.py"]
