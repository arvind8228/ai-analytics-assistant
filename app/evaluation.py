import streamlit as st


st.title("Evaluation")

st.markdown(
    """
    The assistant is evaluated against a frozen benchmark before
    changes are accepted.
    """
)


column_1, column_2, column_3, column_4 = st.columns(
    4
)

with column_1:
    st.metric(
        "Evaluation cases",
        "55",
    )

with column_2:
    st.metric(
        "Status routing",
        "100%",
    )

with column_3:
    st.metric(
        "SQL equivalence",
        "96%",
    )

with column_4:
    st.metric(
        "Regression tests",
        "22 / 22",
    )


st.subheader("Evaluation layers")

left, right = st.columns(2)

with left:
    with st.container(border=True):
        st.markdown("### Question gate")

        st.write(
            "Tests whether the system should answer, "
            "clarify, stop, or reject the request."
        )

        st.markdown(
            """
            **Final results**

            - Status accuracy: **55 / 55**
            - False clarification: **0%**
            - Unanswerable detection: **100%**
            - Unsafe rejection: **100%**
            """
        )

with right:
    with st.container(border=True):
        st.markdown("### SQL correctness")

        st.write(
            "Generated SQL is compared with canonical "
            "queries using database-result equivalence."
        )

        st.markdown(
            """
            **Final results**

            - Automated equivalence: **24 / 25**
            - Semantic correctness: **25 / 25**
            - Validation failures: **0**
            - Execution failures: **0**
            """
        )


st.info(
    "The automated comparator remains intentionally stricter "
    "than the manual semantic review."
)