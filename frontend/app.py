"""
Creative Boardroom - Streamlit frontend.

Usage:
    streamlit run frontend/app.py

Requires the orchestrator to be running at http://localhost:8000.
"""
from __future__ import annotations

import base64
import html
import math
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import requests
import streamlit as st
from PIL import Image


ORCHESTRATOR = "http://localhost:8000"

SCREENS = [
    "Campaign Overview",
    "Creative Analytics",
    "Creative Boardroom",
]

VERDICT_COLORS = {
    "SCALE": "#2ef2a0",
    "PAUSE": "#ff5b7a",
    "PIVOT": "#ffb020",
    "TEST_NEXT": "#8b7cff",
}

STATUS_META = {
    "top_performer": ("Top Performer", "status-top"),
    "fatigued": ("Fatigued", "status-fatigued"),
    "stable": ("Stable", "status-stable"),
    "underperformer": ("Underperformer", "status-underperformer"),
}

AGENT_META = {
    "performance_analyst": ("Performance Analyst", "#2ef2a0"),
    "fatigue_detective": ("Fatigue Detective", "#ffb020"),
    "visual_critic": ("Visual Critic", "#4dd8ff"),
    "risk_officer": ("Risk Officer", "#ff5b7a"),
    "audience_simulator": ("Audience Simulator", "#b98cff"),
}

ROUND_CONTEXT = {
    "task": (
        "Shared briefing sent to every agent before anyone votes. "
        "This is context, not a recommendation yet."
    ),
    "opinions": (
        "Each agent gives a first independent recommendation. "
        "At this point they have not seen the other agents' arguments."
    ),
    "challenges": (
        "Agents challenge weak claims, ask for evidence, or flag contradictions. "
        "This is where disagreements become visible."
    ),
    "revisions": (
        "Only challenged agents answer back. A changed verdict means another agent's "
        "evidence was strong enough to move their position."
    ),
    "consensus": (
        "The orchestrator combines the final agent votes using confidence and agent weights. "
        "The agents do not choose the final verdict themselves."
    ),
    "agent_errors": (
        "Some agents failed during the debate. The orchestrator uses a conservative "
        "TEST_NEXT fallback so the demo still returns a safe recommendation."
    ),
}

METRIC_LABELS = {
    "active_days": "Active days",
    "advertiser_name": "Advertiser",
    "app_name": "App",
    "campaign_id": "Campaign ID",
    "clicks": "Clicks",
    "countries": "Countries",
    "creative_id": "Creative ID",
    "creative_status": "Creative status",
    "ctr": "Click-through rate",
    "ctr_decay_pct": "CTR decay",
    "ctr_pct": "CTR percentile",
    "cvr": "Conversion rate",
    "cvr_pct": "CVR percentile",
    "emotional_tone": "Emotional tone",
    "fatigue_day": "Fatigue day",
    "first_7d_ctr": "First 7 days CTR",
    "format": "Format",
    "impressions": "Impressions",
    "installs": "Installs",
    "ipm": "Installs per 1K impressions",
    "ipm_pct": "IPM percentile",
    "kpi_goal": "KPI goal",
    "language": "Language",
    "last_7d_ctr": "Last 7 days CTR",
    "objective": "Objective",
    "overall_roas": "ROAS",
    "primary_theme": "Primary theme",
    "roas": "ROAS",
    "spend": "Spend",
    "spend_pct": "Spend percentile",
    "target_age_segment": "Target age",
    "target_os": "Target OS",
    "theme": "Theme",
    "total_revenue_usd": "Revenue",
    "vertical": "Vertical",
}

VERDICT_MEANINGS = {
    "SCALE": "Increase budget carefully because the signals are strong enough.",
    "PAUSE": "Stop or reduce spend because performance, fatigue, or risk is too concerning.",
    "PIVOT": "Keep the learning but change the creative angle before spending more.",
    "TEST_NEXT": "Run another controlled test before making a bigger spend decision.",
}

BOARDROOM_ROUNDS = [
    {
        "number": 1,
        "title": "Independent Opinions",
        "short": "Agents vote alone.",
        "detail": (
            "Each specialist reviews the same creative context and produces a first verdict "
            "without seeing anyone else's answer. This protects the first read from group bias."
        ),
        "accent": "#2ef2a0",
    },
    {
        "number": 2,
        "title": "Cross-Examination",
        "short": "Agents challenge weak claims.",
        "detail": (
            "Agents read the first opinions and ask targeted questions when a claim lacks evidence, "
            "conflicts with another metric, or ignores a risk signal."
        ),
        "accent": "#4dd8ff",
    },
    {
        "number": 3,
        "title": "Revisions",
        "short": "Challenged agents answer.",
        "detail": (
            "Only agents that received a challenge respond again. If the new evidence is stronger, "
            "an agent can change its verdict and the app highlights that change."
        ),
        "accent": "#ffb020",
    },
    {
        "number": 4,
        "title": "Weighted Consensus",
        "short": "The orchestrator decides.",
        "detail": (
            "The orchestrator combines final votes using confidence and configured agent weights. "
            "It can also block SCALE when data volume, fatigue, or brand risk makes scaling unsafe."
        ),
        "accent": "#b98cff",
    },
]

AGENT_NODE_KEYS = {
    "orchestrator": "orchestrator",
    "performance_analyst": "performance",
    "fatigue_detective": "fatigue",
    "visual_critic": "visual",
    "risk_officer": "risk",
    "audience_simulator": "audience",
}

LINE_KEYS = ("performance", "fatigue", "visual", "risk", "audience")

DEMO_CREATIVES = [
    {
        "creative_id": "500282",
        "campaign_id": "20047",
        "format": "rewarded_video",
        "creative_status": "stable",
        "theme": "drama",
        "emotional_tone": "urgent",
        "language": "fr",
        "spend": 62831.03,
        "impressions": 10114911,
        "clicks": 37169,
        "installs": 3739,
        "ctr": 0.003675,
        "cvr": 0.1006,
        "ipm": 0.3697,
        "overall_roas": 1.33,
        "ctr_pct": 0.83,
        "ipm_pct": 1.0,
        "spend_pct": 0.50,
        "cvr_pct": 0.83,
        "first_7d_ctr": 0.0089,
        "last_7d_ctr": 0.0019,
        "ctr_decay_pct": -0.79,
        "active_days": 54,
        "image_path": "",
    },
    {
        "creative_id": "500283",
        "campaign_id": "20047",
        "format": "native",
        "creative_status": "underperformer",
        "theme": "trailer",
        "emotional_tone": "urgent",
        "language": "fr",
        "spend": 67264.71,
        "impressions": 16596258,
        "clicks": 51170,
        "installs": 5192,
        "ctr": 0.003083,
        "cvr": 0.1015,
        "ipm": 0.3128,
        "overall_roas": 1.70,
        "ctr_pct": 0.33,
        "ipm_pct": 0.67,
        "spend_pct": 0.83,
        "cvr_pct": 1.0,
        "first_7d_ctr": 0.0076,
        "last_7d_ctr": 0.0018,
        "ctr_decay_pct": -0.76,
        "active_days": 54,
        "image_path": "",
    },
    {
        "creative_id": "500284",
        "campaign_id": "20047",
        "format": "native",
        "creative_status": "underperformer",
        "theme": "celebrity",
        "emotional_tone": "calm",
        "language": "es",
        "spend": 100310.13,
        "impressions": 24786647,
        "clicks": 63591,
        "installs": 6058,
        "ctr": 0.002566,
        "cvr": 0.0953,
        "ipm": 0.2444,
        "overall_roas": 1.35,
        "ctr_pct": 0.17,
        "ipm_pct": 0.17,
        "spend_pct": 1.0,
        "cvr_pct": 0.67,
        "first_7d_ctr": 0.0037,
        "last_7d_ctr": 0.0019,
        "ctr_decay_pct": -0.49,
        "active_days": 59,
        "image_path": "",
    },
    {
        "creative_id": "500285",
        "campaign_id": "20047",
        "format": "interstitial",
        "creative_status": "underperformer",
        "theme": "feature-focus",
        "emotional_tone": "adventurous",
        "language": "es",
        "spend": 46055.44,
        "impressions": 9163034,
        "clicks": 33802,
        "installs": 3035,
        "ctr": 0.003689,
        "cvr": 0.0898,
        "ipm": 0.3312,
        "overall_roas": 1.46,
        "ctr_pct": 1.0,
        "ipm_pct": 0.83,
        "spend_pct": 0.17,
        "cvr_pct": 0.33,
        "first_7d_ctr": 0.0088,
        "last_7d_ctr": 0.0018,
        "ctr_decay_pct": -0.79,
        "active_days": 44,
        "image_path": "",
    },
    {
        "creative_id": "500286",
        "campaign_id": "20047",
        "format": "native",
        "creative_status": "underperformer",
        "theme": "trailer",
        "emotional_tone": "adventurous",
        "language": "fr",
        "spend": 62842.36,
        "impressions": 15558619,
        "clicks": 48139,
        "installs": 4475,
        "ctr": 0.003094,
        "cvr": 0.0930,
        "ipm": 0.2876,
        "overall_roas": 1.60,
        "ctr_pct": 0.50,
        "ipm_pct": 0.33,
        "spend_pct": 0.67,
        "cvr_pct": 0.50,
        "first_7d_ctr": 0.0073,
        "last_7d_ctr": 0.0018,
        "ctr_decay_pct": -0.76,
        "active_days": 54,
        "image_path": "",
    },
    {
        "creative_id": "500287",
        "campaign_id": "20047",
        "format": "interstitial",
        "creative_status": "stable",
        "theme": "drama",
        "emotional_tone": "premium",
        "language": "es",
        "spend": 55464.00,
        "impressions": 13200000,
        "clicks": 43000,
        "installs": 4200,
        "ctr": 0.003258,
        "cvr": 0.0977,
        "ipm": 0.3182,
        "overall_roas": 1.55,
        "ctr_pct": 0.67,
        "ipm_pct": 0.50,
        "spend_pct": 0.33,
        "cvr_pct": 0.67,
        "first_7d_ctr": 0.0068,
        "last_7d_ctr": 0.0020,
        "ctr_decay_pct": -0.70,
        "active_days": 48,
        "image_path": "",
    },
]


