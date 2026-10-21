"""Fixture server that reads stdin and never answers. Used to test the timeout."""
import sys
import time

for _line in sys.stdin:
    time.sleep(0.01)
