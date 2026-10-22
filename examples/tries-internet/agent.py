"""An agent that tries to reach the internet directly, for the forgery check.

It is signed and submitted like any agent. It fetches https://example.com without going through
Veriphex and writes whether that failed. In the sealed space it must fail, and Veriphex must
record the attempt (example.com:443) as an egress refusal for the job.
"""
import json
import os
import urllib.request
from pathlib import Path


def main():
    try:
        with urllib.request.urlopen('https://example.com', timeout=10) as resp:
            outcome = {'reached_internet': True, 'status': resp.status}
    except Exception as exc:  # any failure is the expected outcome
        outcome = {'reached_internet': False, 'error': type(exc).__name__}
    text = ('The direct internet attempt failed, as it should in the sealed space.'
            if not outcome['reached_internet'] else
            'The direct internet attempt SUCCEEDED. The sealed space let it out.')
    Path(os.environ['VERIPHEX_RESULT_FILE']).write_text(text + '\n' + json.dumps(outcome), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
