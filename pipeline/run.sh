#!/bin/bash
# Check if virtual environment exists and activate it
if [ -d ".venv" ]; then
    source .venv/Scripts/activate
elif [ -d "venv" ]; then
    source venv/Scripts/activate
fi

# Run the pipeline script
python pipeline/run.py
