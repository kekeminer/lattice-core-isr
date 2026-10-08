#!/usr/bin/env python3
"""
LATTICE-CORE ISR - Root Execution Wrapper
"""
import sys
from lattice_isr.main import run_orchestrator

if __name__ == "__main__":
    stream_url = sys.argv[1] if len(sys.argv) > 1 else None
    run_orchestrator(stream_override=stream_url)
