import streamlit as st
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


st.set_page_config(
    page_title="AI Analytics Assistant",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


ask_page = st.Page(
    "ask_analytics.py",
    title="Ask Analytics",
    icon=":material/analytics:",
    default=True,
)

evaluation_page = st.Page(
    "evaluation.py",
    title="Evaluation",
    icon=":material/fact_check:",
)

architecture_page = st.Page(
    "architecture.py",
    title="Architecture",
    icon=":material/account_tree:",
)


navigation = st.navigation(
    [
        ask_page,
        evaluation_page,
        architecture_page,
    ],
    position="top",
)


navigation.run()