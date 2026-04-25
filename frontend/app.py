"""
Creative Boardroom — Streamlit frontend.

Usage:
    streamlit run frontend/app.py

Requires the orchestrator to be running at http://localhost:8000.
"""
import json
import time
from pathlib import Path

import requests
import streamlit as st
from PIL import Image

ORCHESTRATOR = "http://localhost:8000"

VERDICT_COLORS = {
    "SCALE": "#22c55e",
    "PAUSE": "#ef4444",
    "PIVOT": "#f59e0b",
    "TEST_NEXT": "#6366f1",
}

VERDICT_ICONS = {
    "SCALE": "📈",
    "PAUSE": "⏸️",
    "PIVOT": "🔄",
    "TEST_NEXT": "🧪",
}

st.set_page_config(
    page_title="Creative Boardroom",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  .verdict-card {
    border-radius: 12px;
    padding: 24px 32px;
    margin-bottom: 16px;
    text-align: center;
  }
  .verdict-label {
    font-size: 3rem;
    font-weight: 800;
    letter-spacing: 0.05em;
  }
  .agent-name { font-weight: 700; }
  .round-badge {
    display: inline-block;
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 0.75rem;
    font-weight: 600;
    margin-right: 6px;
  }
  .changed-verdict {
    background: #fef08a;
    border-left: 4px solid #eab308;
    padding: 8px 12px;
    border-radius: 4px;
    margin: 6px 0;
  }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=30)
def fetch_creatives():
    try:
        r = requests.get(f"{ORCHESTRATOR}/creatives", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Cannot reach orchestrator at {ORCHESTRATOR}: {e}")
        return []


def fmt_pct(val, decimals=2):
    if val is None:
        return "N/A"
    return f"{val:.{decimals}%}"


def fmt_num(val, decimals=4):
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}"


def percentile_delta(pct):
    """Return a coloured delta label from a percentile value (0-1)."""
    if pct is None:
        return "N/A"
    pct_int = int(pct * 100)
    return f"P{pct_int} in campaign"


def render_metric_card(label, value, pct, help_text=""):
    pct_val = pct or 0.0
    color = "#22c55e" if pct_val >= 0.75 else ("#ef4444" if pct_val <= 0.25 else "#f59e0b")
    st.metric(
        label=label,
        value=value,
        delta=percentile_delta(pct),
        help=help_text,
    )


def render_opinion(op: dict, highlight_change: bool = True):
    agent = op.get("agent", "unknown")
    verdict = op.get("verdict", "?")
    confidence = op.get("confidence", 0)
    claims = op.get("claims", [])
    changed_from = op.get("changed_from")
    round_num = op.get("round", 1)

    verdict_color = VERDICT_COLORS.get(verdict, "#64748b")
    verdict_icon = VERDICT_ICONS.get(verdict, "❓")

    if changed_from and highlight_change:
        st.success(
            f"⚡ **{agent}** changed verdict: "
            f"**{changed_from}** → **{verdict}** (confidence {confidence:.0%})"
        )
    else:
        st.markdown(
            f"**{agent}** → "
            f'<span style="color:{verdict_color};font-weight:700">{verdict_icon} {verdict}</span> '
            f"({confidence:.0%} confidence)",
            unsafe_allow_html=True,
        )

    for claim in claims:
        st.markdown(f"  - {claim}")


def render_transcript(transcript: list):
    for block in transcript:
        round_num = block.get("round")
        block_type = block.get("type")
        data = block.get("data", [])

        if not data:
            continue

        label = {
            (1, "opinions"): "Round 1 — Independent Opinions",
            (2, "challenges"): "Round 2 — Cross-Examination",
            (3, "revisions"): "Round 3 — Revisions",
        }.get((round_num, block_type), f"Round {round_num}")

        with st.expander(
            f"**{label}** ({len(data)} items)",
            expanded=(round_num == 3 and bool(data)),
        ):
            if block_type == "opinions":
                for op in data:
                    render_opinion(op, highlight_change=False)
                    st.divider()

            elif block_type == "challenges":
                for msg in data:
                    msg_type = msg.get("type", "")
                    color = "#f59e0b" if msg_type in ("challenge", "evidence_request") else "#6366f1"
                    icon = "🔴" if msg_type == "challenge" else ("🟡" if msg_type == "evidence_request" else "🟢")
                    st.markdown(
                        f"{icon} **{msg.get('from_agent')}** → **{msg.get('to_agent')}** "
                        f'<span style="color:{color}">({msg_type})</span>: {msg.get("body", "")}',
                        unsafe_allow_html=True,
                    )

            elif block_type == "revisions":
                if not data:
                    st.info("No agents revised their opinion in this round.")
                for op in data:
                    render_opinion(op, highlight_change=True)
                    st.divider()


# ─── Layout ───────────────────────────────────────────────────────────────────

st.title("🎯 Creative Boardroom")
st.caption("AI-powered creative decision copilot · Powered by Claude + A2A protocol")

creatives = fetch_creatives()

if not creatives:
    st.warning("No creatives loaded. Make sure the orchestrator is running and pipeline/build_table.py has been run.")
    st.stop()

left, right = st.columns([1, 1.6], gap="large")

