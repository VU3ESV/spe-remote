#!/bin/bash
# Start SPE Remote Control server
cd "$(dirname "$0")"
exec venv/bin/python server.py "$@"
