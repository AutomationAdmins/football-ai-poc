import concurrent.futures
from ai_engine import _chat

def make_call(i):
    print(f"Call {i} starting")
    res = _chat("Say hello", max_tokens=10)
    print(f"Call {i} done")
    return res

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(make_call, i) for i in range(2)]
    for f in concurrent.futures.as_completed(futures):
        print(f.result())

