import streamlit as st


st.title("Architecture")

st.markdown(
    """
    The system separates business interpretation from SQL generation
    and adds deterministic controls before database execution.
    """
)


st.code(
    """
Business Question
       ↓
Question Analysis
       ↓
Answerability Decision
       ↓
Structured SQL Plan
       ↓
SQL Generation
       ↓
Deterministic Validation
       ↓
PostgreSQL EXPLAIN
       ↓
Read-only Execution
       ↓
Result Diagnostics
       ↓
Grounded Explanation
       ↓
Audit Record
""".strip(),
    language=None,
)


left, right = st.columns(2)

with left:
    with st.container(border=True):
        st.markdown("### Before SQL")

        st.markdown(
            """
            - Material ambiguity detection
            - Documented defaults
            - Unsupported-capability detection
            - Unsafe-request rejection
            - Structured SQL planning
            """
        )

with right:
    with st.container(border=True):
        st.markdown("### After SQL generation")

        st.markdown(
            """
            - SQLGlot AST validation
            - Table and schema allowlists
            - Dangerous-function blocking
            - PostgreSQL `EXPLAIN`
            - Read-only transactions
            - Query timeouts
            - One bounded repair attempt
            """
        )


st.subheader("Core principle")

st.success(
    "A syntactically valid SQL query can still answer "
    "the wrong business question."
)