# Creative Boardroom — Project Reference

> **Purpose of this document:** This file is the single source of truth for the Creative Boardroom project. Every team member works independently using their own AI assistant. This document ensures all AI engines understand the full context, architecture, constraints, and implementation details so that code written separately composes correctly when integrated.

---

## 1. What We Are Building

**Creative Boardroom** is an AI-powered creative decision copilot for mobile advertisers. A marketer selects one ad creative from a campaign, and a panel of five specialized AI agents analyzes it from different perspectives — performance metrics, fatigue detection, visual quality, audience fit, and risk — then **debates via Google's A2A (Agent-to-Agent) protocol** until they reach a consensus verdict:

- **SCALE** — increase budget and distribution on this creative
- **PAUSE** — stop running it immediately
- **PIVOT** — change direction significantly
- **TEST NEXT** — not enough data yet; design a follow-up experiment

The marketer sees not just the verdict but a full transcript of the deliberation: which agents agreed, who challenged whom, and whether any agent changed its mind mid-debate. This explainability is the core product value.

---

## 2. Business Context

This project is built for the **Smadex Creative Intelligence Hackathon**. Smadex is an ad-tech company. The problem they want solved:

- Mobile advertisers run hundreds of ad creatives across campaigns, countries, and devices
- Knowing which creatives are working, why, and when they start losing effectiveness is extremely hard
- Decisions are currently based on raw dashboards with no structured reasoning layer

**Key mentor guidance received:**
- Focus on **one campaign only** for the demo — go deep, not broad
- Recommendations must be at the **creative level** (not campaign-level)
- After joining the dataset, **two columns likely make a disproportionate difference** in predicting performance — discovering them is a priority task
- Clustering/similarity is allowed but only as context around a selected creative, not the primary feature
- The final presentation must explain how the architecture scales to all campaigns

**Judging criteria:** Usefulness · Clarity · Technical Quality · Creativity · Demo Quality

---

## 3. Dataset

We receive a synthetic but realistic Smadex dataset. The files we expect are:

| File | Contents | Key columns |
|---|---|---|
| `advertisers.csv` | Advertiser master data | `advertiser_id`, `name`, `vertical` |
| `campaigns.csv` | Campaign metadata | `campaign_id`, `advertiser_id`, `objective`, `country`, `os`, `budget` |
| `creatives.csv` | Creative metadata | `creative_id`, `campaign_id`, `format`, `duration`, `width`, `height`, `name` |
| `daily_perf.csv` | Daily performance per creative | `creative_id`, `campaign_id`, `date`, `impressions`, `clicks`, `installs`, `spend` |
| `creative_summaries.csv` | Pre-generated text summaries of creatives | `creative_id`, `summary` |
| `campaign_summaries.csv` | Pre-generated text summaries of campaigns | `campaign_id`, `summary` |
| `images/` | Folder with 1000+ image assets, one per creative | filenames match `creative_id` |

**Important:** The exact column names may differ slightly. Always run `df.head()` and `df.dtypes` on every file before assuming schema. Document any discrepancies.

---

## 4. Technology Stack

Every team member must use these technologies. Do not introduce alternatives without team agreement.

| Layer | Technology | Notes |
|---|---|---|
| Language | **Python 3.11+** | Everywhere — data, agents, orchestrator |
| Agent servers | **FastAPI + Uvicorn** | One FastAPI app per agent, run as separate processes |
| HTTP client | **httpx** (async) | Used by orchestrator to call agents |
| Data processing | **DuckDB + Parquet** | DuckDB for SQL joins on CSVs; Parquet as the cache format |
| Data manipulation | **pandas + pyarrow** | For Python-side processing after DuckDB |
| Statistics | **scipy.stats** | Confidence intervals, regression slopes |
| LLM SDK | **anthropic** Python SDK | Primary. See model table in section 7 |
| Image handling | **Pillow** | For loading and base64-encoding images |
| Persistence | **SQLite** (file: `evidence.db`) | Stores all agent messages and opinions |
| Frontend | **Streamlit** | Default choice. Only switch to Next.js if Person D is experienced with it |
| Config | **python-dotenv** + `.env` file | API keys, campaign ID, paths |
| Schema validation | **pydantic v2** | All A2A message types are pydantic models |