st.set_page_config(
    page_title="Creative Boardroom",
    page_icon="CB",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def inject_css() -> None:
    try:
        base_css = Path("colors_and_type.css").read_text()
    except Exception:
        base_css = ""

    st.markdown(
        "<style>\n" + base_css + """
/* =========================================================================
   Streamlit / App-specific structural overrides
   ========================================================================= */
.stApp {
  background: var(--bg);
  background-image: var(--bg-app);
  color: var(--text);
}

div[data-testid="stToolbar"],
header[data-testid="stHeader"] {
  display: none;
  visibility: hidden;
  height: 0;
}

.block-container {
  width: 100%;
  max-width: none;
  padding: clamp(0.65rem, 1.2vw, 1.25rem) clamp(0.75rem, 2vw, 2.2rem) 2.4rem;
  padding-bottom: 3rem;
}

.hero-shell {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 28px;
  padding: clamp(22px, 2vw, 30px);
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.78), rgba(2, 6, 23, 0.40)),
    linear-gradient(90deg, rgba(77, 216, 255, 0.08), rgba(46, 242, 160, 0.05));
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(18px);
}

.eyebrow {
  color: var(--cyan);
  font-size: 0.82rem;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  font-weight: 800;
}

.hero-title {
  margin: 0.35rem 0 0.35rem;
  font-size: clamp(2.2rem, 5vw, 4.8rem);
  line-height: 0.92;
  font-weight: 800;
  letter-spacing: 0;
  background: linear-gradient(135deg, #4dd8ff 0%, #2ef2a0 50%, #b98cff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  color: transparent;
}

.hero-copy {
  color: #b8c5d8;
  font-size: 1.05rem;
  max-width: 850px;
}

.glass-card {
  border: 1px solid var(--border);
  border-radius: 22px;
  padding: 20px;
  background: var(--panel);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 18px 50px rgba(0,0,0,0.28);
  backdrop-filter: blur(16px);
}

.metric-card {
  min-height: 138px;
  border-radius: 22px;
  padding: 20px;
  border: 1px solid rgba(148, 163, 184, 0.20);
  background:
    linear-gradient(180deg, rgba(30, 41, 59, 0.78), rgba(15, 23, 42, 0.68));
  box-shadow: 0 20px 60px rgba(0,0,0,0.24);
  transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
}

.metric-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 24px 64px rgba(0,0,0,0.35), 0 0 40px var(--cyan)22;
  border-color: rgba(77, 216, 255, 0.4);
}

.metric-label {
  color: var(--muted);
  font-size: 0.82rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 700;
}

.metric-value {
  margin-top: 12px;
  font-size: 2rem;
  line-height: 1;
  font-weight: 800;
  color: var(--text);
}

.metric-context {
  margin-top: 10px;
  color: #9fb1c8;
  font-size: 0.9rem;
}

.creative-card {
  border: 1px solid rgba(148, 163, 184, 0.20);
  border-radius: 24px;
  padding: 14px;
  margin-bottom: 18px;
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.86), rgba(2, 6, 23, 0.70));
  box-shadow: 0 20px 60px rgba(0,0,0,0.30);
  transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
}

.creative-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 28px 70px rgba(0,0,0,0.40);
  border-color: rgba(148, 163, 184, 0.40);
}

.creative-image {
  width: 100%;
  aspect-ratio: 1 / 1;
  border-radius: 18px;
  object-fit: cover;
  background:
    linear-gradient(135deg, rgba(77, 216, 255, 0.22), rgba(185, 140, 255, 0.15)),
    repeating-linear-gradient(45deg, rgba(255,255,255,0.05) 0 10px, transparent 10px 20px);
  border: 1px solid rgba(255,255,255,0.08);
}

.creative-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(229,237,248,0.72);
  font-weight: 700;
}

.boardroom-creative-card {
  width: 100%;
  max-width: 500px;
  margin: 0 auto 18px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 22px;
  padding: 16px;
  background: rgba(15, 23, 42, 0.72);
  box-shadow: 0 20px 60px rgba(0,0,0,0.24);
}

.boardroom-asset-frame {
  width: 100%;
  height: clamp(330px, 28vw, 500px);
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  background: rgba(2, 6, 23, 0.68);
  border: 1px solid rgba(255,255,255,0.08);
  overflow: hidden;
}

.boardroom-creative-img {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
}

.boardroom-asset-frame.creative-placeholder {
  color: rgba(229,237,248,0.72);
  font-weight: 700;
}

.compact-metric-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-top: 14px;
}

.compact-metric {
  border-radius: 14px;
  padding: 12px;
  background: rgba(2, 6, 23, 0.44);
  border: 1px solid rgba(148, 163, 184, 0.12);
}

.compact-metric .mini-value {
  font-size: 1rem;
}

.compact-verdict {
  margin-top: 18px;
  border-radius: 18px;
  padding: clamp(18px, 1.4vw, 24px);
  background: rgba(2, 6, 23, 0.52);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.compact-verdict-reasons {
  margin-top: 14px;
  color: #cbd5e1;
  font-size: 0.98rem;
  line-height: 1.48;
}

.compact-verdict-reasons ul {
  margin: 6px 0 0 18px;
  padding: 0;
}

.compact-verdict-reasons li {
  margin-bottom: 4px;
}

.compact-verdict-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: 999px;
  padding: 13px 18px;
  font-size: clamp(1.65rem, 2.6vw, 3.1rem);
  font-weight: 800;
  letter-spacing: 0.08em;
  border: 1px solid currentColor;
  box-shadow: 0 0 24px rgba(255, 255, 255, 0.06);
}

.control-panel {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 22px;
  padding: 16px;
  background: rgba(15, 23, 42, 0.66);
  margin-bottom: 12px;
}

.control-title {
  color: var(--text);
  font-size: 1.1rem;
  font-weight: 800;
}

.control-copy {
  color: #9fb1c8;
  font-size: 0.9rem;
  margin-top: 4px;
}

.creative-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}

.creative-id {
  font-size: 1.15rem;
  font-weight: 800;
}

.status-badge {
  display: inline-flex;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 0.76rem;
  font-weight: 800;
  border: 1px solid rgba(255,255,255,0.12);
}

.status-top { color: #04130d; background: linear-gradient(135deg, #2ef2a0, #b8ffd9); }
.status-fatigued { color: #190d02; background: linear-gradient(135deg, #ffb020, #ff5b7a); }
.status-stable { color: #03111a; background: linear-gradient(135deg, #4dd8ff, #a7f3ff); }
.status-underperformer { color: #e2e8f0; background: rgba(100, 116, 139, 0.42); }

.mini-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 14px;
}

.mini-metric {
  border-radius: 16px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.mini-label {
  color: var(--muted);
  font-size: 0.76rem;
}

.mini-value {
  color: var(--text);
  font-weight: 800;
  font-size: 1.05rem;
  margin-top: 4px;
}

.threshold-panel {
  border-left: 3px solid var(--cyan);
  background: rgba(77, 216, 255, 0.08);
  border-radius: 18px;
  padding: 16px 18px;
  color: #cfe9f6;
}

.reliability-bar {
  height: 8px;
  border-radius: 99px;
  overflow: hidden;
  background: rgba(148, 163, 184, 0.18);
  margin-top: 10px;
}

.reliability-fill {
  height: 100%;
  border-radius: 99px;
  background: linear-gradient(90deg, var(--orange), var(--green));
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.meta-tag {
  border: 1px solid rgba(148, 163, 184, 0.20);
  border-radius: 999px;
  padding: 7px 10px;
  color: #cbd5e1;
  background: rgba(15, 23, 42, 0.64);
  font-size: 0.86rem;
}

.boardroom-step {
  border-left: 3px solid var(--purple);
  padding: 8px 0 8px 14px;
  color: #cbd5e1;
}

.round-overview {
  margin-bottom: 12px;
}

.round-tile {
  min-height: 88px;
  border-radius: 18px;
  padding: 12px 14px;
  margin-bottom: 8px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.78), rgba(2, 6, 23, 0.58));
  transition: all 0.3s ease;
}

.round-tile-active {
  border-color: var(--cyan);
  box-shadow: 0 0 28px rgba(77, 216, 255, 0.22);
  transform: translateX(4px);
}

.round-number {
  color: var(--muted);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 800;
}

.round-title {
  color: var(--text);
  font-size: 1rem;
  line-height: 1.05;
  font-weight: 800;
  margin-top: 5px;
}

.round-short {
  color: #9fb1c8;
  font-size: 0.82rem;
  margin-top: 6px;
}

.round-detail {
  border-radius: 16px;
  padding: 12px 14px;
  margin: 2px 0 14px;
  color: #cfe9f6;
  background: rgba(77, 216, 255, 0.07);
  border: 1px solid rgba(77, 216, 255, 0.18);
}

.transcript-detail {
  border-radius: 22px;
  padding: 18px 20px;
  margin: 18px 0;
  border: 1px solid rgba(77, 216, 255, 0.18);
  background: rgba(2, 6, 23, 0.54);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
}

.transcript-detail-title {
  color: var(--text);
  font-size: 1.22rem;
  font-weight: 800;
  margin-bottom: 6px;
}

.loading-boardroom {
  position: relative;
  min-height: 560px;
  margin: 18px 0;
  border-radius: 26px;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background:
    radial-gradient(circle at 50% 46%, rgba(77, 216, 255, 0.12), transparent 32%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.88), rgba(2, 6, 23, 0.74));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 18px 50px rgba(0,0,0,0.30);
}

.loading-title {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 5;
  padding: 16px 20px;
  height: 126px;
  box-sizing: border-box;
  overflow: hidden;
  background: rgba(2, 6, 23, 0.72);
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  backdrop-filter: blur(12px);
}

.loading-title strong {
  display: block;
  color: var(--text);
  font-size: 1rem;
}

.loading-title span {
  display: block;
  color: var(--muted);
  font-size: 0.84rem;
  line-height: 1.35;
  max-width: 980px;
}

.loading-creative {
  margin-top: 10px;
}

.loading-route {
  margin-top: 7px;
  color: var(--text) !important;
  font-weight: 800;
  font-size: 0.92rem !important;
}

.loading-copy {
  margin-top: 4px;
  display: -webkit-box !important;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.boardroom-stage {
  position: absolute;
  left: 18px;
  right: 18px;
  top: 146px;
  bottom: 18px;
  z-index: 1;
  border-radius: 22px;
  overflow: hidden;
  background:
    radial-gradient(circle at 50% 50%, rgba(77, 216, 255, 0.10), transparent 35%),
    rgba(2, 6, 23, 0.20);
}

.table-orbit {
  position: absolute;
  z-index: 1;
  width: 250px;
  height: 156px;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  border: 1px solid rgba(77, 216, 255, 0.24);
  background:
    radial-gradient(circle at 50% 50%, rgba(77, 216, 255, 0.16), rgba(15, 23, 42, 0.72) 58%, rgba(2, 6, 23, 0.88));
  box-shadow: 0 0 40px rgba(77, 216, 255, 0.10);
}

.moderator-node,
.agent-node {
  position: absolute;
  z-index: 4;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.86);
  backdrop-filter: blur(12px);
  box-shadow: 0 14px 34px rgba(0,0,0,0.28);
}

.moderator-node {
  top: 50%;
  left: 50%;
  width: 134px;
  padding: 14px 12px;
  text-align: center;
  transform: translate(-50%, -50%);
  border-color: rgba(77, 216, 255, 0.38);
}

.agent-node {
  width: 156px;
  padding: 10px 11px;
  transform: translate(-50%, -50%);
}

.moderator-node strong,
.agent-node strong {
  display: block;
  color: var(--text);
  font-size: 0.86rem;
  line-height: 1.05;
}

.moderator-node span,
.agent-node span {
  display: block;
  color: #94a3b8;
  font-size: 0.72rem;
  margin-top: 4px;
}

.agent-node::after,
.moderator-node::after {
  content: "";
  position: absolute;
  width: 9px;
  height: 9px;
  right: 10px;
  top: 10px;
  border-radius: 50%;
  background: var(--cyan);
  box-shadow: 0 0 16px var(--cyan);
  animation: nodePulse 1.4s ease-in-out infinite;
}

.active-node {
  border-color: rgba(77, 216, 255, 0.78);
  box-shadow: 0 0 34px rgba(77, 216, 255, 0.22), 0 14px 34px rgba(0,0,0,0.28);
}

.target-node {
  border-color: rgba(185, 140, 255, 0.70);
  box-shadow: 0 0 28px rgba(185, 140, 255, 0.18), 0 14px 34px rgba(0,0,0,0.28);
}

.active-node::after {
  background: var(--green);
  box-shadow: 0 0 18px var(--green);
}

.target-node::after {
  background: var(--purple);
  box-shadow: 0 0 18px var(--purple);
}

.agent-performance { top: 18%; left: 21%; border-left: 4px solid var(--green); }
.agent-fatigue { top: 18%; left: 79%; border-left: 4px solid var(--orange); }
.agent-visual { top: 68%; left: 21%; border-left: 4px solid var(--cyan); }
.agent-risk { top: 68%; left: 79%; border-left: 4px solid var(--red); }
.agent-audience { top: 88%; left: 50%; border-left: 4px solid var(--purple); }

.connection-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 2;
  pointer-events: none;
}

.connector-line {
  stroke: rgba(77, 216, 255, 0.22);
  stroke-width: 0.55;
  stroke-linecap: round;
  vector-effect: non-scaling-stroke;
}

.connector-line.active-line {
  stroke: rgba(46, 242, 160, 0.92);
  stroke-width: 1.1;
  filter: drop-shadow(0 0 5px rgba(46, 242, 160, 0.65));
  animation: connectorPulse 1.3s ease-in-out infinite;
}

.live-feed {
  border-radius: 18px;
  padding: 14px;
  margin-top: 10px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(2, 6, 23, 0.54);
  max-height: 360px;
  overflow-y: auto;
}

.live-event {
  border-left: 3px solid var(--cyan);
  padding: 8px 0 8px 12px;
  margin-bottom: 10px;
  color: #dbeafe;
}

.live-route {
  color: var(--green);
  font-weight: 800;
}

.live-event:last-child {
  margin-bottom: 0;
}

.live-event span {
  display: block;
  color: #94a3b8;
  font-size: 0.78rem;
  margin-bottom: 2px;
}

.decision-panel {
  border-radius: 22px;
  padding: 18px 20px;
  margin: 18px 0;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.66);
}

.decision-panel h4 {
  margin: 0 0 10px;
  color: var(--text);
}

.plain-list {
  margin: 8px 0 0 18px;
  color: #dbeafe;
}

.plain-list li {
  margin-bottom: 8px;
}

.hypothesis-card {
  border-left: 3px solid var(--green);
  border-radius: 16px;
  padding: 12px 14px;
  margin-bottom: 10px;
  background: rgba(2, 6, 23, 0.48);
  color: #dbeafe;
}

.hypothesis-card strong {
  display: block;
  color: var(--text);
  margin-bottom: 4px;
}

@keyframes nodePulse {
  0%, 100% { opacity: 0.35; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.25); }
}

@keyframes signalFlow {
  0% { opacity: 0.15; filter: blur(0px); }
  50% { opacity: 0.95; filter: blur(0.3px); }
  100% { opacity: 0.15; filter: blur(0px); }
}

@keyframes connectorPulse {
  0%, 100% { opacity: 0.45; }
  50% { opacity: 1; }
}

.agent-line {
  border-radius: 18px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.round-note {
  margin-bottom: 16px;
  color: #cbd5e1;
  border-left: 3px solid var(--cyan);
  background: rgba(77, 216, 255, 0.07);
  border-radius: 16px;
  padding: 12px 14px;
}

.briefing-grid,
.evidence-grid,
.consensus-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  margin: 12px 0 16px;
}

.briefing-item,
.evidence-item,
.consensus-item {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 16px;
  padding: 13px 14px;
  background: rgba(15, 23, 42, 0.62);
}

.briefing-label,
.evidence-label,
.score-label {
  color: var(--muted);
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 700;
}

.briefing-value,
.evidence-value {
  color: var(--text);
  font-size: 1.08rem;
  margin-top: 6px;
  font-weight: 800;
}

.evidence-source {
  color: #8ea3bb;
  font-size: 0.82rem;
  margin-top: 4px;
}

.challenge-card,
.error-card {
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 18px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: rgba(15, 23, 42, 0.68);
}

.challenge-body {
  color: #dbeafe;
  margin-top: 8px;
  font-size: 1rem;
}

.score-track {
  height: 10px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(148, 163, 184, 0.16);
  margin-top: 8px;
}

.score-fill {
  height: 100%;
  border-radius: 999px;
}

.small-context {
  color: #9fb1c8;
  font-size: 0.9rem;
  margin-top: 6px;
}

.verdict-card {
  border-radius: 24px;
  padding: 18px 22px;
  margin-bottom: 18px;
  text-align: center;
  background: rgba(15, 23, 42, 0.76);
  box-shadow: 0 20px 60px rgba(0,0,0,0.28);
}

.verdict-label {
  font-size: clamp(1.45rem, 3vw, 2.5rem);
  font-weight: 800;
  letter-spacing: 0.08em;
}

div[data-testid="stRadio"] label {
  color: #dbeafe;
}

div[data-testid="stRadio"] [role="radiogroup"] {
  gap: 0.7rem;
}

div[data-testid="stRadio"] [role="radio"] {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 999px;
  padding: 0.7rem 1rem;
  background: rgba(15, 23, 42, 0.58);
}

.st-key-main_nav {
  margin: 18px 0 20px;
}

.st-key-main_nav .stButton > button {
  min-height: 72px;
  border-radius: 18px;
  justify-content: center;
  padding: 0.8rem 1.2rem;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.80), rgba(2, 6, 23, 0.60));
  color: #94a3b8;
  font-size: 1.15rem;
  font-weight: 800;
  text-align: center;
  line-height: 1.3;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 10px 30px rgba(0,0,0,0.18);
  transition: all 0.2s ease;
}

.st-key-main_nav .stButton > button:hover {
  border-color: rgba(77, 216, 255, 0.36);
  color: #dbeafe;
}

.st-key-main_nav .stButton > button[kind="primary"] {
  border-color: rgba(77, 216, 255, 0.65);
  background:
    linear-gradient(135deg, rgba(77,216,255,0.20), rgba(46,242,160,0.12)),
    rgba(15, 23, 42, 0.88);
  color: #e5edf8;
  box-shadow:
    0 0 0 1px rgba(77,216,255,0.15),
    0 0 32px rgba(77,216,255,0.12),
    0 14px 40px rgba(0,0,0,0.24);
}

button[kind="primary"], .stButton > button {
  border-radius: 999px;
  border: 1px solid rgba(77, 216, 255, 0.32);
  background: linear-gradient(135deg, rgba(77,216,255,0.22), rgba(46,242,160,0.16));
  color: #e5edf8;
  font-weight: 800;
}

@media (max-width: 900px) {
  .block-container { padding-left: 0.75rem; padding-right: 0.75rem; }
  .hero-shell { padding: 22px; }
  .metric-value { font-size: 1.6rem; }
  .st-key-main_nav .stButton > button { min-height: 62px; justify-content: center; text-align: center; }
  .boardroom-creative-card { max-width: 100%; }
  .boardroom-asset-frame { height: 340px; }
  .loading-boardroom { min-height: 570px; }
  .loading-title {
    height: 132px;
    padding: 14px 16px;
  }
  .boardroom-stage {
    top: 150px;
    left: 10px;
    right: 10px;
    bottom: 14px;
  }
  .agent-node { width: 130px; }
  .agent-performance { top: 20%; left: 22%; }
  .agent-fatigue { top: 20%; left: 78%; }
  .agent-visual { top: 70%; left: 22%; }
  .agent-risk { top: 70%; left: 78%; }
  .agent-audience { top: 90%; left: 50%; }
}

/* =========================================================================
   PREMIUM UPGRADES
   ========================================================================= */

/* --- Metric card glow ring on hover --- */
.metric-card {
  position: relative;
  overflow: hidden;
  transition: transform 0.25s cubic-bezier(0.2,0.8,0.2,1), box-shadow 0.25s ease;
}
.metric-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 22px;
  background: radial-gradient(circle at 50% 0%, rgba(77,216,255,0.12) 0%, transparent 60%);
  pointer-events: none;
}

/* --- Creative card status-tinted bottom border --- */
.creative-card.status-top    { border-bottom: 2px solid #2ef2a0; }
.creative-card.status-fatigued { border-bottom: 2px solid #ffb020; }
.creative-card.status-stable  { border-bottom: 2px solid #4dd8ff; }
.creative-card.status-underperformer { border-bottom: 2px solid #64748b; }

/* --- Section headers --- */
.screen-title {
  font-size: 1.55rem;
  font-weight: 800;
  color: var(--fg1);
  margin: 0 0 4px;
  letter-spacing: -0.01em;
}
.screen-caption {
  color: var(--fg3);
  font-size: 0.92rem;
  margin-bottom: 20px;
}

/* --- Agent chat bubble --- */
.agent-bubble {
  border-radius: 20px;
  margin-bottom: 14px;
  background: linear-gradient(180deg, rgba(15,23,42,0.84), rgba(2,6,23,0.72));
  border: 1px solid rgba(148,163,184,0.18);
  border-left-width: 4px;
  box-shadow: 0 12px 36px rgba(0,0,0,0.28);
  overflow: hidden;
  transition: transform 0.2s ease;
}
.agent-bubble:hover { transform: translateX(3px); }

.agent-bubble-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px 10px;
}
.agent-avatar {
  width: 42px;
  height: 42px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 1.1rem;
  color: #030c1a;
  flex-shrink: 0;
}
.agent-bubble-name {
  flex: 1;
  min-width: 0;
}
.agent-bubble-name strong { display: block; color: #e5edf8; font-size: 1rem; line-height: 1.1; }
.agent-bubble-name span  { display: block; color: #94a3b8; font-size: 0.78rem; margin-top: 2px; }

.verdict-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 0.84rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  border: 1px solid currentColor;
  flex-shrink: 0;
}

.agent-bubble-body { padding: 0 16px 14px; }

.conf-bar-track {
  height: 5px;
  border-radius: 999px;
  background: rgba(148,163,184,0.18);
  overflow: hidden;
  margin-top: 6px;
}
.conf-bar-fill { height: 100%; border-radius: 999px; }

.mind-change-badge {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: rgba(255,176,32,0.10);
  border: 1px solid rgba(255,176,32,0.28);
  font-size: 0.82rem;
}
.mind-change-badge strong { color: #ffb020; }
.mind-change-badge span   { color: #cbd5e1; }

/* --- Final verdict hero panel --- */
.verdict-hero {
  border-radius: 28px;
  padding: clamp(24px, 2.5vw, 36px);
  margin: 24px 0;
  text-align: center;
  backdrop-filter: blur(20px);
  box-shadow: 0 28px 80px rgba(0,0,0,0.45);
}
.verdict-hero-eyebrow {
  font-size: 0.8rem;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  font-weight: 800;
  margin-bottom: 10px;
}
.verdict-hero-label {
  font-weight: 800;
  letter-spacing: 0.1em;
  line-height: 1;
  text-shadow: 0 0 40px currentColor;
}
.verdict-hero-sub {
  color: #94a3b8;
  font-size: 0.9rem;
  margin-top: 8px;
}
.verdict-hero-reasons {
  margin: 20px auto 0;
  max-width: 560px;
  text-align: left;
}
.verdict-reason-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 10px;
}
.verdict-reason-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 7px;
}
.verdict-reason-text { color: #cbd5e1; font-size: 0.96rem; line-height: 1.5; }

/* --- Analytics screen improvements --- */
.analytics-section-head {
  color: var(--fg1);
  font-size: 1.05rem;
  font-weight: 800;
  margin-bottom: 6px;
  letter-spacing: -0.01em;
}
.fatigue-info-panel {
  border-left: 3px solid #ffb020;
  background: rgba(255,176,32,0.08);
  border-radius: 14px;
  padding: 12px 14px;
  color: #ffe5a0;
  font-size: 0.9rem;
  margin-top: 12px;
}
.roas-compare-card {
  border-radius: 18px;
  padding: 16px;
  background: rgba(15,23,42,0.72);
  border: 1px solid rgba(148,163,184,0.16);
  margin-bottom: 12px;
}
.roas-compare-label { color: #94a3b8; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; }
.roas-compare-val   { color: #e5edf8; font-size: 1.6rem; font-weight: 800; margin: 6px 0 8px; }
.roas-bar-track     { height: 8px; border-radius: 999px; background: rgba(148,163,184,0.18); overflow: hidden; }
.roas-bar-fill      { height: 100%; border-radius: 999px; }
</style>
        """,
        unsafe_allow_html=True,
    )


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
    except (TypeError, ValueError):
        return default


def fmt_money(value: Any) -> str:
    value = safe_float(value)
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def fmt_compact(value: Any) -> str:
    value = safe_float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def fmt_pct(value: Any, decimals: int = 1) -> str:
    return f"{safe_float(value) * 100:.{decimals}f}%"


def fmt_signed_pct(value: Any) -> str:
    value = safe_float(value)
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.0f}%"


