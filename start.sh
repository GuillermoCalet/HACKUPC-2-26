#!/bin/bash
echo "🚀 Starting Creative Boardroom Environment..."

# 1. Ensure venv exists and activate
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# 2. Check/Install dependencies
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt --quiet

# 3. Kill any previously running instances on these ports
echo "Cleaning up old processes..."
pkill -f "uvicorn agents"
pkill -f "uvicorn orchestrator.server:app"
pkill -f "streamlit run frontend/app.py"

echo "✅ Environment ready. Starting servers..."

# 4. Start agents in background
uvicorn agents.performance:app --port 8001 &
uvicorn agents.fatigue:app --port 8002 &
uvicorn agents.risk:app --port 8003 &
uvicorn agents.visual:app --port 8004 &
uvicorn agents.audience:app --port 8005 &

# 5. Start Orchestrator
uvicorn orchestrator.server:app --port 8000 &

echo "⏳ Waiting for backend to initialize (5s)..."
sleep 5

# 6. Start Streamlit (this blocks and keeps the terminal open)
echo "🖥️ Starting Frontend..."
streamlit run frontend/app.py