with left:
    st.subheader("Select Creative")

    creative_options = {
        f"{c['creative_id']} · {c.get('format','?')} · {c.get('theme','?')} · {c.get('creative_status','?')}": c
        for c in creatives
    }
    selected_label = st.selectbox("Creative", list(creative_options.keys()), label_visibility="collapsed")
    selected = creative_options[selected_label]
    creative_id = selected["creative_id"]

    image_path = selected.get("image_path", "")
    if image_path and Path(image_path).exists():
        try:
            img = Image.open(image_path)
            st.image(img, use_column_width=True)
        except Exception:
            st.warning("Could not load image.")
    else:
        st.info("Image not available.")

    st.subheader("Key Metrics")
    m1, m2 = st.columns(2)
    with m1:
        st.metric("CTR", fmt_pct(selected.get("ctr"), 3), percentile_delta(selected.get("ctr_pct")))
        st.metric("CVR", fmt_pct(selected.get("cvr"), 3), percentile_delta(selected.get("cvr_pct")))
    with m2:
        st.metric("IPM", fmt_num(selected.get("ipm"), 3), percentile_delta(selected.get("ipm_pct")))
        spend = selected.get("spend")
        st.metric("Spend", f"${spend:,.0f}" if spend else "N/A", percentile_delta(selected.get("spend_pct")))

    st.markdown(f"**Status:** `{selected.get('creative_status', 'N/A')}`  "
                f"**Format:** `{selected.get('format', 'N/A')}`  "
                f"**Language:** `{selected.get('language', 'N/A')}`")

    st.divider()

    run_btn = st.button(
        "🏛️ Convene the Boardroom",
        type="primary",
        use_container_width=True,
        help="Runs a full 4-round AI debate for this creative. May take several minutes on low API rate limits.",
    )

    load_cached_btn = st.button(
        "📁 Load Cached Result",
        use_container_width=True,
        help="Load the most recent cached debate result for this creative.",
    )

with right:
    result_placeholder = st.empty()

    # ── Handle cached load ──────────────────────────────────────────────────
    if load_cached_btn:
        try:
            r = requests.get(f"{ORCHESTRATOR}/debate/{creative_id}/result", timeout=5)
            if r.status_code == 200:
                st.session_state[f"result_{creative_id}"] = r.json()
            else:
                st.warning("No cached result found for this creative. Run the boardroom first.")
        except Exception as e:
            st.error(f"Error loading cached result: {e}")

    # ── Handle live debate ──────────────────────────────────────────────────
    if run_btn:
        with result_placeholder.container():
            progress = st.progress(0, text="Convening the boardroom…")
            status = st.empty()

            try:
                status.info("⏳ Round 1 — Agents forming independent opinions…")
                progress.progress(20)

                r = requests.post(
                    f"{ORCHESTRATOR}/debate",
                    json={"creative_id": creative_id},
                    timeout=600,
                )
                r.raise_for_status()
                debate_result = r.json()
                st.session_state[f"result_{creative_id}"] = debate_result
                progress.progress(100, text="Complete!")
                status.empty()
            except requests.exceptions.Timeout:
                st.error("Debate timed out (>120s). Try loading a cached result.")
            except Exception as e:
                st.error(f"Debate failed: {e}")

    # ── Render result ───────────────────────────────────────────────────────
    result = st.session_state.get(f"result_{creative_id}")
    if result:
        verdict_card = result.get("verdict_card", {})
        verdict = verdict_card.get("verdict", result.get("weighted_verdict", "?"))
        headline = verdict_card.get("headline", "")
        bullets = verdict_card.get("evidence_bullets", [])
        dissent = verdict_card.get("dissent")
        next_action = verdict_card.get("next_action", "")

        color = VERDICT_COLORS.get(verdict, "#64748b")
        icon = VERDICT_ICONS.get(verdict, "❓")

        # Verdict card
        st.markdown(
            f"""<div class="verdict-card" style="background:{color}22;border:2px solid {color}">
              <div class="verdict-label" style="color:{color}">{icon} {verdict}</div>
            </div>""",
            unsafe_allow_html=True,
        )

        final_opinions = result.get("final_opinions", [])
        confidence_avg = (
            sum(o.get("confidence", 0) for o in final_opinions) / len(final_opinions)
            if final_opinions else 0
        )
        st.markdown(f"**{headline}**")
        st.caption(f"Average agent confidence: {confidence_avg:.0%} · {len(final_opinions)} agents participated")

        if bullets:
            st.subheader("Evidence")
            for b in bullets:
                st.markdown(f"- {b}")

        if dissent:
            st.warning(f"**Dissent:** {dissent}")

        if next_action:
            st.info(f"**Next action:** {next_action}")

        # Hero moment highlight
        heroes = [o for o in final_opinions if o.get("changed_from")]
        if heroes:
            st.subheader("⚡ Mind Changes")
            for op in heroes:
                st.success(
                    f"⚡ **{op['agent']}** changed verdict: "
                    f"**{op['changed_from']}** → **{op['verdict']}**"
                )

        # Full transcript
        st.subheader("Full Debate Transcript")
        transcript = result.get("transcript", [])
        render_transcript(transcript)

        # Raw JSON expander for debugging
        with st.expander("Raw JSON result"):
            st.json(result)
    else:
        st.subheader("Boardroom Results")
        st.info("Select a creative and click **Convene the Boardroom** to start the AI debate.")
        st.markdown("""
**What happens when you convene:**
1. **Round 1** — 5 specialist agents independently analyze this creative
2. **Round 2** — Agents challenge each other's claims
3. **Round 3** — Challenged agents revise or defend their position
4. **Synthesis** — A weighted verdict with full reasoning is produced

The hero moment is when an agent **changes its mind** based on another agent's evidence.
""")