**Do not use:** LangChain, LangGraph, CrewAI, AutoGen, Redis, Kafka, Docker, vector databases, or any agent framework. These add complexity without adding visible value in the demo.

---

## 5. Repository Structure

```
creative-boardroom/
│
├── .env                          # API keys and config — never commit this
├── .env.example                  # Template showing required env vars
├── requirements.txt
├── CREATIVE_BOARDROOM.md         # This file
├── SCHEMA.md                     # Written by Person A after data exploration
│
├── data/                         # Raw dataset files (gitignored if large)
│   ├── advertisers.csv
│   ├── campaigns.csv
│   ├── creatives.csv
│   ├── daily_perf.csv
│   ├── creative_summaries.csv
│   ├── campaign_summaries.csv
│   └── images/
│
├── pipeline/                     # Person A owns this folder
│   ├── build_table.py            # Builds creative_features.parquet
│   ├── discover_features.py      # Finds the two important columns
│   └── creative_features.parquet # Output — shared by all agents
│
├── orchestrator/                 # Person B owns this folder
│   ├── a2a.py                    # All pydantic message type definitions
│   ├── base.py                   # Shared FastAPI scaffold for agents
│   ├── server.py                 # Orchestrator HTTP server
│   ├── debate.py                 # 3-round deliberation logic
│   └── evidence_store.py         # SQLite read/write helpers
│
├── agents/                       # Person C owns this folder
│   ├── performance.py
│   ├── fatigue.py
│   ├── risk.py
│   ├── visual.py
│   ├── audience.py
│   └── prompts/                  # All prompt templates as .txt files
│       ├── performance.txt
│       ├── fatigue.txt
│       ├── risk.txt
│       ├── visual.txt
│       ├── audience.txt
│       ├── respond.txt           # Shared challenge/respond prompt
│       └── synthesizer.txt
│
├── synthesizer/
│   └── synthesize.py             # Final verdict generator (Person C)
│
├── frontend/
│   └── app.py                    # Streamlit app (Person D)
│
└── evidence.db                   # Created at runtime, gitignored
```

---

## 6. The A2A Protocol — How It Works

A2A (Agent-to-Agent) is a protocol by Google for inter-agent communication. For our purposes it means three things:

### 6.1 Agent Cards
Every agent exposes a JSON description of itself at `GET /.well-known/agent.json`. The orchestrator calls this at startup to discover all agents. Example:

```json
{
  "name": "fatigue_detective",
  "description": "Detects creative fatigue by analyzing performance decay trends and frequency saturation",
  "skills": ["analyze_fatigue", "respond_to_challenge"],
  "endpoint": "http://localhost:8002",
  "vote_weight": 1.0
}
```

### 6.2 Message Types
All inter-agent communication uses typed pydantic models defined in `orchestrator/a2a.py`. These are the canonical types — every agent must import from here, never define their own:

```python
# orchestrator/a2a.py

from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime

class AgentCard(BaseModel):
    name: str
    description: str
    skills: list[str]
    endpoint: str
    vote_weight: float

class Evidence(BaseModel):
    type: Literal["metric", "visual", "categorical"]
    key: str           # e.g. "ctr_7d_slope"
    value: str | float # e.g. -0.18
    source: str        # e.g. "daily_perf.csv"

class Opinion(BaseModel):
    agent: str
    round: int                          # 1 = initial, 3 = revised
    verdict: Literal["SCALE", "PAUSE", "PIVOT", "TEST_NEXT"]
    confidence: float                   # 0.0 to 1.0
    claims: list[str]                   # plain English, max 3
    evidence: list[Evidence]
    changed_from: Optional[str] = None  # set if verdict changed in R3

class Message(BaseModel):
    id: str
    from_agent: str
    to_agent: str   # agent name or "ALL"
    type: Literal["challenge", "evidence_request", "concur", "revision"]
    in_reply_to: Optional[str] = None
    body: str       # plain English, max 2 sentences
    timestamp: datetime

class Task(BaseModel):
    task_id: str
    creative_id: str
    campaign_id: str
    context: dict   # the full row from creative_features.parquet as a dict
    image_path: str # absolute path to the creative image file
```

### 6.3 Agent Endpoints
Every agent exposes exactly two POST endpoints:

- `POST /opinion` — called in Round 1 (initial opinion) and Round 3 (revised opinion)
- `POST /respond` — called in Round 2 (cross-examination)

