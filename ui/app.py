"""MusicStream ETL Dashboard — Home page.

Run: streamlit run ui/app.py
     MOCK_MODE=true streamlit run ui/app.py  (no AWS credentials needed)
"""

import os
import sys

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Add ui/ to path so lib/ imports work regardless of cwd.
sys.path.insert(0, os.path.dirname(__file__))

MOCK_MODE = os.environ.get("MOCK_MODE", "false").lower() == "true"
ENV = os.environ.get("ENV", "dev")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MusicStream ETL",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .metric-card {
        background: linear-gradient(135deg, #1a1d27 0%, #23263a 100%);
        border: 1px solid #2e3250;
        border-radius: 12px;
        padding: 20px 24px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(108, 99, 255, 0.2);
    }
    .badge-success { color: #4ade80; font-weight: 600; }
    .badge-fail    { color: #f87171; font-weight: 600; }
    .badge-running { color: #fbbf24; font-weight: 600; }

    [data-testid="stSidebar"] {
        background: #0f1117;
        border-right: 1px solid #2e3250;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Mock mode banner ──────────────────────────────────────────────────────────
if MOCK_MODE:
    st.warning("⚡ **Mock mode** — no AWS credentials detected. Showing fixture data.")

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    f"## 🎵 MusicStream ETL Dashboard &nbsp;&nbsp;<small style='color:#6c63ff;font-size:0.75rem;'>[env: {ENV}]</small>",
    unsafe_allow_html=True,
)
st.caption("Real-time analytics pipeline: S3 → Step Functions → Glue → DynamoDB")
st.divider()

# ── Quick stats ───────────────────────────────────────────────────────────────
if MOCK_MODE:
    from lib.mock_data import mock_recent_executions

    executions = mock_recent_executions()
else:
    try:
        from lib.pipeline_ops import list_recent_executions

        executions = list_recent_executions(max_results=20)
    except Exception:
        executions = []

succeeded = sum(1 for e in executions if e.get("status") == "SUCCEEDED")
failed = sum(1 for e in executions if e.get("status") == "FAILED")
running = sum(1 for e in executions if e.get("status") == "RUNNING")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Executions (recent)", len(executions))
with col2:
    st.metric("✅ Succeeded", succeeded)
with col3:
    st.metric("❌ Failed", failed)
with col4:
    st.metric("⏳ Running", running)

st.divider()

# ── Navigation hints ──────────────────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.markdown(
        """
        <div class="metric-card">
            <h3>🔁 Pipeline</h3>
            <p>Upload stream CSVs, trigger the ETL pipeline, and track Stage-by-stage execution progress.</p>
            <p><em>→ Use the sidebar to navigate</em></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col_b:
    st.markdown(
        """
        <div class="metric-card">
            <h3>📊 KPI Dashboard</h3>
            <p>Query daily genre-level KPIs, top songs, and top genres directly from DynamoDB.</p>
            <p><em>→ Use the sidebar to navigate</em></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.divider()
st.caption("MusicStream Streaming Analytics ETL Pipeline · NSS Phase 2 Project 1")