def has_value(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        return not pd.isna(value)
    except (TypeError, ValueError):
        return True


def metric_label(key: Any) -> str:
    key_str = str(key)
    return METRIC_LABELS.get(key_str, key_str.replace("_", " ").title())


def fmt_metric_value(key: Any, value: Any) -> str:
    key_str = str(key).lower()
    if not has_value(value):
        return "Not available"
    if key_str.endswith("_id") or key_str in {"id", "task_id"}:
        return str(value)
    if isinstance(value, (list, tuple, set)):
        values = [str(item).replace("_", " ") for item in list(value)[:4]]
        suffix = "..." if len(value) > 4 else ""
        return ", ".join(values) + suffix
    if isinstance(value, dict):
        return f"{len(value)} fields"

    numeric_value = safe_float(value, default=float("nan"))
    is_numeric = not math.isnan(numeric_value)

    if key_str in {"spend", "total_revenue_usd", "revenue", "cost", "cpi"} and is_numeric:
        return fmt_money(numeric_value)
    if key_str in {"impressions", "clicks", "installs", "conversions", "active_days"} and is_numeric:
        return fmt_compact(numeric_value)
    if key_str in {"ctr", "cvr", "first_7d_ctr", "last_7d_ctr"} and is_numeric:
        return fmt_pct(numeric_value, 2)
    if key_str in {"ctr_decay_pct", "spend_share_pct"} and is_numeric:
        return fmt_pct(numeric_value, 0)
    if key_str == "ctr_vs_campaign_pct" and is_numeric:
        return fmt_signed_pct(numeric_value)
    if key_str in {"ctr_pct", "ipm_pct", "cvr_pct", "spend_pct"} and is_numeric:
        return f"P{int(numeric_value * 100)}"
    if key_str in {"overall_roas", "roas"} and is_numeric:
        return f"{numeric_value:.2f}x"
    if key_str == "ipm" and is_numeric:
        return f"{numeric_value:.3f}"
    if key_str in {"confidence", "reliability_score"} and is_numeric:
        return fmt_pct(numeric_value, 0)
    if is_numeric and abs(numeric_value) >= 1000:
        return fmt_compact(numeric_value)
    if is_numeric and abs(numeric_value) < 1 and numeric_value != 0:
        return f"{numeric_value:.4f}"
    if is_numeric:
        return f"{numeric_value:g}"
    text = str(value).replace("_", " ")
    return text if len(text) <= 160 else f"{text[:157]}..."


def agent_display(agent: Any) -> tuple[str, str]:
    agent_key = str(agent or "unknown")
    return AGENT_META.get(agent_key, (agent_key.replace("_", " ").title(), "#94a3b8"))


def render_round_note(block_type: str) -> None:
    note = ROUND_CONTEXT.get(block_type)
    if not note:
        return
    st.markdown(
        f'<div class="round-note">{html.escape(note)}</div>',
        unsafe_allow_html=True,
    )


def render_metric_tiles(items: list[tuple[str, Any]], class_name: str = "briefing") -> None:
    tiles = []
    for key, value in items:
        if not has_value(value):
            continue
        tiles.append(
            f"""
<div class="{class_name}-item">
  <div class="{class_name}-label">{html.escape(metric_label(key))}</div>
  <div class="{class_name}-value">{html.escape(fmt_metric_value(key, value))}</div>
</div>
            """
        )
    if not tiles:
        st.caption("No usable fields available for this section.")
        return
    st.markdown(
        f'<div class="{class_name}-grid">{"".join(tiles)}</div>',
        unsafe_allow_html=True,
    )


def image_to_data_uri(path: Any) -> str | None:
    if not path:
        return None
    file_path = Path(str(path))
    if not file_path.exists():
        return None
    mime = mimetypes.guess_type(file_path.name)[0] or "image/png"
    try:
        encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    except OSError:
        return None
    return f"data:{mime};base64,{encoded}"


@st.cache_data(ttl=60)
def fetch_creative_summaries() -> list[dict[str, Any]]:
    response = requests.get(f"{ORCHESTRATOR}/creatives", timeout=6)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60)
def fetch_creative_detail(creative_id: str) -> dict[str, Any]:
    response = requests.get(f"{ORCHESTRATOR}/creatives/{creative_id}", timeout=6)
    response.raise_for_status()
    return response.json()


def load_campaign_creatives() -> tuple[list[dict[str, Any]], bool]:
    try:
        summaries = fetch_creative_summaries()
        rows: list[dict[str, Any]] = []
        for item in summaries:
            creative_id = str(item.get("creative_id", ""))
            if not creative_id:
                continue
            try:
                detail = fetch_creative_detail(creative_id)
                rows.append({**item, **detail})
            except Exception:
                rows.append(item)
        return rows or DEMO_CREATIVES, not bool(rows)
    except Exception:
        return DEMO_CREATIVES, True


def campaign_metrics(creatives: list[dict[str, Any]]) -> dict[str, float]:
    total_spend = sum(safe_float(c.get("spend")) for c in creatives)
    total_impressions = sum(safe_float(c.get("impressions")) for c in creatives)
    total_clicks = sum(safe_float(c.get("clicks")) for c in creatives)
    total_revenue = sum(safe_float(c.get("total_revenue_usd")) for c in creatives)

    if total_impressions:
        overall_ctr = total_clicks / total_impressions
    else:
        overall_ctr = sum(safe_float(c.get("ctr")) for c in creatives) / max(len(creatives), 1)

    if total_spend and total_revenue:
        overall_roas = total_revenue / total_spend
    else:
        weighted_roas = sum(
            safe_float(c.get("overall_roas")) * max(safe_float(c.get("spend")), 1.0)
            for c in creatives
        )
        overall_roas = weighted_roas / max(total_spend, 1.0)

    return {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "overall_ctr": overall_ctr,
        "overall_roas": overall_roas,
    }