The orchestrator never calls agents directly from business logic — it only calls `/opinion` and `/respond`. Agents never call each other directly. All communication goes through the orchestrator.

---

## 7. Debate Protocol — The 4 Rounds

This is the core of the system. Understand this before writing any agent code.

### Round 1 — Independent Opinions (parallel, ~3s)
The orchestrator sends the same `Task` to all 5 agents simultaneously via `asyncio.gather`. Each agent independently analyzes the creative and returns an `Opinion`. **Agents cannot see each other's opinions in Round 1.** This guarantees independent reasoning — not groupthink.

### Round 2 — Cross-Examination (parallel, ~5s)
Each agent receives all 5 Round 1 opinions and may emit up to 2 `Message` objects:
- `challenge` — "You said X but my evidence shows Y. Explain."
- `evidence_request` — "Your claim is unsupported. What grounds it?"
- `concur` — "I agree with your point on Z."
- Silence is also valid if no challenge is warranted.

Agents must be willing to challenge. Prompts must explicitly instruct this. A debate with zero challenges is a system failure.

### Round 3 — Revision (parallel, ~3s)
Only agents that received a `challenge` or `evidence_request` in Round 2 are called. Each must respond with either:
- A revised `Opinion` (with `changed_from` set to the original verdict) — this is the hero moment
- A defended `Opinion` (same verdict, confidence unchanged, with a rebuttal in claims)

Agents that were not challenged keep their Round 1 opinion unchanged.

### Round 4 — Synthesis
The orchestrator collects all final opinions (R3 revisions where they exist, R1 opinions otherwise), runs weighted voting, and calls the synthesizer.

---

## 8. Weighted Voting & Verdict Rules

### Vote weights by agent
| Agent | Weight |
|---|---|
| Performance Analyst | 1.0 |
| Fatigue Detective | 1.0 |
| Risk Officer | 0.8 |
| Visual Critic | 0.7 |
| Audience Simulator | 0.5 |

### Scoring formula
```python
from collections import defaultdict

def compute_weighted_vote(final_opinions: list[Opinion], agent_weights: dict) -> str:
    scores = defaultdict(float)
    for op in final_opinions:
        weight = agent_weights.get(op.agent, 0.5)
        scores[op.verdict] += weight * op.confidence
    return max(scores, key=scores.get)
```

### Safety overrides (applied after voting, before synthesizer)
These rules are deterministic Python — not LLM decisions:

```python
def apply_safety_overrides(verdict: str, context: dict, final_opinions: list[Opinion]) -> str:
    # Not enough data to recommend scaling
    if context.get('installs', 0) < 50 and verdict == 'SCALE':
        return 'TEST_NEXT'

    # Fatigue agent with high confidence cannot be overridden to SCALE
    fatigue_op = next((o for o in final_opinions if o.agent == 'fatigue_detective'), None)
    if fatigue_op and fatigue_op.verdict == 'PAUSE' and fatigue_op.confidence > 0.8:
        if verdict == 'SCALE':
            return 'PAUSE'

    # High risk exposure limits options
    risk_op = next((o for o in final_opinions if o.agent == 'risk_officer'), None)
    if risk_op and risk_op.confidence > 0.7 and risk_op.verdict in ('PAUSE', 'PIVOT'):
        if verdict == 'SCALE':
            return 'PIVOT'

    return verdict
```

---

## 9. The Five Agents

### 9.1 Performance Analyst
**Purpose:** Quantifies how this creative performs relative to campaign peers on hard metrics.

**Inputs:** `context` dict from `creative_features.parquet` (all columns)

**LLM:** `claude-haiku-4-5` — data narration only, no vision needed

**Key fields it uses:** `ctr`, `ctr_pct`, `ipm`, `ipm_pct`, `cvr`, `spend`, `spend_pct`, `impressions`

**Expected behavior:** Votes SCALE if top-quartile on 2+ KPIs, PAUSE if bottom-quartile, PIVOT if high-spend but poor efficiency, TEST_NEXT if low impressions.

**Port:** 8001

---

### 9.2 Fatigue Detective
**Purpose:** Detects whether the creative is losing effectiveness over time.

**Inputs:** `context` dict — specifically `ctr_slope_7d`, `creative_age_days`, `active_days`

**LLM:** `claude-haiku-4-5`

