#!/bin/bash
# Run Paraphe from the checkout with the project's virtual environment.
cd "$(dirname "$0")" && exec .venv/bin/python -m paraphe "$@"