def creative_reliability(creative: dict[str, Any]) -> float:
    """Directional score capped at 80% because the dataset is not ground truth."""
    score = 0.80
    missing_core = [
        key
        for key in ("ctr", "ipm", "spend", "installs", "impressions")
        if creative.get(key) in (None, "")
    ]
    score -= 0.05 * len(missing_core)
    if safe_float(creative.get("installs")) < 50:
        score -= 0.20
    if safe_float(creative.get("impressions")) < 1000:
        score -= 0.15
    if safe_float(creative.get("spend")) < 50:
        score -= 0.10
    return max(0.25, min(0.80, score))


def enrich_creatives(creatives: list[dict[str, Any]], metrics: dict[str, float]) -> list[dict[str, Any]]:
    total_spend = metrics["total_spend"] or 1.0
    campaign_ctr = metrics["overall_ctr"] or 0.000001
    enriched = []
    for creative in creatives:
        item = dict(creative)
        ctr = safe_float(item.get("ctr"))
        item["ctr_vs_campaign_pct"] = ((ctr - campaign_ctr) / campaign_ctr) * 100
        item["spend_share_pct"] = safe_float(item.get("spend")) / total_spend
        item["reliability_score"] = creative_reliability(item)
        enriched.append(item)
    return enriched


def status_meta(creative: dict[str, Any]) -> tuple[str, str]:
    raw = str(creative.get("performance_label") or creative.get("creative_status") or "stable")
    key = raw.strip().lower().replace(" ", "_")
    return STATUS_META.get(key, (raw.replace("_", " ").title(), "status-stable"))


def select_creative(creatives: list[dict[str, Any]], creative_id: str | None = None) -> dict[str, Any]:
    if not creatives:
        return {}
    target = creative_id or st.session_state.get("selected_creative_id")
    if target:
        for creative in creatives:
            if str(creative.get("creative_id")) == str(target):
                return creative
    return creatives[0]


def set_active_screen(screen: str) -> None:
    st.session_state["active_screen"] = screen


def toggle_session_bool(key: str) -> None:
    st.session_state[key] = not bool(st.session_state.get(key, False))