**Key logic (computed in Python before the LLM call):**
- `ctr_slope_7d` < -0.10 → strong fatigue signal
- `creative_age_days` > 30 and `ctr_pct` < 0.4 → likely fatigued
- Recent impressions > 2× earlier average → frequency saturation risk

**Expected behavior:** Votes PAUSE if strong fatigue, PIVOT if moderate, TEST_NEXT if too early to tell.

**Port:** 8002

---

### 9.3 Risk Officer
**Purpose:** Evaluates financial exposure and statistical confidence.

**Inputs:** `context` dict — `spend`, `spend_pct`, `installs`, `impressions`, `cpi`

**LLM:** `claude-haiku-4-5`

**Key logic (computed in Python):**
```python
from scipy.stats import proportion_confint
ci_low, ci_high = proportion_confint(
    count=row['installs'], nobs=row['impressions'], alpha=0.05, method='wilson'
)
confidence_width = ci_high - ci_low  # wide = unreliable
```

**Expected behavior:** High spend + wide confidence interval → PIVOT (risky). Low spend + strong signal → SCALE. High spend + poor metrics → PAUSE.

**Port:** 8003

---

### 9.4 Visual Critic
**Purpose:** Analyzes the creative asset itself for visual quality, CTA clarity, and format fit.

**Inputs:** `image_path` from the Task + `context` dict for campaign vertical

**LLM:** `claude-sonnet-4-7` with vision

**Image handling:**
```python
import base64
from pathlib import Path

def load_image_b64(image_path: str) -> str:
    return base64.b64encode(Path(image_path).read_bytes()).decode()
```

**Response cache:** After the first vision call for a creative, save the structured visual analysis to `evidence.db`. On Round 3 revision, read from cache — do not call the vision API twice for the same image.

**What it analyzes:** CTA presence and clarity · dominant subject · text legibility · color contrast · brand consistency · format appropriateness for vertical

**Port:** 8004

---

### 9.5 Audience Simulator
**Purpose:** Simulates how a realistic target audience member would react to the creative.

**Inputs:** `image_path` + `context` dict (especially `vertical`, `country`, `os`)

**LLM:** `claude-sonnet-4-7` with vision

**Persona construction:** Built from campaign metadata:
```python
persona = f"""
You are a mobile user in {context['country']} using {context['os']}.
You engage with {context['vertical']} apps. You are scrolling a social feed.
"""
```

**Grounding rule (critical):** Every reaction the Audience Simulator claims MUST be grounded in either (a) a specific visual element it can describe, or (b) a documented property of the target audience from the metadata. The prompt must enforce this. If it cannot ground a reaction, it must omit it.

**Vote weight is lowest (0.5)** precisely because it is the most subjective agent. If another agent sends an `evidence_request` to Audience Simulator and it cannot respond with grounding, its vote is excluded from that round's calculation.

**Port:** 8005

---

## 10. Orchestrator & Shared Scaffolding

### 10.1 `agents/base.py`
Every agent imports from this file. It provides the FastAPI app factory:

```python
from fastapi import FastAPI
from orchestrator.a2a import AgentCard, Task, Opinion, Message

def make_agent(
    card: AgentCard,
    opinion_fn,   # async (task: Task, prior_messages: list[Message]) -> Opinion
    respond_fn,   # async (task: Task, opinions: list[Opinion]) -> list[Message]
) -> FastAPI:
    app = FastAPI()

    @app.get("/.well-known/agent.json")
    def get_card():
        return card

    @app.post("/opinion")
    async def opinion(task: Task, prior_messages: list[Message] = []) -> Opinion:
        return await opinion_fn(task, prior_messages)

    @app.post("/respond")
    async def respond(task: Task, opinions: list[Opinion]) -> list[Message]:
        return await respond_fn(task, opinions)

    return app
```

### 10.2 `orchestrator/debate.py`
The full round logic. Uses `asyncio.gather` for parallelism:

