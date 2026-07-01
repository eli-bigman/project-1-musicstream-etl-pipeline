"""Pipeline page — upload CSVs, trigger the ETL, track execution progress."""

import os
import sys
import time
from datetime import date

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MOCK_MODE = os.environ.get("MOCK_MODE", "false").lower() == "true"
ENV = os.environ.get("ENV", "dev")
RAW_BUCKET = os.environ.get("RAW_BUCKET", f"musicstream-{ENV}-raw")

st.set_page_config(page_title="Pipeline · MusicStream", page_icon="🔁", layout="wide")

st.markdown(
    """
    <style>
    .stage-done    { color: #4ade80; }
    .stage-running { color: #fbbf24; }
    .stage-pending { color: #94a3b8; }
    .stage-fail    { color: #f87171; }
    </style>
    """,
    unsafe_allow_html=True,
)

if MOCK_MODE:
    st.warning("⚡ Mock mode — showing simulated pipeline data.")

st.title("🔁 Pipeline")
st.caption("Upload a CSV, trigger the pipeline, and watch it progress stage by stage.")
st.divider()

# ── Section 1: Upload ─────────────────────────────────────────────────────────
st.subheader("1 · Upload Stream CSV")
uploaded_files = st.file_uploader(
    "Drop stream CSV files here",
    type=["csv"],
    accept_multiple_files=True,
)
stream_date = st.date_input(
    "Stream date (used for S3 partition prefix)", value=date(2024, 6, 25)
)

if st.button(
    "🚀 Upload & Trigger Pipeline", type="primary", disabled=not uploaded_files
):
    if MOCK_MODE:
        st.session_state["mock_execution"] = True
        st.success(
            f"[Mock] Would upload {len(uploaded_files)} file(s) and send to SQS."
        )
    else:
        from lib.pipeline_ops import upload_csv_to_s3, start_execution_via_sqs

        keys = []
        for uf in uploaded_files:
            key = upload_csv_to_s3(uf.read(), uf.name, stream_date.isoformat())
            keys.append(key)
            st.write(f"  ✅ Uploaded `{key}`")

        for key in keys:
            msg_id = start_execution_via_sqs(RAW_BUCKET, key)
            st.write(f"  📨 Queued key → SQS message `{msg_id}`")
        st.success(
            "All files uploaded and queued. EventBridge Pipe will start execution shortly."
        )

st.divider()

# ── Section 2: Execution Status ───────────────────────────────────────────────
st.subheader("2 · Recent Executions")

if MOCK_MODE:
    from lib.mock_data import mock_recent_executions

    executions = mock_recent_executions()
else:
    try:
        from lib.pipeline_ops import list_recent_executions

        executions = list_recent_executions(10)
    except Exception as exc:
        st.error(f"Could not list executions: {exc}")
        executions = []

if not executions:
    st.info("No executions found.")
else:
    for ex in executions[:5]:
        status = ex.get("status", "UNKNOWN")
        name = ex.get("name", ex.get("executionArn", "?"))
        start = str(ex.get("startDate", ""))[:19]
        stop = str(ex.get("stopDate", ""))[:19] if ex.get("stopDate") else "—"
        icon = {"SUCCEEDED": "✅", "FAILED": "❌", "RUNNING": "⏳"}.get(status, "❓")
        with st.expander(f"{icon} `{name}` — {status}", expanded=status == "RUNNING"):
            col1, col2 = st.columns(2)
            col1.write(f"**Started:** {start}")
            col2.write(f"**Ended:** {stop}")

            stages = [
                "ValidateSchema",
                "TransformAndCompute",
                "LoadDynamoDB",
                "ArchiveBatch",
            ]
            stage_status = {s: "pending" for s in stages}
            if status == "SUCCEEDED":
                stage_status = {s: "done" for s in stages}
            elif status == "RUNNING":
                stage_status["ValidateSchema"] = "done"
                stage_status["TransformAndCompute"] = "running"
            elif status == "FAILED":
                stage_status["ValidateSchema"] = "done"
                stage_status["TransformAndCompute"] = "fail"

            cols = st.columns(len(stages))
            labels = {
                "done": ("✅", "stage-done"),
                "running": ("⏳", "stage-running"),
                "pending": ("⬜", "stage-pending"),
                "fail": ("❌", "stage-fail"),
            }
            for col, stage in zip(cols, stages):
                sym, css = labels[stage_status[stage]]
                col.markdown(
                    f'<span class="{css}">{sym} {stage}</span>', unsafe_allow_html=True
                )

st.divider()

# ── Section 3: Quarantine Monitor ─────────────────────────────────────────────
st.subheader("3 · Quarantine (Rejected Files)")
st.caption("Files that failed T1 schema validation or T2 referential integrity. Check reason JSONs for details.")

if MOCK_MODE:
    st.info("Mock mode — no quarantine data to display.")
else:
    try:
        import boto3
        import json

        s3 = boto3.client("s3", region_name="eu-west-1")
        try:
            response = s3.list_objects_v2(
                Bucket=f"musicstream-{ENV}-quarantine-970547336735",
                Prefix="streams/"
            )
            objects = response.get("Contents", [])

            # Filter to just the CSV files (not the reason JSONs)
            csv_files = [o for o in objects if o["Key"].endswith(".csv")]

            if not csv_files:
                st.success("✅ No quarantined files — all uploads passed validation!")
            else:
                quarantine_data = []
                for obj in csv_files:
                    key = obj["Key"]
                    size_mb = obj["Size"] / 1_000_000
                    # Try to fetch the reason JSON
                    reason_key = key.replace(".csv", "_reason.json")
                    try:
                        resp = s3.get_object(Bucket=f"musicstream-{ENV}-quarantine-970547336735", Key=reason_key)
                        reason = json.loads(resp["Body"].read().decode("utf-8"))
                        reason_str = reason.get("error", reason.get("message", "Unknown"))
                    except Exception:
                        reason_str = "See reason JSON for details"

                    quarantine_data.append({
                        "File": key.split("/")[-1],
                        "Size (MB)": f"{size_mb:.1f}",
                        "Reason": reason_str,
                    })

                if quarantine_data:
                    import pandas as pd
                    df_quarantine = pd.DataFrame(quarantine_data)
                    st.dataframe(df_quarantine, use_container_width=True, hide_index=True)
                    st.warning(f"⚠️ {len(csv_files)} file(s) quarantined. Review the reason and re-upload after fixing the issue.")
        except Exception as e:
            st.warning(f"Quarantine bucket not accessible or empty: {e}")
    except ImportError:
        st.info("S3 access not configured for this session.")

st.divider()

# ── Section 4: Auto-refresh ───────────────────────────────────────────────────
auto_refresh = st.checkbox("Auto-refresh every 10 s", value=False)
if auto_refresh:
    time.sleep(10)
    st.rerun()