def metric_card(label: str, value: str, context: str, accent: str) -> None:
    st.markdown(
        f"""
<div class="metric-card" style="
  box-shadow: 0 20px 60px rgba(0,0,0,0.28), 0 0 0 1px {accent}28, 0 0 40px {accent}18;
  border-color: {accent}44;
">
  <div class="metric-label" style="color:{accent}bb;">{html.escape(label)}</div>
  <div class="metric-value" style="background:linear-gradient(135deg,#e5edf8,{accent});-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">{html.escape(value)}</div>
  <div class="metric-context">{html.escape(context)}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def creative_card(creative: dict[str, Any], campaign_ctr: float, index: int) -> None:
    label, status_class = status_meta(creative)
    image_uri = image_to_data_uri(creative.get("image_path"))
    creative_id = str(creative.get("creative_id", "unknown"))
    title = f"Creative {html.escape(creative_id)}"
    ctr_vs = safe_float(creative.get("ctr_vs_campaign_pct"))
    spend_share = safe_float(creative.get("spend_share_pct"))
    format_ = html.escape(str(creative.get("format") or "unknown").replace("_", " ").title())
    tone = html.escape(str(creative.get("emotional_tone") or creative.get("theme") or "—"))
    ctr_color = "#2ef2a0" if ctr_vs >= 0 else "#ff5b7a"
    ctr_sign = "+" if ctr_vs >= 0 else ""

    # Status badge color per class
    badge_styles = {
        "status-top":           "background:linear-gradient(135deg,#2ef2a0,#b8ffd9);color:#04130d;",
        "status-fatigued":      "background:linear-gradient(135deg,#ffb020,#ff5b7a);color:#190d02;",
        "status-stable":        "background:linear-gradient(135deg,#4dd8ff,#a7f3ff);color:#03111a;",
        "status-underperformer":"background:rgba(100,116,139,0.42);color:#e2e8f0;",
    }
    badge_style = badge_styles.get(status_class, badge_styles["status-stable"])

    if image_uri:
        image_block = f"""
<div style="position:relative;width:100%;aspect-ratio:1/1;border-radius:16px;overflow:hidden;margin-bottom:12px;">
  <img src="{image_uri}" alt="{title}" style="width:100%;height:100%;object-fit:cover;display:block;">
  <div style="position:absolute;top:10px;right:10px;">
    <span style="display:inline-flex;border-radius:999px;padding:5px 10px;font-size:0.72rem;font-weight:800;border:1px solid rgba(255,255,255,0.15);{badge_style}">{html.escape(label)}</span>
  </div>
  <div style="position:absolute;bottom:0;left:0;right:0;height:56px;background:linear-gradient(to top,rgba(2,6,23,0.85),transparent);border-radius:0 0 16px 16px;"></div>
  <div style="position:absolute;bottom:8px;left:12px;color:#e5edf8;font-size:0.8rem;font-weight:700;letter-spacing:0.02em;">{format_} · {tone}</div>
</div>"""
    else:
        image_block = f"""
<div style="position:relative;width:100%;aspect-ratio:1/1;border-radius:16px;overflow:hidden;margin-bottom:12px;
  background:linear-gradient(135deg,rgba(77,216,255,0.22),rgba(185,140,255,0.15)),
  repeating-linear-gradient(45deg,rgba(255,255,255,0.05) 0 10px,transparent 10px 20px);
  display:flex;align-items:center;justify-content:center;">
  <div style="position:absolute;top:10px;right:10px;">
    <span style="display:inline-flex;border-radius:999px;padding:5px 10px;font-size:0.72rem;font-weight:800;border:1px solid rgba(255,255,255,0.15);{badge_style}">{html.escape(label)}</span>
  </div>
  <span style="color:rgba(229,237,248,0.55);font-weight:700;font-size:0.9rem;">{title}</span>
  <div style="position:absolute;bottom:8px;left:12px;color:#94a3b8;font-size:0.8rem;">{format_} · {tone}</div>
</div>"""

    st.markdown(
        f"""
<div class="creative-card">
  {image_block}
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
    <div style="color:#e5edf8;font-size:1rem;font-weight:800;">{title}</div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">
    <div style="border-radius:12px;padding:10px 12px;background:rgba(2,6,23,0.52);border:1px solid rgba(148,163,184,0.12);">
      <div style="color:#94a3b8;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.06em;font-weight:700;">CTR vs campaign</div>
      <div style="color:{ctr_color};font-size:1.15rem;font-weight:800;margin-top:4px;">{ctr_sign}{ctr_vs:.0f}%</div>
    </div>
    <div style="border-radius:12px;padding:10px 12px;background:rgba(2,6,23,0.52);border:1px solid rgba(148,163,184,0.12);">
      <div style="color:#94a3b8;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.06em;font-weight:700;">Spend share</div>
      <div style="color:#e5edf8;font-size:1.15rem;font-weight:800;margin-top:4px;">{spend_share * 100:.1f}%</div>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Analyze Creative →", key=f"analyze_{creative_id}_{index}", use_container_width=True):
        st.session_state["selected_creative_id"] = creative_id
        st.session_state["active_screen"] = "Creative Analytics"
        st.rerun()


def render_header(using_demo_data: bool) -> None:
    data_note = "Demo fallback data" if using_demo_data else "Live campaign parquet"
    
    # Use the wordmark styling provided in assets/wordmark.html
    st.markdown(
        f"""
<style>
  .wm {{
    display:flex;align-items:center;gap:14px;
    padding:5px 0 10px;
    margin-bottom: 12px;
  }}
  .glyph {{
    width:46px;height:46px;border-radius:14px;
    background:linear-gradient(135deg,#4dd8ff,#2ef2a0);
    display:flex;align-items:center;justify-content:center;
    color:#03111a;font-weight:800;font-size:22px;letter-spacing:-.02em;
    box-shadow:0 0 24px rgba(77,216,255,.25), inset 0 1px 0 rgba(255,255,255,.4);
  }}
  .text-wm {{display:flex;flex-direction:column;line-height:1}}
  .text-wm .a {{color:var(--cyan);font-size:11px;letter-spacing:.18em;text-transform:uppercase;font-weight:800;margin-bottom:4px}}
  .text-wm .b {{color:var(--fg1);font-size:26px;font-weight:800;letter-spacing:-.01em; margin:0; padding:0; line-height: 1; background: none; -webkit-text-fill-color: var(--fg1); box-shadow: none; transform: none; border: none;}}
</style>

<div class="wm">
  <div class="glyph">CB</div>
  <div class="text-wm">
    <div class="a">Smadex × HackUPC</div>
    <div class="b">Creative Boardroom</div>
  </div>
</div>

<div class="hero-shell" style="margin-top:8px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
  <div>
    <div class="eyebrow" style="margin-bottom:6px;">AI ad decision copilot</div>
    <div class="hero-title" style="font-size:clamp(1.8rem,3.5vw,3rem);margin-bottom:6px;">Creative Boardroom</div>
    <div class="hero-copy" style="font-size:0.96rem;max-width:640px;">
      Five AI specialists debate each creative, challenge each other's data, and converge on one actionable recommendation — scale, pause, pivot, or test next.
    </div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;">
    <div style="border-radius:999px;padding:5px 14px;background:rgba(46,242,160,0.12);border:1px solid rgba(46,242,160,0.30);color:#2ef2a0;font-size:0.78rem;font-weight:800;letter-spacing:0.06em;">{html.escape(data_note.upper())}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_campaign_overview(creatives: list[dict[str, Any]], metrics: dict[str, float]) -> None:
    st.markdown('<div class="screen-title">Campaign Overview</div>', unsafe_allow_html=True)
    st.markdown('<div class="screen-caption">Manager-level view of spend, reach, and creative health across all 6 ads.</div>', unsafe_allow_html=True)

    cols = st.columns(4)
    with cols[0]:
        metric_card("Total Spend", fmt_money(metrics["total_spend"]), "Budget already invested", "#4dd8ff")
    with cols[1]:
        metric_card("Impressions", fmt_compact(metrics["total_impressions"]), "Campaign delivery volume", "#b98cff")
    with cols[2]:
        metric_card("Overall CTR", fmt_pct(metrics["overall_ctr"], 2), "Clicks divided by impressions", "#2ef2a0")
    with cols[3]:
        metric_card("Overall ROAS", f"{metrics['overall_roas']:.2f}x", "Revenue per dollar spent", "#ffb020")

    # Campaign health banner
    campaign_reliability = min(
        0.80,
        sum(safe_float(c.get("reliability_score"), 0.5) for c in creatives) / max(len(creatives), 1),
    )
    n_fatigued = sum(1 for c in creatives if str(c.get("creative_status", "")).lower() == "fatigued")
    n_top = sum(1 for c in creatives if str(c.get("creative_status", "")).lower() == "top_performer")
    st.markdown(
        f"""
<div style="display:flex;gap:12px;flex-wrap:wrap;margin:16px 0 24px;padding:16px 20px;
  border-radius:20px;background:rgba(15,23,42,0.60);border:1px solid rgba(148,163,184,0.16);
  box-shadow:inset 0 1px 0 rgba(255,255,255,0.04);">
  <div style="flex:1;min-width:120px;">
    <div style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;font-weight:700;">Top Performers</div>
    <div style="color:#2ef2a0;font-size:1.5rem;font-weight:800;margin-top:2px;">{n_top}</div>
  </div>
  <div style="flex:1;min-width:120px;">
    <div style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;font-weight:700;">Fatigued</div>
    <div style="color:#ffb020;font-size:1.5rem;font-weight:800;margin-top:2px;">{n_fatigued}</div>
  </div>
  <div style="flex:2;min-width:200px;">
    <div style="color:#94a3b8;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;font-weight:700;">Decision Reliability</div>
    <div style="display:flex;align-items:center;gap:10px;margin-top:4px;">
      <div style="flex:1;height:8px;border-radius:999px;background:rgba(148,163,184,0.18);overflow:hidden;">
        <div style="height:100%;width:{int(campaign_reliability*100)}%;border-radius:999px;background:linear-gradient(90deg,#ffb020,#2ef2a0);"></div>
      </div>
      <span style="color:#e5edf8;font-weight:800;font-size:0.95rem;">{int(campaign_reliability*100)}%</span>
    </div>
    <div style="color:#94a3b8;font-size:0.76rem;margin-top:3px;">Directional — capped at 80% (non-ground-truth data)</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="font-size:1.15rem;font-weight:800;color:#e5edf8;margin-bottom:4px;letter-spacing:-0.01em;">Creative Grid</div>'
        '<div style="color:#94a3b8;font-size:0.88rem;margin-bottom:16px;">Click any card to open the deep-dive analytics view.</div>',
        unsafe_allow_html=True,
    )
    grid = st.columns(3)
    for index, creative in enumerate(creatives):
        with grid[index % 3]:
            creative_card(creative, metrics["overall_ctr"], index)


def selected_creative_selector(creatives: list[dict[str, Any]]) -> dict[str, Any]:
    options = {
        f"{c.get('creative_id')} - {c.get('format', '?')} - {c.get('theme', c.get('creative_status', '?'))}": c
        for c in creatives
    }
    selected_current = select_creative(creatives)
    labels = list(options.keys())
    selected_label = next(
        (
            label
            for label, creative in options.items()
            if str(creative.get("creative_id")) == str(selected_current.get("creative_id"))
        ),
        labels[0],
    )
    label = st.selectbox("Creative", labels, index=labels.index(selected_label), label_visibility="collapsed")
    selected = options[label]
    st.session_state["selected_creative_id"] = str(selected.get("creative_id"))
    return selected


def render_asset(creative: dict[str, Any]) -> None:
    image_path = creative.get("image_path", "")
    if image_path and Path(str(image_path)).exists():
        try:
            st.image(Image.open(str(image_path)), use_container_width=True)
            return
        except Exception:
            pass
    st.markdown(
        f"""
<div class="creative-image creative-placeholder">
  Creative {html.escape(str(creative.get("creative_id", "unknown")))}
</div>
        """,
        unsafe_allow_html=True,
    )


def render_ctr_chart(selected: dict[str, Any]) -> None:
    active_days = max(int(safe_float(selected.get("active_days"), 14)), 14)
    first_ctr = safe_float(selected.get("first_7d_ctr"), safe_float(selected.get("ctr")))
    last_ctr = safe_float(selected.get("last_7d_ctr"), safe_float(selected.get("ctr")))
    fatigue_day = int(safe_float(selected.get("fatigue_day"), 0))

    days = list(range(1, active_days + 1))
    # Smooth exponential decay
    decay_ratio = (first_ctr - last_ctr) / max(first_ctr, 1e-9)
    ctr_curve = [
        first_ctr * (1 - decay_ratio * ((d - 1) / max(active_days - 1, 1)) ** 0.65)
        for d in days
    ]
    threshold = first_ctr * 0.5

    df = pd.DataFrame({
        "Day": days * 2,
        "CTR": ctr_curve + [threshold] * len(days),
        "Series": ["CTR"] * len(days) + ["−50% fatigue threshold"] * len(days),
    })

    color_scale = alt.Scale(
        domain=["CTR", "−50% fatigue threshold"],
        range=["#4dd8ff", "#ff5b7a"],
    )
    stroke_dash_cond = alt.condition(
        alt.datum["Series"] == "−50% fatigue threshold",
        alt.value([6, 3]),
        alt.value([0]),
    )

    lines = alt.Chart(df).mark_line(strokeWidth=2.5).encode(
        x=alt.X("Day:Q", title="Day", axis=alt.Axis(labelColor="#94a3b8", titleColor="#94a3b8", gridColor="rgba(148,163,184,0.08)")),
        y=alt.Y("CTR:Q", axis=alt.Axis(format=".3%", labelColor="#94a3b8", titleColor="#94a3b8", gridColor="rgba(148,163,184,0.08)")),
        color=alt.Color("Series:N", scale=color_scale, legend=alt.Legend(labelColor="#94a3b8", orient="top-right", labelFontSize=11)),
        strokeDash=stroke_dash_cond,
    )
    layers: list[Any] = [lines]

    if fatigue_day > 0:
        df_rule = pd.DataFrame({"Day": [fatigue_day]})
        rule = alt.Chart(df_rule).mark_rule(color="#ffb020", strokeWidth=2, strokeDash=[8, 4]).encode(x="Day:Q")
        lbl_df = pd.DataFrame({"Day": [fatigue_day], "y": [first_ctr * 0.88 if first_ctr > 0 else 0.001]})
        label = alt.Chart(lbl_df).mark_text(
            color="#ffb020", align="left", dx=6, dy=-6, fontSize=11, fontWeight=700,
        ).encode(x="Day:Q", y="y:Q", text=alt.value(f"⚠ Fatigue day {fatigue_day}"))
        layers += [rule, label]

    chart = (
        alt.layer(*layers)
        .properties(height=260, background="transparent")
        .configure_axis(gridColor="rgba(148,163,184,0.08)", domainColor="rgba(148,163,184,0.2)")
        .configure_view(strokeWidth=0)
        .interactive()
    )
    st.altair_chart(chart, use_container_width=True)


def render_creative_analytics(creatives: list[dict[str, Any]], metrics: dict[str, float]) -> None:
    st.markdown('<div class="screen-title">Single Creative Analytics</div>', unsafe_allow_html=True)
    st.markdown('<div class="screen-caption">Deep-dive on fatigue trends, ROAS, and scale readiness for the selected ad.</div>', unsafe_allow_html=True)

    left, center, right = st.columns([0.9, 1.3, 0.9], gap="large")
    with left:
        selected = selected_creative_selector(creatives)
        render_asset(selected)
        tags = [
            selected.get("emotional_tone"),
            selected.get("format"),
            selected.get("theme") or selected.get("primary_theme"),
            selected.get("language"),
        ]
        st.markdown(
            '<div class="tag-row">'
            + "".join(f'<span class="meta-tag">{html.escape(str(tag))}</span>' for tag in tags if tag)
            + "</div>",
            unsafe_allow_html=True,
        )

    with center:
        st.markdown('<div class="analytics-section-head">CTR Performance Over Time</div>', unsafe_allow_html=True)
        render_ctr_chart(selected)
        decay_pct = safe_float(selected.get("ctr_decay_pct"))
        fatigue_day = int(safe_float(selected.get("fatigue_day"), 0))
        fatigue_note = (
            f"Fatigue onset detected on day {fatigue_day}. " if fatigue_day > 0 else "No fatigue onset flagged. "
        )
        st.markdown(
            f'<div class="fatigue-info-panel">{fatigue_note}CTR has declined {abs(decay_pct * 100):.0f}% from launch — threshold is −50%.</div>',
            unsafe_allow_html=True,
        )

    with right:
        st.markdown('<div class="analytics-section-head">Scale Readiness</div>', unsafe_allow_html=True)
        roas = safe_float(selected.get("overall_roas"))
        campaign_roas = metrics["overall_roas"]
        reliability = safe_float(selected.get("reliability_score"), 0.5)
        ctr_pct = safe_float(selected.get("ctr_pct"))
        roas_pct = min(roas / max(campaign_roas * 1.5, 0.001), 1.0)
        st.markdown(
            f"""
<div class="roas-compare-card">
  <div class="roas-compare-label">Creative ROAS vs Campaign</div>
  <div class="roas-compare-val">{roas:.2f}x</div>
  <div class="roas-bar-track"><div class="roas-bar-fill" style="width:{int(roas_pct*100)}%;background:{'#2ef2a0' if roas >= campaign_roas else '#ffb020'};"></div></div>
  <div style="color:#94a3b8;font-size:0.82rem;margin-top:6px;">Campaign avg {campaign_roas:.2f}x</div>
</div>
<div class="roas-compare-card">
  <div class="roas-compare-label">CTR Percentile</div>
  <div class="roas-compare-val">P{int(ctr_pct * 100)}</div>
  <div class="roas-bar-track"><div class="roas-bar-fill" style="width:{int(ctr_pct*100)}%;background:#4dd8ff;"></div></div>
  <div style="color:#94a3b8;font-size:0.82rem;margin-top:6px;">Within this campaign</div>
</div>
<div class="roas-compare-card">
  <div class="roas-compare-label">Data Reliability</div>
  <div class="roas-compare-val">{int(reliability * 100)}%</div>
  <div class="roas-bar-track"><div class="roas-bar-fill" style="width:{int(reliability*100)}%;background:linear-gradient(90deg,#ffb020,#2ef2a0);"></div></div>
  <div style="color:#94a3b8;font-size:0.82rem;margin-top:6px;">Capped at 80% (non-ground-truth data)</div>
</div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Proceed to Creative Boardroom →", key="btn_to_boardroom", type="primary", use_container_width=True):
        st.session_state["active_screen"] = "Creative Boardroom"
        st.rerun()


def render_evidence_items(evidence: list[dict[str, Any]]) -> None:
    if not evidence:
        return

    tiles = []
    for item in evidence[:5]:
        key = item.get("key", "evidence")
        source = item.get("source") or "agent"
        evidence_type = item.get("type") or "evidence"
        signal = {
            "ctr": "Audience interest signal",
            "ipm": "Install pull signal",
            "roas": "Business return signal",
            "overall_roas": "Business return signal",
            "ctr_decay_pct": "Audience tiredness signal",
            "active_days": "Exposure age signal",
            "creative_status": "Creative health signal",
        }.get(str(key), metric_label(key))
        tiles.append(
            f"""
<div class="evidence-item">
  <div class="evidence-label">{html.escape(str(evidence_type))}</div>
  <div class="evidence-value">{html.escape(signal)}</div>
  <div class="evidence-source">Source: {html.escape(str(source))}</div>
</div>
            """
        )

    st.markdown(
        '<div class="small-context"><strong>Evidence used by this agent</strong></div>'
        f'<div class="evidence-grid">{"".join(tiles)}</div>',
        unsafe_allow_html=True,
    )


def render_opinion(op: dict[str, Any], highlight_change: bool = True) -> None:
    agent = str(op.get("agent", "unknown"))
    name, color = agent_display(agent)
    verdict = str(op.get("verdict", "?"))
    confidence = safe_float(op.get("confidence"))
    changed_from = op.get("changed_from")
    claims = op.get("claims", [])
    verdict_color = VERDICT_COLORS.get(verdict, "#94a3b8")
    meaning = VERDICT_MEANINGS.get(verdict, "Agent recommendation.")
    initial = name[0].upper()
    conf_pct = int(confidence * 100)

    change_html = ""
    if changed_from and highlight_change:
        change_html = f"""
<div class="mind-change-badge">
  <strong>MIND CHANGED</strong>
  <span> — {html.escape(str(changed_from))} → {html.escape(verdict)}</span>
</div>"""

    claims_html = ""
    if claims:
        items = "".join(
            f"<li style='margin-bottom:5px;color:#cbd5e1;'>{html.escape(plain_language(claim))}</li>"
            for claim in claims[:4]
        )
        claims_html = f"<ul style='margin:10px 0 0 18px;padding:0;font-size:0.93rem;line-height:1.5;'>{items}</ul>"

    st.markdown(
        f"""
<div class="agent-bubble" style="border-left-color:{color};">
  <div class="agent-bubble-header">
    <div class="agent-avatar" style="background:linear-gradient(135deg,{color},{color}99);box-shadow:0 4px 14px {color}44;">{initial}</div>
    <div class="agent-bubble-name">
      <strong>{html.escape(name)}</strong>
      <span>{html.escape(meaning[:58])}{'…' if len(meaning) > 58 else ''}</span>
    </div>
    <div class="verdict-chip" style="color:{verdict_color};border-color:{verdict_color};background:{verdict_color}18;">{html.escape(verdict)}</div>
  </div>
  <div class="agent-bubble-body">
    <div style="color:#94a3b8;font-size:0.76rem;text-transform:uppercase;letter-spacing:0.06em;font-weight:700;">Confidence {conf_pct}%</div>
    <div class="conf-bar-track"><div class="conf-bar-fill" style="width:{conf_pct}%;background:linear-gradient(90deg,{color},{color}77);"></div></div>
    {claims_html}
    {change_html}
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )
    render_evidence_items(op.get("evidence", []))


def render_briefing(data: dict[str, Any]) -> None:
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    combined = {**context, **{key: value for key, value in data.items() if key != "context"}}

    st.markdown("##### Creative Identity")
    render_metric_tiles(
        [
            ("creative_id", combined.get("creative_id")),
            ("campaign_id", combined.get("campaign_id")),
            ("advertiser_name", combined.get("advertiser_name")),
            ("app_name", combined.get("app_name")),
            ("vertical", combined.get("vertical")),
            ("creative_status", combined.get("creative_status")),
        ]
    )

    st.markdown("##### Business Signal")
    render_metric_tiles(
        [
            ("spend", combined.get("spend")),
            ("impressions", combined.get("impressions")),
            ("clicks", combined.get("clicks")),
            ("installs", combined.get("installs")),
            ("total_revenue_usd", combined.get("total_revenue_usd")),
            ("overall_roas", combined.get("overall_roas") or combined.get("roas")),
        ]
    )

    st.markdown("##### Performance Health")
    render_metric_tiles(
        [
            ("ctr", combined.get("ctr")),
            ("ipm", combined.get("ipm")),
            ("cvr", combined.get("cvr")),
            ("ctr_pct", combined.get("ctr_pct")),
            ("ipm_pct", combined.get("ipm_pct")),
            ("cvr_pct", combined.get("cvr_pct")),
            ("first_7d_ctr", combined.get("first_7d_ctr")),
            ("last_7d_ctr", combined.get("last_7d_ctr")),
            ("ctr_decay_pct", combined.get("ctr_decay_pct")),
            ("active_days", combined.get("active_days")),
        ]
    )
    st.caption(
        "Guide: strong ads keep attention and pull people toward install; tired ads lose attention over time."
    )

    st.markdown("##### Audience And Creative Context")
    render_metric_tiles(
        [
            ("format", combined.get("format")),
            ("theme", combined.get("theme") or combined.get("primary_theme")),
            ("emotional_tone", combined.get("emotional_tone")),
            ("language", combined.get("language")),
            ("target_os", combined.get("target_os")),
            ("countries", combined.get("countries")),
            ("objective", combined.get("objective")),
            ("target_age_segment", combined.get("target_age_segment")),
        ]
    )


def render_challenge(msg: dict[str, Any]) -> None:
    from_agent = msg.get("from_agent", "unknown")
    to_agent = msg.get("to_agent", "ALL")
    from_name, from_color = agent_display(from_agent)
    to_name, _ = agent_display(to_agent)
    msg_type = str(msg.get("type", "message")).replace("_", " ").title()
    body = msg.get("body", "")

    st.markdown(
        f"""
<div class="challenge-card" style="border-left: 4px solid {from_color};">
  <strong>{html.escape(from_name)}</strong>
  <span style="color:#94a3b8;"> challenged </span>
  <strong>{html.escape(to_name)}</strong>
  <span style="float:right;color:#94a3b8;">{html.escape(msg_type)}</span>
  <div class="challenge-body">{html.escape(str(body))}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def simplify_error(error: Any) -> tuple[str, str]:
    text = str(error)
    lowered = text.lower()
    if "insufficient_quota" in lowered:
        return (
            "OpenAI quota exhausted",
            "The API key has no available billing quota. Add billing, use a different provider, or switch these agents to stubs/local mode.",
        )
    if "rate_limit_exceeded" in lowered or "too many requests" in lowered:
        return (
            "OpenAI rate limit hit",
            "Too many model requests were sent too quickly. Increase AGENT_CALL_DELAY_SECONDS or reduce parallel agent calls.",
        )
    if "timed out" in lowered or "readtimeout" in lowered:
        return (
            "Model response timed out",
            "The model did not answer before the configured timeout. Use a smaller model, increase timeout, or avoid vision calls for the demo.",
        )
    if "connection refused" in lowered or "all connection attempts failed" in lowered:
        return (
            "Agent service unavailable",
            "The orchestrator could not reach this agent. Check the uvicorn process and port mapping.",
        )
    return ("Agent call failed", text[:260])


def render_agent_errors(errors: list[dict[str, Any]]) -> None:
    for error in errors:
        agent = error.get("agent", "unknown")
        name, color = agent_display(agent)
        title, explanation = simplify_error(error.get("error", "Unknown error"))
        st.markdown(
            f"""
<div class="error-card" style="border-left: 4px solid {color};">
  <strong>{html.escape(name)}</strong>
  <span style="float:right;color:#ffb020;">Round {html.escape(str(error.get("round", "?")))}</span>
  <div class="briefing-value">{html.escape(title)}</div>
  <div class="small-context">{html.escape(explanation)}</div>
</div>
            """,
            unsafe_allow_html=True,
        )


def render_consensus(data: dict[str, Any]) -> None:
    verdict = str(data.get("verdict", "TEST_NEXT"))
    confidence = safe_float(data.get("confidence"))
    color = VERDICT_COLORS.get(verdict, "#94a3b8")
    scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    total_score = sum(max(0.0, safe_float(value)) for value in scores.values())
    low_consensus = bool(data.get("low_consensus"))
    overrides = data.get("applied_overrides") or []

    st.markdown(
        f"""
<div class="agent-line" style="border-left: 4px solid {color};">
  <strong>Final Weighted Verdict</strong>
  <span style="float:right;color:{color};font-weight:800;">{html.escape(verdict)}</span>
  <div style="color:#94a3b8;margin-top:4px;">Consensus confidence {confidence:.0%}</div>
  <div class="small-context">{html.escape(VERDICT_MEANINGS.get(verdict, ""))}</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    score_cards = []
    for score_verdict in VERDICT_COLORS:
        raw_score = max(0.0, safe_float(scores.get(score_verdict)))
        share = raw_score / total_score if total_score else 0.0
        score_color = VERDICT_COLORS[score_verdict]
        score_cards.append(
            f"""
<div class="consensus-item">
  <div class="score-label">{html.escape(score_verdict)}</div>
  <div class="briefing-value">{share:.0%} weighted support</div>
  <div class="score-track"><div class="score-fill" style="width:{int(share * 100)}%;background:{score_color};"></div></div>
  <div class="small-context">{html.escape(VERDICT_MEANINGS.get(score_verdict, ""))}</div>
</div>
            """
        )
    st.markdown(
        f'<div class="consensus-grid">{"".join(score_cards)}</div>',
        unsafe_allow_html=True,
    )

    if low_consensus:
        st.warning("Low consensus: the top verdict was close to the runner-up, so the result should be treated cautiously.")
    if overrides:
        override_text = {
            "low_data_blocks_scale": "Scale was blocked because the data volume is too thin.",
            "fatigue_pause_blocks_scale": "Scale was blocked because the Fatigue Detective found a strong fatigue signal.",
            "risk_officer_blocks_scale": "Scale was blocked because the Risk Officer found a brand or compliance risk.",
            "no_agents_available": "No live agents were available, so the safest verdict is TEST_NEXT.",
        }
        for override in overrides:
            st.info(override_text.get(str(override), str(override).replace("_", " ")))


def transcript_block_meta(block: dict[str, Any]) -> dict[str, str]:
    round_num = block.get("round")
    block_type = block.get("type")
    data = block.get("data", [])

    if isinstance(data, list):
        item_count = len(data)
        item_label = "items"
    elif block_type == "task":
        item_count = 1
        item_label = "briefing"
    elif block_type == "consensus":
        item_count = 1
        item_label = "result"
    else:
        item_count = 1
        item_label = "item"

    meta = {
        (0, "task"): {
            "label": "Round 0 - Briefing",
            "number": "Round 0",
            "title": "Briefing",
            "short": "Shared context for every agent.",
            "accent": "#8b7cff",
        },
        (1, "opinions"): {
            "label": "Round 1 - Independent Opinions",
            "number": "Round 1",
            "title": "Independent Opinions",
            "short": "Agents vote alone.",
            "accent": "#2ef2a0",
        },
        (2, "challenges"): {
            "label": "Round 2 - Cross-Examination",
            "number": "Round 2",
            "title": "Cross-Examination",
            "short": "Agents challenge weak claims.",
            "accent": "#4dd8ff",
        },
        (3, "revisions"): {
            "label": "Round 3 - Revisions",
            "number": "Round 3",
            "title": "Revisions",
            "short": "Challenged agents answer.",
            "accent": "#ffb020",
        },
        (4, "consensus"): {
            "label": "Round 4 - Consensus",
            "number": "Round 4",
            "title": "Weighted Consensus",
            "short": "The orchestrator decides.",
            "accent": "#b98cff",
        },
        (99, "agent_errors"): {
            "label": "Agent Errors",
            "number": "System",
            "title": "Agent Errors",
            "short": "Fallbacks used where needed.",
            "accent": "#ff5b7a",
        },
    }.get(
        (round_num, block_type),
        {
            "label": f"Round {round_num} - {block_type}",
            "number": f"Round {round_num}",
            "title": str(block_type).replace("_", " ").title(),
            "short": f"{item_count} {item_label}",
            "accent": "#94a3b8",
        },
    )

    return {
        **meta,
        "count": str(item_count),
        "item_label": item_label,
        "id": f"{round_num}:{block_type}",
    }


def render_transcript_block_content(block_type: str, data: Any) -> None:
    render_round_note(block_type)
    if block_type in {"opinions", "revisions"}:
        for op in data:
            render_opinion(op, highlight_change=(block_type == "revisions"))
    elif block_type == "challenges":
        for msg in data:
            render_challenge(msg)
    elif block_type == "task" and isinstance(data, dict):
        render_briefing(data)
    elif block_type == "consensus" and isinstance(data, dict):
        render_consensus(data)
    elif block_type == "agent_errors" and isinstance(data, list):
        render_agent_errors(data)
    else:
        st.caption("This transcript block is not currently rendered in the executive view.")


def render_transcript(transcript: list[dict[str, Any]]) -> None:
    blocks = [block for block in transcript if block.get("data") not in (None, [], {})]
    if not blocks:
        st.info("No transcript available yet.")
        return

    metas = [transcript_block_meta(block) for block in blocks]
    available_ids = {meta["id"] for meta in metas}
    active_id = st.session_state.get("active_transcript_block")
    if active_id not in available_ids:
        default_meta = next((meta for meta in metas if meta["id"].startswith("1:")), metas[0])
        active_id = default_meta["id"]
        st.session_state["active_transcript_block"] = active_id

    for row_start in range(0, len(blocks), 2):
        cols = st.columns(2)
        for col, block, meta in zip(cols, blocks[row_start: row_start + 2], metas[row_start: row_start + 2]):
            is_active = meta["id"] == active_id
            tile_class = "round-tile round-tile-active" if is_active else "round-tile"
            with col:
                st.markdown(
                    f"""
<div class="{tile_class}" style="border-left:4px solid {meta['accent']};">
  <div class="round-number">{html.escape(meta['number'])}</div>
  <div class="round-title">{html.escape(meta['title'])}</div>
  <div class="round-short">{html.escape(meta['short'])}</div>
  <div class="small-context">{html.escape(meta['count'])} {html.escape(meta['item_label'])}</div>
</div>
                    """,
                    unsafe_allow_html=True,
                )
                button_label = f"Viewing {meta['number']}" if is_active else f"Open {meta['number']}"
                if st.button(button_label, key=f"transcript_block_{meta['id']}", use_container_width=True):
                    st.session_state["active_transcript_block"] = meta["id"]
                    st.rerun()

    active_block = next((block for block, meta in zip(blocks, metas) if meta["id"] == active_id), blocks[0])
    active_meta = transcript_block_meta(active_block)
    st.markdown(
        f"""
<div class="transcript-detail">
  <div class="transcript-detail-title">{html.escape(active_meta['label'])}</div>
</div>
        """,
        unsafe_allow_html=True,
    )
    render_transcript_block_content(str(active_block.get("type")), active_block.get("data"))


def render_final_verdict_hero(result: dict[str, Any]) -> None:
    verdict_card = result.get("verdict_card") or result.get("synthesis") or {}
    verdict = str(verdict_card.get("verdict") or result.get("weighted_verdict") or "TEST_NEXT")
    color = VERDICT_COLORS.get(verdict, "#94a3b8")
    confidence = safe_float((result.get("consensus") or {}).get("confidence"))
    reasons = verdict_reasons(result, limit=3)
    if not reasons:
        reasons = [VERDICT_MEANINGS.get(verdict, "Final recommendation from weighted agent consensus.")]

    reason_rows = "".join(
        f"""<div class="verdict-reason-row">
  <div class="verdict-reason-dot" style="background:{color};box-shadow:0 0 8px {color};"></div>
  <div class="verdict-reason-text">{html.escape(r)}</div>
</div>"""
        for r in reasons
    )
    dissent = dissent_summary(result)
    dissent_html = (
        f'<div style="margin-top:14px;padding:10px 14px;border-radius:12px;'
        f'background:rgba(148,163,184,0.07);border:1px solid rgba(148,163,184,0.15);'
        f'color:#9fb1c8;font-size:0.87rem;max-width:520px;margin-left:auto;margin-right:auto;">'
        f'<strong style="color:#e5edf8;">Dissent:</strong> {html.escape(dissent)}</div>'
        if dissent else ""
    )

    st.markdown(
        f"""
<div class="verdict-hero" style="border:1px solid {color};background:radial-gradient(circle at 50% 30%,{color}18 0%,transparent 55%),linear-gradient(180deg,rgba(15,23,42,0.92),rgba(2,6,23,0.84));box-shadow:0 0 60px {color}28,0 28px 80px rgba(0,0,0,0.45);">
  <div class="verdict-hero-eyebrow" style="color:{color};">Boardroom Verdict</div>
  <div class="verdict-hero-label" style="font-size:clamp(2.6rem,5vw,4.2rem);color:{color};">{html.escape(verdict)}</div>
  <div class="verdict-hero-sub">{html.escape(agreement_text(result))} — {int(confidence * 100)}% agent confidence</div>
  <div class="verdict-hero-reasons">{reason_rows}</div>
  {dissent_html}
</div>
        """,
        unsafe_allow_html=True,
    )


def render_boardroom_result(result: dict[str, Any]) -> None:
    verdict_card = result.get("verdict_card") or result.get("synthesis") or {}
    verdict = str(verdict_card.get("verdict") or result.get("weighted_verdict") or "TEST_NEXT")
    render_final_verdict_hero(result)
    reasons = verdict_reasons(result, limit=4)
    if not reasons:
        reasons = [plain_language(VERDICT_MEANINGS.get(verdict, "The agents found a clear enough pattern to recommend this action."))]
    reason_html = "".join(f"<li>{html.escape(reason)}</li>" for reason in reasons)
    hypotheses = creative_change_hypotheses(result)
    hypothesis_html = "".join(
        f"""
<div class="hypothesis-card">
  <strong>{html.escape(title)}</strong>
  {html.escape(explanation)}
</div>
        """
        for title, explanation in hypotheses
    )
    dissent = dissent_summary(result)
    dissent_html = (
        f'<div class="small-context"><strong>Different views in the room:</strong> {html.escape(dissent)}</div>'
        if dissent
        else ""
    )

    st.markdown(
        f"""
<div class="decision-panel">
  <h4>Decision Explanation</h4>
  <div class="small-context">{html.escape(agreement_text(result))}</div>
  <ul class="plain-list">{reason_html}</ul>
  {dissent_html}
</div>
<div class="decision-panel">
  <h4>Recommended Creative Changes</h4>
  <div class="small-context">{html.escape(plain_next_action(verdict))}</div>
  <div style="margin-top:12px;">{hypothesis_html}</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    details_key = f"show_debate_details_{result.get('debate_id') or result.get('creative_id') or 'latest'}"
    show_details = bool(st.session_state.get(details_key, False))
    button_label = "Hide details" if show_details else "View more details"
    st.markdown("#### Debate Details")
    st.button(
        button_label,
        key=f"{details_key}_button",
        use_container_width=True,
        on_click=toggle_session_bool,
        args=(details_key,),
    )

    if show_details:
        render_transcript(result.get("transcript", []))
    else:
        st.caption("Round-by-round details are hidden to keep the main view clean.")


def render_round_overview() -> None:
    active_round = st.session_state.get("active_round_info")
    st.markdown("#### Debate Flow")
    st.caption("Select a round to see what happens at that stage. Opening one round closes the previous one.")

    for row_start in (0, 2):
        cols = st.columns(2)
        for col, step in zip(cols, BOARDROOM_ROUNDS[row_start: row_start + 2]):
            number = step["number"]
            is_active = active_round == number
            tile_class = "round-tile round-tile-active" if is_active else "round-tile"
            with col:
                st.markdown(
                    f"""
<div class="{tile_class}" style="border-left:4px solid {step['accent']};">
  <div class="round-number">Round {number}</div>
  <div class="round-title">{html.escape(step['title'])}</div>
  <div class="round-short">{html.escape(step['short'])}</div>
</div>
                    """,
                    unsafe_allow_html=True,
                )
                button_label = (
                    f"Close Round {number}"
                    if is_active
                    else f"Round {number}: {step['title']}"
                )
                if st.button(button_label, key=f"round_info_{number}", use_container_width=True):
                    st.session_state["active_round_info"] = None if is_active else number
                    st.rerun()
                if is_active:
                    st.markdown(
                        f"""
<div class="round-detail">
  {html.escape(step['detail'])}
</div>
                        """,
                        unsafe_allow_html=True,
                    )


def node_key(agent: Any) -> str:
    key = str(agent or "orchestrator")
    return AGENT_NODE_KEYS.get(key, key.replace("_", "-"))


def communication_lines(from_agent: Any, to_agent: Any) -> list[str]:
    source = node_key(from_agent)
    target = node_key(to_agent)
    if to_agent in (None, "", "ALL"):
        return list(LINE_KEYS)
    if source == "orchestrator" and target in LINE_KEYS:
        return [target]
    if target == "orchestrator" and source in LINE_KEYS:
        return [source]
    lines = [line for line in (source, target) if line in LINE_KEYS]
    return list(dict.fromkeys(lines))


def node_css(source: str | None, target_agent: str | None, node: str) -> str:
    classes = []
    if source == node:
        classes.append("active-node")
    if target_agent == node:
        classes.append("target-node")
    return (" " + " ".join(classes)) if classes else ""


def active_line_css(active_lines: list[str], target: str) -> str:
    return " active-line" if target in active_lines else ""


def plain_language(text: Any) -> str:
    value = str(text or "").strip()
    replacements = [
        (r"\bCTR\b", "click interest"),
        (r"\bIPM\b", "install pull"),
        (r"\bROAS\b", "business return"),
        (r"\bCVR\b", "conversion quality"),
        (r"\bCTA\b", "call-to-action"),
        (r"below the\s+\d+(?:st|nd|rd|th)?\s+percentile", "weaker than most other ads in this campaign"),
        (r"above the\s+\d+(?:st|nd|rd|th)?\s+percentile", "stronger than most other ads in this campaign"),
        (r"top\s+\d+%", "among the stronger ads"),
        (r"last\s+\d+\s+days", "recently"),
        (r"first\s+\d+\s+days", "at launch"),
        (r"\bpercentile\b", "campaign ranking"),
        (r"\bconfidence\b", "agent agreement"),
        (r"\bdecay\b", "loss of attention"),
        (r"\bfatigue\b", "audience tiredness"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    value = re.sub(r"\b\d+(?:\.\d+)?\s?%?\b", "", value)
    value = re.sub(r"\s+", " ", value)
    value = value.replace(" .", ".").replace(" ,", ",").strip(" -:")
    if not value:
        return "The agents found a useful signal, but it needs to be interpreted cautiously."
    return value[0].upper() + value[1:]


def agreement_text(result: dict[str, Any]) -> str:
    confidence = safe_float((result.get("consensus") or {}).get("confidence"))
    if confidence >= 0.75:
        return "Agent agreement feels strong."
    if confidence >= 0.55:
        return "Agent agreement is moderate, so treat the decision as directional."
    return "Agents were split, so this should be handled as a cautious recommendation."


def plain_next_action(verdict: str) -> str:
    return {
        "SCALE": "Keep using this ad, but watch for signs that the audience starts getting tired of it.",
        "PAUSE": "Stop pushing this exact version and refresh the creative before spending more.",
        "PIVOT": "Keep the learning, but change the creative angle before the next test.",
        "TEST_NEXT": "Run a small controlled test before making a bigger decision.",
    }.get(verdict, "Use this as a directional recommendation and validate it with the next test.")


def signal_strength(value: Any) -> str:
    score = safe_float(value, 0.5)
    if score >= 0.75:
        return "Strong"
    if score <= 0.25:
        return "Weak"
    return "Mixed"


def spend_pressure(value: Any) -> str:
    share = safe_float(value, 0.0)
    if share >= 0.5:
        return "High"
    if share >= 0.2:
        return "Moderate"
    return "Low"


def verdict_reasons(result: dict[str, Any], limit: int = 3) -> list[str]:
    verdict_card = result.get("verdict_card") or result.get("synthesis") or {}
    verdict = verdict_card.get("verdict") or result.get("weighted_verdict")
    bullets = [str(item) for item in verdict_card.get("evidence_bullets", []) if item]
    if bullets:
        return [plain_language(item) for item in bullets[:limit]]

    final_opinions = result.get("final_opinions") or []
    aligned = [op for op in final_opinions if op.get("verdict") == verdict]
    reasons: list[str] = []
    for opinion in aligned or final_opinions:
        claims = opinion.get("claims") or []
        if claims:
            reasons.append(plain_language(claims[0]))
        if len(reasons) >= limit:
            break
    return reasons


def dissent_summary(result: dict[str, Any]) -> str | None:
    verdict_card = result.get("verdict_card") or result.get("synthesis") or {}
    dissent = verdict_card.get("dissent")
    if dissent:
        text = str(dissent)
        for agent, (name, _) in AGENT_META.items():
            text = text.replace(agent, name)
        return text
    final_opinions = result.get("final_opinions") or []
    verdict = verdict_card.get("verdict") or result.get("weighted_verdict")
    dissenters = [
        f"{agent_display(op.get('agent'))[0]}: {op.get('verdict')}"
        for op in final_opinions
        if op.get("verdict") != verdict
    ]
    return ", ".join(dissenters) if dissenters else None


def creative_change_hypotheses(result: dict[str, Any]) -> list[tuple[str, str]]:
    verdict_card = result.get("verdict_card") or result.get("synthesis") or {}
    verdict = str(verdict_card.get("verdict") or result.get("weighted_verdict") or "TEST_NEXT")
    if verdict == "SCALE":
        return [
            (
                "Keep the winning structure, create a fresh opening.",
                "Hypothesis: the current idea is working, but a new first moment can delay audience tiredness.",
            ),
            (
                "Make one bolder version of the offer.",
                "Hypothesis: if the promise is clearer faster, the same audience may respond even better.",
            ),
        ]
    if verdict == "PAUSE":
        return [
            (
                "Refresh the first second of the ad.",
                "Hypothesis: people may be skipping because the opening feels familiar or too easy to ignore.",
            ),
            (
                "Give the call-to-action stronger contrast and clearer placement.",
                "Hypothesis: if the next step is easier to notice, interested viewers are less likely to drop off.",
            ),
            (
                "Test a new emotional hook instead of reusing the same angle.",
                "Hypothesis: the audience may still like the product, but this specific presentation has lost attention.",
            ),
        ]
    if verdict == "PIVOT":
        return [
            (
                "Change the story angle while keeping the same product promise.",
                "Hypothesis: the offer may be valid, but the current framing is not making people care enough.",
            ),
            (
                "Create one audience-specific version.",
                "Hypothesis: a message written for a clearer viewer type should feel more relevant and less generic.",
            ),
        ]
    return [
        (
            "Run a cleaner challenger creative.",
            "Hypothesis: the current evidence is not decisive enough, so a controlled comparison will reveal whether the idea deserves more spend.",
        ),
        (
            "Change only one major element in the next version.",
            "Hypothesis: testing one clear change makes it easier to understand what actually improved.",
        ),
    ]


def render_compact_creative_panel(creative: dict[str, Any], result: dict[str, Any] | None = None) -> None:
    creative_id = str(creative.get("creative_id", "unknown"))
    image_uri = image_to_data_uri(creative.get("image_path"))
    title = f"Creative {html.escape(creative_id)}"
    image_html = (
        f'<div class="boardroom-asset-frame"><img class="boardroom-creative-img" src="{image_uri}" alt="{title}"></div>'
        if image_uri
        else f'<div class="boardroom-asset-frame creative-placeholder">{title}</div>'
    )

    verdict_html = ""
    if result:
        verdict_card = result.get("verdict_card") or result.get("synthesis") or {}
        verdict = verdict_card.get("verdict") or result.get("weighted_verdict") or "TEST_NEXT"
        color = VERDICT_COLORS.get(str(verdict), "#94a3b8")
        confidence_text = agreement_text(result)
        reasons = verdict_reasons(result, limit=3)
        if not reasons:
            reasons = [VERDICT_MEANINGS.get(str(verdict), "Final recommendation from weighted agent consensus.")]
        reason_items = "".join(f"<li>{html.escape(reason)}</li>" for reason in reasons)
        dissent = dissent_summary(result)
        dissent_html = (
            f'<div class="small-context"><strong>Why not unanimous:</strong> {html.escape(dissent)}</div>'
            if dissent
            else ""
        )
        verdict_html = f"""
  <div class="compact-verdict">
    <div class="mini-label">Boardroom verdict</div>
    <div class="compact-verdict-label" style="color:{color};margin-top:8px;">{html.escape(str(verdict))}</div>
    <div class="small-context">{html.escape(confidence_text)}</div>
    <div class="compact-verdict-reasons">
      <strong>Why this recommendation</strong>
      <ul>{reason_items}</ul>
    </div>
    {dissent_html}
  </div>
        """

    st.markdown(
        f"""
<div class="boardroom-creative-card">
  {image_html}
  <div class="creative-title">
    <div>
      <div class="creative-id">{title}</div>
      <div style="color:#94a3b8;font-size:0.86rem;">{html.escape(str(creative.get("format") or "unknown"))} - {html.escape(str(creative.get("theme") or creative.get("primary_theme") or "unknown"))}</div>
    </div>
  </div>
  <div class="compact-metric-row">
    <div class="compact-metric">
      <div class="mini-label">Audience interest</div>
      <div class="mini-value">{signal_strength(creative.get("ctr_pct"))}</div>
    </div>
    <div class="compact-metric">
      <div class="mini-label">Install pull</div>
      <div class="mini-value">{signal_strength(creative.get("ipm_pct"))}</div>
    </div>
    <div class="compact-metric">
      <div class="mini-label">Budget pressure</div>
      <div class="mini-value">{spend_pressure(creative.get("spend_share_pct"))}</div>
    </div>
  </div>
  {verdict_html}
</div>
        """,
        unsafe_allow_html=True,
    )


def render_loading_boardroom(
    creative_id: str,
    phase: dict[str, Any] | None = None,
    *,
    completed: bool = False,
) -> None:
    phase = phase or {}
    source = node_key(phase.get("from_agent") or phase.get("active") or ("orchestrator" if completed else ""))
    target = node_key(phase.get("to_agent")) if phase.get("to_agent") not in (None, "", "ALL") else None
    explicit_lines = phase.get("lines")
    if isinstance(explicit_lines, list):
        active_lines = [str(line) for line in explicit_lines]
    else:
        active_lines = communication_lines(phase.get("from_agent"), phase.get("to_agent"))
    status_title = "Boardroom complete" if completed else "Boardroom in session"
    status_copy = (
        "Consensus is ready below."
        if completed
        else str(phase.get("text") or "Agents are exchanging evidence.")
    )
    route = phase.get("route")
    route_html = (
        f'<span class="loading-route">{html.escape(str(route))}</span>'
        if route
        else ""
    )
    st.markdown(
        f"""
<div class="loading-boardroom">
  <div class="loading-title">
    <strong>{html.escape(status_title)}</strong>
    <span class="loading-creative">Creative {html.escape(creative_id)}</span>
    {route_html}
    <span class="loading-copy">{html.escape(status_copy)}</span>
  </div>
  <div class="boardroom-stage">
    <svg class="connection-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <line class="connector-line{active_line_css(active_lines, "performance")}" x1="50" y1="50" x2="21" y2="18"></line>
      <line class="connector-line{active_line_css(active_lines, "fatigue")}" x1="50" y1="50" x2="79" y2="18"></line>
      <line class="connector-line{active_line_css(active_lines, "visual")}" x1="50" y1="50" x2="21" y2="68"></line>
      <line class="connector-line{active_line_css(active_lines, "risk")}" x1="50" y1="50" x2="79" y2="68"></line>
      <line class="connector-line{active_line_css(active_lines, "audience")}" x1="50" y1="50" x2="50" y2="88"></line>
    </svg>
    <div class="table-orbit"></div>
    <div class="moderator-node{node_css(source, target, "orchestrator")}">
      <strong>Orchestrator</strong>
      <span>routes rounds and consensus</span>
    </div>
    <div class="agent-node agent-performance{node_css(source, target, "performance")}">
      <strong>Performance Analyst</strong>
      <span>interest, installs, return</span>
    </div>
    <div class="agent-node agent-fatigue{node_css(source, target, "fatigue")}">
      <strong>Fatigue Detective</strong>
      <span>decay and active days</span>
    </div>
    <div class="agent-node agent-visual{node_css(source, target, "visual")}">
      <strong>Visual Critic</strong>
      <span>layout and attention</span>
    </div>
    <div class="agent-node agent-risk{node_css(source, target, "risk")}">
      <strong>Risk Officer</strong>
      <span>brand safety</span>
    </div>
    <div class="agent-node agent-audience{node_css(source, target, "audience")}">
      <strong>Audience Simulator</strong>
      <span>fit and motivation</span>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_live_feed(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    event_html = "".join(
        f"""
<div class="live-event">
  <span>{html.escape(str(event.get("round", "")))} - {html.escape(str(event.get("agent", "")))}</span>
  <div class="live-route">{html.escape(str(event.get("route", "")))}</div>
  {html.escape(str(event.get("text", "")))}
</div>
        """
        for event in events
    )
    st.markdown(
        f"""
<div class="live-feed">
  {event_html}
</div>
        """,
        unsafe_allow_html=True,
    )


def route_name(agent: Any) -> str:
    if agent in (None, "", "ALL"):
        return "All agents"
    return agent_display(agent)[0] if str(agent) in AGENT_META else str(agent).replace("_", " ").title()


def route_label(from_agent: Any, to_agent: Any) -> str:
    return f"{route_name(from_agent)} -> {route_name(to_agent)}"


def purpose_text(purpose: Any) -> str:
    return {
        "request_independent_opinion": "asking for a first independent recommendation",
        "request_cross_examination": "asking this agent to challenge or support other views",
        "request_revision_after_challenge": "asking this agent to respond to a challenge",
    }.get(str(purpose), "asking for the next contribution")


def phase_progress(round_num: Any, event_type: str) -> int:
    try:
        round_int = int(round_num)
    except (TypeError, ValueError):
        round_int = 0
    if event_type == "synthesis":
        return 98
    return {
        0: 8,
        1: 28,
        2: 56,
        3: 78,
        4: 96,
        99: 92,
    }.get(round_int, 18)


def event_to_live_phases(event: dict[str, Any]) -> list[dict[str, Any]]:
    event_type = str(event.get("type", "event"))
    round_num = event.get("round", "?")
    payload = event.get("payload")
    event_agent = event.get("agent") or "orchestrator"
    progress = phase_progress(round_num, event_type)

    if event_type == "task":
        return [{
            "progress": progress,
            "round": f"Round {round_num}",
            "agent": "Orchestrator",
            "from_agent": "orchestrator",
            "to_agent": "ALL",
            "route": route_label("orchestrator", "ALL"),
            "text": "Briefing sent: creative context and image reference are now available to all agents.",
        }]

    if event_type == "agents":
        return [{
            "progress": max(progress, 12),
            "round": "Discovery",
            "agent": "Orchestrator",
            "from_agent": "orchestrator",
            "to_agent": "ALL",
            "route": route_label("orchestrator", "ALL"),
            "text": "All available agents have entered the boardroom.",
        }]

    if event_type == "agent_call" and isinstance(payload, dict):
        from_agent = payload.get("from_agent") or "orchestrator"
        to_agent = payload.get("to_agent") or event_agent
        return [{
            "progress": progress,
            "round": f"Round {round_num}",
            "agent": route_name(from_agent),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "route": route_label(from_agent, to_agent),
            "text": f"Request sent: {purpose_text(payload.get('purpose'))}. Waiting for {route_name(to_agent)} to respond.",
        }]

    if event_type in {"opinion", "revision"} and isinstance(payload, dict):
        agent = payload.get("agent") or event_agent
        verdict = payload.get("verdict", "UNKNOWN")
        claims = payload.get("claims") or []
        first_claim = plain_language(claims[0]) if claims else "The agent gave its recommendation without an extra explanation."
        changed_from = payload.get("changed_from")
        if changed_from:
            text = f"Changes its recommendation from {changed_from} to {verdict}. Reason: {first_claim}"
        else:
            verb = "revises" if event_type == "revision" else "submits"
            text = f"{verb.title()} recommendation: {verdict}. Reason: {first_claim}"
        return [{
            "progress": progress,
            "round": f"Round {round_num}",
            "agent": route_name(agent),
            "from_agent": agent,
            "to_agent": "orchestrator",
            "route": route_label(agent, "orchestrator"),
            "text": text,
        }]

    if event_type == "messages" and isinstance(payload, list):
        phases = []
        for index, message in enumerate(payload):
            from_agent = message.get("from_agent") or event_agent
            to_agent = message.get("to_agent") or "ALL"
            body = plain_language(message.get("body") or "Message sent.")
            msg_type = str(message.get("type", "message")).replace("_", " ")
            phases.append({
                "progress": min(74, progress + index),
                "round": f"Round {round_num}",
                "agent": route_name(from_agent),
                "from_agent": from_agent,
                "to_agent": to_agent,
                "route": route_label(from_agent, to_agent),
                "text": f"{msg_type.title()}: {body}",
            })
        return phases

    if event_type in {"agent_error", "server_error"}:
        error_text = payload.get("error") if isinstance(payload, dict) else str(payload)
        return [{
            "progress": progress,
            "round": f"Round {round_num}",
            "agent": route_name(event_agent),
            "from_agent": event_agent,
            "to_agent": "orchestrator",
            "route": route_label(event_agent, "orchestrator"),
            "text": f"Error reported: {error_text}",
        }]

    if event_type == "consensus" and isinstance(payload, dict):
        return [{
            "progress": progress,
            "round": "Round 4",
            "agent": "Orchestrator",
            "from_agent": "orchestrator",
            "to_agent": "ALL",
            "route": route_label("orchestrator", "ALL"),
            "text": "Consensus calculated. The final recommendation is ready to explain.",
        }]

    if event_type == "synthesis":
        return [{
            "progress": progress,
            "round": "Synthesis",
            "agent": "Orchestrator",
            "from_agent": "orchestrator",
            "to_agent": "ALL",
            "route": route_label("orchestrator", "ALL"),
            "text": "Final explanation and next action are being prepared for the marketing decision.",
        }]

    if event_type == "hero_moment" and isinstance(payload, dict):
        agent = payload.get("agent") or "orchestrator"
        return [{
            "progress": 99,
            "round": "Mind Change",
            "agent": route_name(agent),
            "from_agent": agent,
            "to_agent": "orchestrator",
            "route": route_label(agent, "orchestrator"),
            "text": f"{route_name(agent)} changed from {payload.get('changed_from')} to {payload.get('changed_to')}: {payload.get('reason')}",
        }]

    return [{
        "progress": progress,
        "round": f"Round {round_num}",
        "agent": route_name(event_agent),
        "from_agent": event_agent,
        "to_agent": "orchestrator",
        "route": route_label(event_agent, "orchestrator"),
        "text": f"{event_type.replace('_', ' ').title()} event received.",
    }]


def render_live_state(
    table_slot: Any,
    progress_bar: Any,
    feed_slot: Any,
    creative_id: str,
    current_phase: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    completed: bool = False,
) -> None:
    table_slot.empty()
    with table_slot.container():
        render_loading_boardroom(creative_id, current_phase, completed=completed)
    progress_bar.progress(
        int(current_phase.get("progress", 10)),
        text=f"{current_phase.get('round')} - {current_phase.get('route')}",
    )
    feed_slot.empty()
    with feed_slot.container():
        render_live_feed(events)


def live_phases_from_events(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    for raw_event in raw_events:
        phases.extend(event_to_live_phases(raw_event))
    return phases


def render_completed_workflow(creative_id: str, result: dict[str, Any]) -> None:
    phases = live_phases_from_events(result.get("events") or [])
    if not phases:
        return
    final_phase = {
        "progress": 100,
        "round": "Complete",
        "agent": "Orchestrator",
        "from_agent": "orchestrator",
        "to_agent": "ALL",
        "route": route_label("orchestrator", "ALL"),
        "text": "Consensus complete. Final recommendation is ready below.",
    }
    render_loading_boardroom(creative_id, final_phase, completed=True)
    st.progress(100, text="Complete - final recommendation ready")
    render_live_feed(phases + [final_phase])


def run_live_debate(creative_id: str) -> dict[str, Any] | None:
    start_response = requests.post(
        f"{ORCHESTRATOR}/debate/start",
        json={"creative_id": creative_id},
        timeout=10,
    )
    start_response.raise_for_status()
    debate_id = start_response.json()["debate_id"]
    table_slot = st.empty()
    progress_bar = st.progress(0, text="Preparing boardroom")
    feed_slot = st.empty()
    events: list[dict[str, Any]] = []
    seen_event_keys: set[str] = set()
    current_phase: dict[str, Any] = {
        "progress": 4,
        "round": "Starting",
        "agent": "Orchestrator",
        "from_agent": "orchestrator",
        "to_agent": "ALL",
        "route": route_label("orchestrator", "ALL"),
        "text": "Opening the boardroom and waiting for the first agent event.",
    }
    deadline = time.monotonic() + 620

    while time.monotonic() < deadline:
        poll_response = requests.get(f"{ORCHESTRATOR}/debate/{debate_id}", timeout=8)
        if poll_response.status_code == 404:
            payload: dict[str, Any] = {"events": []}
        else:
            poll_response.raise_for_status()
            payload = poll_response.json()

        for raw_event in payload.get("events", []):
            event_id = raw_event.get("id", len(seen_event_keys))
            phases = event_to_live_phases(raw_event)
            for index, phase in enumerate(phases):
                key = f"{event_id}:{index}"
                if key in seen_event_keys:
                    continue
                seen_event_keys.add(key)
                events.append(phase)
                current_phase = phase
                render_live_state(
                    table_slot,
                    progress_bar,
                    feed_slot,
                    creative_id,
                    current_phase,
                    events,
                )
                time.sleep(0.35)

        if payload.get("transcript") and payload.get("consensus"):
            result = payload
            final_phase = {
                "progress": 100,
                "round": "Complete",
                "agent": "Orchestrator",
                "from_agent": "orchestrator",
                "to_agent": "ALL",
                "route": route_label("orchestrator", "ALL"),
                "text": "Consensus complete. Final recommendation is ready below.",
            }
            events.append(final_phase)
            render_live_state(
                table_slot,
                progress_bar,
                feed_slot,
                creative_id,
                final_phase,
                events,
                completed=True,
            )
            return result

        render_live_state(
            table_slot,
            progress_bar,
            feed_slot,
            creative_id,
            current_phase,
            events,
        )

        time.sleep(1.0)

    raise requests.exceptions.Timeout("Live debate polling timed out")


def render_boardroom(creatives: list[dict[str, Any]]) -> None:
    st.markdown('<div class="screen-title">Creative Boardroom</div>', unsafe_allow_html=True)
    st.markdown('<div class="screen-caption">Five AI specialists debate the ad, challenge each other\'s claims, and converge on one actionable verdict.</div>', unsafe_allow_html=True)

    left, right = st.columns([0.58, 1.42], gap="large")
    with left:
        selected = selected_creative_selector(creatives)
        creative_id = str(selected.get("creative_id"))
        result_key = f"result_{creative_id}"
        result = st.session_state.get(result_key)
        ran_live_this_turn = False
        
        creative_panel_slot = st.empty()
        with creative_panel_slot.container():
            render_compact_creative_panel(selected, result)

    with right:
        st.markdown(
            """
<div style="border:1px solid rgba(77,216,255,0.22);border-radius:20px;padding:18px 20px;
  background:linear-gradient(135deg,rgba(77,216,255,0.06),rgba(46,242,160,0.04)),rgba(15,23,42,0.72);
  margin-bottom:14px;box-shadow:0 0 32px rgba(77,216,255,0.06);">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
    <div style="width:8px;height:8px;border-radius:50%;background:#2ef2a0;box-shadow:0 0 10px #2ef2a0;animation:nodePulse 1.4s ease-in-out infinite;"></div>
    <div style="color:#e5edf8;font-size:1.05rem;font-weight:800;">Agent Boardroom</div>
  </div>
  <div style="color:#9fb1c8;font-size:0.88rem;line-height:1.45;">
    5 AI specialists debate the selected creative across 4 rounds — independent opinions,
    cross-examination, revisions, and weighted consensus.
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        with cols[0]:
            run_btn = st.button("▶  Convene the Boardroom", type="primary", use_container_width=True)
        with cols[1]:
            load_cached_btn = st.button("Load Cached Result", use_container_width=True)

        if load_cached_btn:
            try:
                response = requests.get(f"{ORCHESTRATOR}/debate/{creative_id}/result", timeout=8)
                if response.status_code == 200:
                    result = response.json()
                    st.session_state[result_key] = result
                else:
                    st.warning("No cached result found for this creative.")
            except Exception as exc:
                st.error(f"Error loading cached result: {exc}")

        if run_btn:
            try:
                result = run_live_debate(creative_id)
                if result:
                    st.session_state[result_key] = result
                    ran_live_this_turn = True
                    with creative_panel_slot.container():
                        render_compact_creative_panel(selected, result)
            except requests.exceptions.Timeout:
                st.error("Debate timed out. Try loading a cached result or use stub agents for the demo.")
            except Exception as exc:
                st.error(f"Debate failed: {exc}")

        if result:
            with creative_panel_slot.container():
                render_compact_creative_panel(selected, result)
            if not ran_live_this_turn:
                render_completed_workflow(creative_id, result)
            render_boardroom_result(result)
        else:
            st.info("No verdict yet. Start the boardroom to generate the live agent debate and final recommendation.")


def render_navigation() -> str:
    if "active_screen" not in st.session_state:
        st.session_state["active_screen"] = SCREENS[0]
    active_screen = st.session_state["active_screen"]
    with st.container(key="main_nav"):
        cols = st.columns(3, gap="medium")
        for col, screen in zip(cols, SCREENS):
            with col:
                st.button(
                    screen,
                    key=f"nav_{re.sub(r'[^a-z0-9]+', '_', screen.lower()).strip('_')}",
                    type="primary" if screen == active_screen else "secondary",
                    use_container_width=True,
                    on_click=set_active_screen,
                    args=(screen,),
                )
    return st.session_state["active_screen"]


def main() -> None:
    inject_css()
    creatives_raw, using_demo_data = load_campaign_creatives()
    metrics = campaign_metrics(creatives_raw)
    creatives = enrich_creatives(creatives_raw, metrics)

    if not st.session_state.get("selected_creative_id") and creatives:
        st.session_state["selected_creative_id"] = str(creatives[0].get("creative_id"))

    render_header(using_demo_data)
    st.markdown("")
    active_screen = render_navigation()
    st.markdown("")

    if active_screen == "Campaign Overview":
        render_campaign_overview(creatives, metrics)
    elif active_screen == "Creative Analytics":
        render_creative_analytics(creatives, metrics)
    else:
        render_boardroom(creatives)


if __name__ == "__main__":
    main()