```python
import asyncio, httpx, uuid
from orchestrator.a2a import Task, Opinion, Message

AGENT_ENDPOINTS = [
    "http://localhost:8001",  # performance
    "http://localhost:8002",  # fatigue
    "http://localhost:8003",  # risk
    "http://localhost:8004",  # visual
    "http://localhost:8005",  # audience
]

async def run_debate(task: Task) -> dict:
    transcript = []

    async with httpx.AsyncClient(timeout=45) as client:

        # Round 1 — parallel independent opinions
        r1_responses = await asyncio.gather(*[
            client.post(f"{ep}/opinion", json=task.model_dump(), timeout=30)
            for ep in AGENT_ENDPOINTS
        ], return_exceptions=True)
        opinions_r1 = [Opinion(**r.json()) for r in r1_responses if not isinstance(r, Exception)]
        transcript.append({"round": 1, "type": "opinions", "data": [o.model_dump() for o in opinions_r1]})

        # Round 2 — cross-examination
        r2_responses = await asyncio.gather(*[
            client.post(f"{ep}/respond",
                json={"task": task.model_dump(), "opinions": [o.model_dump() for o in opinions_r1]})
            for ep in AGENT_ENDPOINTS
        ], return_exceptions=True)
        challenges = [
            Message(**m)
            for r in r2_responses if not isinstance(r, Exception)
            for m in r.json()
        ]
        transcript.append({"round": 2, "type": "challenges", "data": [m.model_dump() for m in challenges]})

        # Round 3 — only challenged agents revise
        challenged_agents = {m.to_agent for m in challenges if m.type in ("challenge", "evidence_request")}
        agent_opinions = {o.agent: (o, ep) for o, ep in zip(opinions_r1, AGENT_ENDPOINTS)}

        r3_calls = []
        for agent_name in challenged_agents:
            if agent_name not in agent_opinions:
                continue
            _, ep = agent_opinions[agent_name]
            my_challenges = [m for m in challenges if m.to_agent == agent_name]
            r3_calls.append(
                client.post(f"{ep}/opinion",
                    json={"task": task.model_dump(), "prior_messages": [m.model_dump() for m in my_challenges]})
            )

        r3_responses = await asyncio.gather(*r3_calls, return_exceptions=True)
        revisions = [Opinion(**r.json()) for r in r3_responses if not isinstance(r, Exception)]
        transcript.append({"round": 3, "type": "revisions", "data": [o.model_dump() for o in revisions]})

    # Merge: revised opinion overrides Round 1
    final_by_agent = {o.agent: o for o in opinions_r1}
    for o in revisions:
        o.changed_from = final_by_agent[o.agent].verdict if o.verdict != final_by_agent[o.agent].verdict else None
        final_by_agent[o.agent] = o

    return {
        "transcript": transcript,
        "final_opinions": [o.model_dump() for o in final_by_agent.values()],
    }
```

### 10.3 Evidence Store (`orchestrator/evidence_store.py`)
SQLite helpers. All agents and the orchestrator write here:

```python
import sqlite3, json
from datetime import datetime

DB_PATH = "evidence.db"

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS debate_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        debate_id TEXT, creative_id TEXT, round INTEGER,
        type TEXT, agent TEXT, payload TEXT, ts TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS vision_cache (
        creative_id TEXT PRIMARY KEY,
        analysis TEXT, ts TEXT
    )""")
    con.commit()

def log_event(debate_id, creative_id, round_, type_, agent, payload):
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT INTO debate_log VALUES (NULL,?,?,?,?,?,?,?)",
        (debate_id, creative_id, round_, type_, agent, json.dumps(payload), datetime.utcnow().isoformat()))
    con.commit()

def get_vision_cache(creative_id: str) -> dict | None:
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT analysis FROM vision_cache WHERE creative_id=?", (creative_id,)).fetchone()
    return json.loads(row[0]) if row else None

def set_vision_cache(creative_id: str, analysis: dict):
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT OR REPLACE INTO vision_cache VALUES (?,?,?)",
        (creative_id, json.dumps(analysis), datetime.utcnow().isoformat()))
    con.commit()
```

---

## 11. Data Pipeline Details (Person A's Deliverable)

The output of the pipeline is `pipeline/creative_features.parquet`. This file is the single input for all agents via `task.context`. Its schema must be documented in `SCHEMA.md` after Person A runs the exploration.

### Required columns in `creative_features.parquet`

