#!/usr/bin/env python3
"""Portable timestamp for chronicle memory writes.

Usage:
    python3 timestamp.py

Output example:
    Tuesday, 24-06-2026, 3:15 pm
"""
from datetime import datetime

n = datetime.now()
print(n.strftime("%A, %d-%m-%Y, %-I:%M ") + n.strftime("%p").lower())
