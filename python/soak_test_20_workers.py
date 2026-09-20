"""Deprecated launcher for :mod:`tools.soak_test_20_workers`."""

import runpy

if __name__ == "__main__":
    runpy.run_module("tools.soak_test_20_workers", run_name="__main__")