| Column | Type | Description |
|---|---|---|
| `creative_id` | str | Primary key |
| `campaign_id` | str | Foreign key |
| `format` | str | e.g. "video", "banner", "interstitial" |
| `impressions` | int | Lifetime total |
| `clicks` | int | Lifetime total |
| `installs` | int | Lifetime total |
| `spend` | float | Lifetime USD |
| `ctr` | float | clicks / impressions |
| `cvr` | float | installs / clicks |
| `ipm` | float | installs per 1000 impressions |
| `cpi` | float | spend / installs |
| `ctr_slope_7d` | float | Linear regression slope of daily CTR over last 7 days |
| `creative_age_days` | int | Days since first impression |
| `active_days` | int | Number of distinct days with impressions |
| `first_date` | date | First impression date |
| `last_date` | date | Most recent impression date |
| `ctr_pct` | float | Percentile rank within campaign (0–1) |
| `ipm_pct` | float | Percentile rank within campaign (0–1) |
| `spend_pct` | float | Percentile rank within campaign (0–1) |
| `cvr_pct` | float | Percentile rank within campaign (0–1) |
| `image_path` | str | Absolute path to the image file |

Additional columns from creatives.csv (format, dimensions, duration if video) should be included verbatim.

### Campaign selection criteria
```python
# In build_table.py, use this to pick the campaign
campaign_stats = daily_perf.groupby('campaign_id').agg(
    n_creatives=('creative_id', 'nunique'),
    n_days=('date', 'nunique'),
    total_spend=('spend', 'sum'),
)
# Pick campaign with: n_creatives >= 10, n_days >= 30, highest total_spend
```
Hardcode the chosen `campaign_id` in `.env` as `CAMPAIGN_ID=...`.

### Discovering the two important columns
```python
# In discover_features.py
import pandas as pd
df = pd.read_parquet('pipeline/creative_features.parquet')
target = 'ipm'

# Numerical correlations
num_corr = df.select_dtypes('number').corrwith(df[target]).abs().sort_values(ascending=False)
print("Top numerical predictors:\n", num_corr.head(10))

# Categorical variance
for col in df.select_dtypes('object').columns:
    if col in ('creative_id', 'campaign_id', 'image_path'):
        continue
    variance = df.groupby(col)[target].mean().std()
    print(f"{col}: {variance:.4f}")
```
The two columns at the top of both lists are the discovery. **Share results with the whole team and add them to SCHEMA.md.**

---

## 12. Prompt Engineering Guidelines

All prompts live as `.txt` files in `agents/prompts/`. They are loaded at agent startup. Follow these rules when writing prompts:

### Output format
Every agent prompt must end with an instruction to return JSON only, matching the `Opinion` schema. Use this closing block:

```
Respond ONLY with valid JSON. No explanation, no markdown, no preamble.
The JSON must match this exact schema:
{
  "agent": "<your agent name>",
  "round": <1 or 3>,
  "verdict": "<SCALE|PAUSE|PIVOT|TEST_NEXT>",
  "confidence": <0.0 to 1.0>,
  "claims": ["<plain English claim 1>", "<plain English claim 2>"],
  "evidence": [
    {"type": "<metric|visual|categorical>", "key": "<field name>", "value": "<value>", "source": "<source>"}
  ]
}
```

### Challenge willingness
The `respond.txt` prompt (used by all agents in Round 2) must include:

```
A debate where all agents agree is a failure — it means no new information was produced.
If you have ANY doubt about another agent's claim, challenge it.
Silence is only acceptable if you genuinely have no evidence that contradicts or questions their claims.
```

### Audience Simulator grounding rule
The `audience.txt` prompt must include:

```
IMPORTANT: Every reaction you describe must be grounded in ONE of:
  (a) A specific visual element you can observe in the image (describe it exactly)
  (b) A documented property of your target audience from the campaign metadata
If you cannot ground a reaction, do not include it.
Speculative reactions without grounding will invalidate your vote.
```

### Synthesizer prompt structure
The `synthesizer.txt` receives the full transcript and must produce:

```json
{
  "verdict": "SCALE|PAUSE|PIVOT|TEST_NEXT",
  "headline": "One sentence explaining the verdict for a marketer",
  "evidence_bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
  "dissent": "One sentence describing the strongest opposing view, or null",
  "next_action": "One concrete recommendation — what to do tomorrow"
}
```

---

## 13. Running the System Locally

### Environment setup
```bash
# .env.example — copy to .env and fill in values
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...          # optional, only if using GPT-4o
CAMPAIGN_ID=your_campaign_id
DATA_DIR=./data
IMAGES_DIR=./data/images
```

