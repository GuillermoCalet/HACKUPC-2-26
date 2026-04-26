#!/bin/bash

# Start all 5 real agents for Creative Boardroom

echo "🚀 Starting Creative Boardroom agents..."
echo ""

if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Creating .venv..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
fi

# Kill any existing agents
echo "🛑 Cleaning up old processes..."
pkill -f "uvicorn agents"
sleep 1

# Start each agent in background
echo "Starting agents..."
echo ""

uvicorn agents.performance:app --port 8001 --reload &
echo "✅ Performance Analyst (8001)"

uvicorn agents.fatigue:app --port 8002 --reload &
echo "✅ Fatigue Detective (8002)"

uvicorn agents.risk:app --port 8003 --reload &
echo "✅ Risk Officer (8003)"

uvicorn agents.visual:app --port 8004 --reload &
echo "✅ Visual Critic (8004)"

uvicorn agents.audience:app --port 8005 --reload &
echo "✅ Audience Simulator (8005)"

echo ""
echo "🎉 All agents started! (Takes ~10 seconds to be ready)"
echo ""
echo "In another terminal, run:"
echo "  uvicorn orchestrator.server:app --port 8000"
echo ""
echo "Then open the frontend:"
echo "  streamlit run frontend/app.py"
echo ""
echo "Press Ctrl+C to stop all agents"
echo ""

wait
