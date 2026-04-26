# Smadex Creative Boardroom
**HackUPC 2026 - Smadex Challenge**

Smadex Creative Boardroom is a Multi-Agent AI System designed to automate creative fatigue detection, data analysis, and decision-making for ad campaigns. Instead of relying on manual dashboards, our Agent Pipeline simulates a live "Boardroom" where 5 specialized AI personas aggressively debate the performance metrics and visual quality of each creative to deliver a final, actionable verdict.

## 🌐 Live Demo
Check out the fully functional deployment on Render:
**[https://hackupc-2-26.onrender.com]**

## The Agents

The simulated boardroom is driven by five specialized profiles:
1. **Performance Analyst:** Analyzes CTR, IPM, Conversion Rates, and delivery metrics.
2. **Risk Officer:** Protects the budget by monitoring Spend Share, ROAS, and statistical confidence intervals.
3. **Fatigue Detective:** Uses 7-day decay slopes to detect audience wear-out before budget is wasted.
4. **Visual Critic:** Critiques metadata, colors, formats, CTAs, and overall creative hook structure.
5. **Audience Simulator:** Evaluates demographic suitability and emotional resonance based on target regions.
* **Orchestrator (*The Judge*):** Weighs the conflicting opinions from the 5 agents and dictates the final consensus (SCALE, PAUSE, PIVOT, or TEST_NEXT).

## System Architecture

- **Backend / Orchestrator:** Powered by FastAPI. The communication framework leverages an Agent-to-Agent (A2A) protocol where opinions are generated via heuristic bounds and simulated LLM prompts.
- **Data Engine:** Uses Pandas and PyArrow to ingest the original `creative_features.parquet` dataset.
- **Frontend / UI:** A responsive glassmorphism Dashboard built with Streamlit presenting dynamic metrics and an interactive live-debate node diagram.

## Quick Start (Local Deployment)

Make sure you have Python 3.10+ installed.

```bash
chmod +x start.sh
./start.sh
```