### Starting all services
```bash
# Terminal 1 — Performance agent
uvicorn agents.performance:app --port 8001

# Terminal 2 — Fatigue agent
uvicorn agents.fatigue:app --port 8002

# Terminal 3 — Risk agent
uvicorn agents.risk:app --port 8003

# Terminal 4 — Visual agent
uvicorn agents.visual:app --port 8004

# Terminal 5 — Audience agent
uvicorn agents.audience:app --port 8005

# Terminal 6 — Orchestrator
uvicorn orchestrator.server:app --port 8000

# Terminal 7 — Frontend
streamlit run frontend/app.py
```

### Testing a single agent
```bash
curl -X POST http://localhost:8001/opinion \
  -H "Content-Type: application/json" \
  -d '{"task_id":"test","creative_id":"c001","campaign_id":"camp1","context":{...},"image_path":"./data/images/c001.jpg"}'
```

### Running a full debate
```bash
curl -X POST http://localhost:8000/debate \
  -H "Content-Type: application/json" \
  -d '{"creative_id":"c001"}'
```

---

## 14. Frontend Requirements (Streamlit)

The frontend is a single `frontend/app.py`. It must show:

### Left panel
- Dropdown to select a creative from the campaign
- Creative image display
- Key metrics: CTR, IPM, CVR, spend — each with percentile rank as delta
- "Convene the Boardroom" button (primary, triggers the debate)

### Right panel — shown after debate completes
- **Verdict card:** large verdict label (SCALE/PAUSE/PIVOT/TEST_NEXT), confidence percentage, headline sentence
- **Evidence bullets:** 3 bullets from the synthesizer
- **Dissent callout:** shown only if non-null (use `st.warning`)
- **Next action:** shown as `st.info`
- **Transcript expander:** full list of messages by round, agent name bold, Round 2 challenges in amber, Round 3 revisions with a "⚡ Changed verdict" badge

### Hero moment
In the transcript, any `Opinion` where `changed_from` is not null must be displayed prominently:
```python
if opinion.get('changed_from'):
    st.success(f"⚡ {opinion['agent']} changed verdict: {opinion['changed_from']} → {opinion['verdict']}")
```
This is the single most important UI moment in the demo. Never hide it.

---

## 15. Work Division Summary

| Person | Primary ownership | Key deliverable |
|---|---|---|
| **A — Data Lead** | `pipeline/` folder | `SCHEMA.md` within 2 hours · `creative_features.parquet` · two important columns identified |
| **B — Protocol Lead** | `orchestrator/` folder | Pydantic schemas · debate round logic · stub agents running end-to-end |
| **C — Agents Lead** | `agents/` and `synthesizer/` | All 5 real agents · all prompts · synthesizer |
| **D — Frontend Lead** | `frontend/` folder | Complete Streamlit app · demo script · fallback recording |

---

### The only real dependency

**Person A must publish `SCHEMA.md` within the first 2 hours.** This is the single blocking dependency in the entire project. It does not require the parquet file to be finished — only the column names, types, and join keys to be documented. After `SCHEMA.md` exists, no one is blocked by anyone else again.

Everything else below runs in parallel from minute zero.

---

### Parallel timeline

```
HOUR    0    1    2    3    4    5    6    7    8    9   10   11   12
         |    |    |    |    |    |    |    |    |    |    |    |    |

A    [explore CSVs · pick campaign]──[SCHEMA.md]──[build parquet · discover columns]──[support C/B]

B    [a2a.py schemas · base.py]──────────────────[debate.py · stub agents · end-to-end run]──[wire real agents · error handling]

C    [agent file structure · FastAPI shells · prompt templates]──────[Performance · Fatigue · Risk agents]──[Visual · Audience · Synthesizer]

D    [Streamlit shell · creative picker · layout]──────────────────[verdict card · transcript view]──[hero moment · polish · fallback recording]

ALL                                                                                        [INTEGRATION]──[dry run · demo prep]
```

---

### What each person does before `SCHEMA.md` exists (hour 0–2)

The key insight is that **none of B, C, or D need real data to start**. They need the schema — the column names — not the data itself. And they can build everything around placeholder names in the meantime.

**Person B** writes all pydantic models in `a2a.py` (`Task`, `Opinion`, `Message`, `AgentCard`, `Evidence`), the `base.py` FastAPI scaffold, and the 3-round `debate.py` logic. None of this touches data at all. These are pure protocol definitions.

