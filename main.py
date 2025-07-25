import streamlit as st
import firebase_admin
from firebase_admin import credentials, db
import uuid
import datetime
import json
import pandas as pd
from collections import defaultdict, abc

# Convert secrets AttrDict to native dict
def to_dict(obj):
    if isinstance(obj, abc.Mapping):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj

firebase_config = to_dict(st.secrets["FIREBASE"])

if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_config)
    firebase_admin.initialize_app(cred, {
        'databaseURL': f"https://{firebase_config['project_id']}-default-rtdb.asia-southeast1.firebasedatabase.app"
    })

ref = db.reference('/questions')
data = ref.get() or {}

st.set_page_config(page_title="Live Assistance AI", layout="wide")
st.title("🤖 Real-Time AI Clarification Assistant")

# --- Helper Functions ---
def time_since(iso_time_str):
    now = datetime.datetime.now(datetime.timezone.utc)
    created = datetime.datetime.fromisoformat(iso_time_str).astimezone(datetime.timezone.utc)
    diff = now - created
    minutes = int(diff.total_seconds() // 60)
    hours = minutes // 60
    if minutes < 1:
        return "Just now"
    elif minutes < 60:
        return f"{minutes} min ago"
    elif hours < 24:
        return f"{hours} hr ago"
    else:
        return f"{hours // 24} day(s) ago"

def auto_tag(text):
    keywords = {
        "refund": "Refund",
        "order": "Order",
        "payment": "Payment",
        "local": "Local Deals",
        "voucher": "Voucher",
        "expired": "Expiration",
        "cancel": "Cancellation",
        "return": "Return Policy"
    }
    for key, tag in keywords.items():
        if key in text.lower():
            return tag
    return "General"

# --- Layout ---
left_col, right_col = st.columns([2, 1])

# ------------------------ AGENT PANEL ------------------------
with left_col:
    st.header("🧑 Agent Panel")

    agent_name = st.text_input("Your Name (Agent)", key="agent_name")
    question = st.text_input("What clarification do you need?", key="agent_q")

    similar_found = False
    if question:
        st.markdown("### 🔍 Suggested Previous Answers")
        for qid, item in data.items():
            if question.lower() in item['question'].lower() and item.get("answer"):
                similar_found = True
                st.markdown(f"**Q:** {item['question']}")
                with st.expander("View Answer"):
                    st.markdown(f"**A:** {item['answer']}")
                st.caption(f"Tagged Topic: {item.get('topic', 'N/A')} | By: {item.get('answered_by', 'Unknown')}")
                st.markdown("---")
        if not similar_found:
            st.info("No similar answers found.")

    if st.button("Submit Clarification") and question and agent_name and not similar_found:
        qid = str(uuid.uuid4())
        ref.child(qid).set({
            'question': question,
            'asked_by': agent_name,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'answer': '',
            'answered_by': '',
            'claimed_by': '',
            'edit_log': [],
            'topic': '',
            'send_back': 0
        })
        st.success("✅ Clarification submitted!")

    if agent_name:
        st.markdown("### 📥 Your Clarifications")
        agent_questions = {
            qid: q for qid, q in data.items()
            if q.get('asked_by', '').lower() == agent_name.lower()
        }

        if not agent_questions:
            st.info("You haven’t raised any clarifications yet.")
        else:
            for qid, q in sorted(agent_questions.items(), key=lambda x: x[1]['timestamp'], reverse=True):
                st.markdown(f"**Q:** {q['question']}")
                st.caption(f"⏱️ {time_since(q['timestamp'])}")
                if q.get("answer"):
                    st.success("✅ Your query has been answered!")
                    with st.expander("View Answer"):
                        st.markdown(f"**A:** {q['answer']}")
                    st.caption(f"Answered by: {q.get('answered_by', 'Unknown')} | Topic: {q.get('topic', 'N/A')}")
                elif q.get("claimed_by"):
                    st.info(f"🕓 Claimed by {q['claimed_by']} – Awaiting answer")
                else:
                    st.warning("❗ Unclaimed")
                st.markdown("---")

# ------------------------ SME PANEL ------------------------
with st.sidebar:
    st.title("🧑‍💼 SME Panel")
    sme_name = st.text_input("Your Name (SME)", key="sme_name")

    if sme_name:
        st.subheader("🗂️ Unanswered Clarifications")
        unanswered = {
            qid: q for qid, q in data.items()
            if not q.get("answer")
        }

        if not unanswered:
            st.info("No open clarifications.")
        else:
            for qid, q in sorted(unanswered.items(), key=lambda x: x[1]['timestamp'], reverse=True):
                claimed_by = q.get("claimed_by")
                is_claimed = claimed_by and claimed_by != sme_name
                faded_style = "color:gray;" if is_claimed else ""

                with st.expander(f"❓ {q['question']}"):
                    st.markdown(f"<span style='{faded_style}'>🧑 Asked by: {q['asked_by']} – ⏱️ {time_since(q['timestamp'])}</span>", unsafe_allow_html=True)

                    if claimed_by and claimed_by != sme_name:
                        st.warning(f"⚠️ Claimed by {claimed_by}")
                    elif not claimed_by:
                        if st.button("Claim", key=f"claim_{qid}"):
                            ref.child(qid).update({"claimed_by": sme_name})
                            st.rerun()

                    if claimed_by == sme_name:
                        suggested_topic = auto_tag(q['question'])
                        topic = st.text_input("Tag Topic (editable)", value=suggested_topic, key=f"topic_{qid}")
                        ans = st.text_area("Your Answer", height=200, key=f"ans_{qid}")
                        if st.button("Submit Answer", key=f"submit_{qid}"):
                            ref.child(qid).update({
                                'answer': ans,
                                'answered_by': sme_name,
                                'last_updated': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                'topic': topic
                            })
                            st.success("✅ Answer submitted!")
                            st.rerun()

        # Send-back Panel
        st.subheader("🔁 Send Back Existing Answer")
        tag_filter = st.text_input("Enter Topic Tag to Send Back")
        agent_to_notify = st.text_input("Agent to Notify")

        matched = [
            (qid, q) for qid, q in data.items()
            if q.get("topic") and tag_filter.lower() in q.get("topic").lower() and q.get("answer")
        ]

        if matched and st.button("Send Back Clarification"):
            for qid, q in matched:
                new_count = q.get("send_back", 0) + 1
                ref.child(qid).update({"send_back": new_count})
            st.success(f"✅ Sent back {len(matched)} related clarifications to {agent_to_notify}")

# ------------------------ DASHBOARD ------------------------
with right_col:
    st.header("📊 Dashboard")
    total = len(data)
    answered = sum(1 for item in data.values() if item.get('answer'))
    unanswered = total - answered
    claimed = sum(1 for item in data.values() if item.get('claimed_by'))
    sent_back_total = sum(1 for item in data.values() if item.get("send_back", 0) > 0)

    dashboard_df = pd.DataFrame([
        {"Metric": "Total Clarifications", "Count": total},
        {"Metric": "Answered", "Count": answered},
        {"Metric": "Unanswered", "Count": unanswered},
        {"Metric": "Claimed", "Count": claimed},
        {"Metric": "Send Backs", "Count": sent_back_total}
    ])

    st.dataframe(dashboard_df.style.set_table_styles([
        {"selector": "th, td", "props": [("font-size", "12px")]}]),
        hide_index=True,
        use_container_width=True
    )

    st.subheader("🧑‍💼 SME Contributions")
    sme_counts = defaultdict(int)
    for item in data.values():
        if item.get("answered_by"):
            sme_counts[item["answered_by"]] += 1
    for sme, count in sme_counts.items():
        st.markdown(f"<span style='font-size: 12px;'>- <b>{sme}</b> answered {count}</span>", unsafe_allow_html=True)
