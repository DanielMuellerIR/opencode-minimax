from calc import average

# A tiny self-reporting test: prints a clear FAIL line (and exits 1) instead of dumping
# a raw traceback, so the demo output stays readable.
def check():
    assert average([2, 4, 6]) == 4, "average([2, 4, 6]) should be 4"
    assert average([]) == 0.0, "average([]) should be 0.0, not raise"

try:
    check()
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    raise SystemExit(1)
print("OK")