**Person C** creates every agent file, wires the FastAPI app using `base.py`, and writes all prompt templates using placeholder column references like `{ctr}`, `{ipm_pct}`, `{creative_age_days}`. When `SCHEMA.md` arrives, C fills in the real names in under 10 minutes. The LLM call wrappers, JSON parsing, and error handling are all written before the schema is needed.

**Person D** builds the complete Streamlit layout — left panel with image display and metric cards, right panel with verdict card and transcript view. All of this is static UI that needs zero data. D can even hardcode one fake verdict result as a placeholder to get the visual design right.

---

### Sync points (the only 2 moments the team needs to coordinate)

**Sync 1 — Hour 2:** Person A posts `SCHEMA.md` to the repo. Everyone pulls. C fills in real column names in prompts. B updates the `Task.context` field description. This takes each person under 10 minutes.

**Sync 2 — Hour 10:** Full integration. B's real debate logic + C's real agents + D's live UI all run together for the first time. Budget 2 hours for this — fix wiring issues, find the hero creative, do a full dry run.

---

### Integration checklist (Hour 10–12)

Work through this list as a team before the demo:

- [ ] All 5 agents return valid `Opinion` JSON for a known creative
- [ ] At least one `challenge` message appears in Round 2
- [ ] At least one agent has `changed_from` set in Round 3
- [ ] Synthesizer produces valid verdict card JSON
- [ ] Streamlit displays the hero moment badge correctly
- [ ] Full debate completes in under 30 seconds
- [ ] Fallback cached result saved to disk for the hero creative
- [ ] Demo script rehearsed at least once end-to-end

---

## 16. Demo Script

The live demo should follow this sequence and take no more than 4 minutes:

1. **(30s)** State the problem — "Marketers run hundreds of creatives and can't explain why one wins over another."
2. **(30s)** Introduce the metaphor — "We built a boardroom of expert agents that debate using Google's A2A protocol."
3. **(90s)** Live demo — select the hero creative, click Convene, watch the transcript stream, highlight the moment an agent changes its mind.
4. **(45s)** Architecture slide — emphasize: independent opinions → genuine challenges → revised verdicts → weighted consensus. This is not a pipeline.
5. **(30s)** Scalability — "Today one campaign. Tomorrow: same agents, precomputed tables for every campaign, plug in new agents via agent discovery."
6. Q&A

**Always have a pre-cached result for the hero creative** as a fallback. If the live API call fails, load the saved result from disk. Never demo without a backup.

---

## 17. Scaling Story (for the Pitch)

When asked how this scales beyond one campaign, the answer is:

- **Data layer:** `build_table.py` runs nightly for every campaign. Each campaign gets its own parquet file. The agents are stateless — they read whichever file the orchestrator passes.
- **Agent layer:** Each agent is an independent HTTP service. Scaling means running more instances behind a load balancer. Adding a new agent type (e.g., a "Brand Safety Agent") means deploying a new FastAPI service with an agent card — the orchestrator discovers it automatically. No code changes to any existing agent.
- **Cost control:** Low-spend creatives use a "fast path" (3 agents, 1 round). High-spend or flagged creatives get the full boardroom. The threshold is a config variable.
- **Why A2A specifically enables this:** In a sequential pipeline, adding a new analytical dimension requires changing every downstream step. In our system, new agents plug in via discovery. This is the architectural claim that differentiates us.

---

## 18. Risks and Fallbacks

| Risk | Mitigation |
|---|---|
| Vision API latency causes timeout | Cache vision responses in SQLite after first call; set `timeout=45` in httpx |
| Agent returns malformed JSON | Wrap all LLM output parsing in try/except; return a default "TEST_NEXT, confidence 0.3" opinion on failure |
| No mind-change in R1→R3 for demo | Run debate on all creatives beforehand; pick the hero creative that produces the most interesting trajectory |
| Streamlit too slow for live streaming | Pre-compute and cache full debate result; load from disk in the demo |
| Vision LLM unavailable | Visual Critic falls back to metadata only: format, duration, dimensions, filename-derived features |
| Only 3 agents built by demo time | Drop Visual Critic and Audience Simulator; 3 data-only agents still produce a real debate |
| A2A library confusion | We implement A2A shapes directly via pydantic + FastAPI. No external A2A library needed. |
