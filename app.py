"""Entry point: `streamlit run app.py`."""
from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

from views import compare, home, review, usage
from views.common import init_state

load_dotenv()

st.set_page_config(
    page_title="Polyglot Review",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_state()

pages = [
    st.Page(home.render, title="Overview", icon=":material/home:", url_path="overview", default=True),
    st.Page(review.render, title="Review", icon=":material/rate_review:", url_path="review"),
    st.Page(compare.render, title="Compare versions", icon=":material/compare_arrows:", url_path="compare"),
    st.Page(usage.render, title="Usage analytics", icon=":material/monitoring:", url_path="usage"),
]
st.navigation(pages).run()
