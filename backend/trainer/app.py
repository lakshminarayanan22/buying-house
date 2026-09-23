"""SQL Trainer — correct XiYanSQL's queries, one question at a time.

    cd ~/buying-house/backend
    ollama serve &                                  # XiYanSQL has to be reachable
    .venv/bin/streamlit run trainer/app.py

A separate tool from the Ecolink console: it runs locally, it is never deployed, and it only
ever touches the evaluation database (`ecolink_eval`). Your real data is not reachable from here.

The loop is the one from the invoice trainer: the model drafts, a person corrects, and the
corrections become training data. What is different is that SQL can be *run*, so the screen
shows the rows a query returns rather than asking anyone to read SQL and imagine them.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text

from app.chat import newrecord
from app.chat.llm import uses_xiyan
from app.config import settings
from trainer import runner, store

st.set_page_config(page_title="SQL Trainer", page_icon="🧵", layout="wide")

QUESTIONS = store.questions()
BY_ID = {q["id"]: q for q in QUESTIONS}
SCORING = {q["id"] for q in QUESTIONS if q["set"] == "score"}


def rows_state() -> dict[str, dict]:
    if "rows" not in st.session_state:
        st.session_state.rows = store.load()
    return st.session_state.rows


def row_for(question: dict) -> dict:
    rows = rows_state()
    if question["id"] not in rows:
        rows[question["id"]] = store.blank(question)
    return rows[question["id"]]


def show_result(result: runner.Result) -> None:
    if not result.ok:
        st.error(result.error)
        return
    if result.kind == "SELECT":
        if result.rows:
            st.caption(f"{len(result.rows)} row(s)" + (" — showing the first 200"
                                                       if result.truncated else ""))
            st.dataframe(pd.DataFrame(result.rows), use_container_width=True, hide_index=True)
        else:
            st.warning("Ran, but returned no rows. That is sometimes the right answer and "
                       "sometimes a missing filter — check against the database tab.")
        return
    st.success(f"{result.kind} — {result.affected} row(s) would change. Nothing was saved; "
               f"the statement ran inside a transaction that was rolled back.")
    for entry in result.diff[:10]:
        changes = entry.get("changes") or {}
        if changes:
            st.dataframe(pd.DataFrame([
                {"field": col, "now": cell.get("before"), "after": cell.get("after")}
                for col, cell in changes.items()
            ]), use_container_width=True, hide_index=True)
        elif entry.get("after"):
            st.dataframe(pd.DataFrame([entry["after"]]), use_container_width=True,
                         hide_index=True)


# ===================================================================== the review tab
def review_tab() -> None:
    rows = rows_state()
    stats = store.progress(rows, QUESTIONS)

    with st.sidebar:
        drafting = settings.ollama_sql_model or f"{settings.ollama_model} (no SQL specialist set)"
        st.caption(f"Drafting with **{drafting}**")
        if not uses_xiyan():
            st.warning("OLLAMA_SQL_MODEL does not name a XiYan model, so drafts come from the "
                       "general model and use the generic prompt. Set it in backend/.env if "
                       "XiYanSQL is what you intend to fine-tune.", icon="⚠️")
        st.subheader("Progress")
        st.progress(stats["done"] / stats["total"] if stats["total"] else 0.0)
        st.write(f"**{stats['done']} of {stats['total']}** reviewed")
        if stats["counted"]:
            st.metric("XiYanSQL right without help", f"{stats['share']:.0%}",
                      help="Share of reviewed questions accepted unchanged. This is the number "
                           "that says whether fine-tuning is worth doing.")
        only_todo = st.checkbox("Hide the ones I've done", value=False)

        listed = [q for q in QUESTIONS
                  if not only_todo or rows.get(q["id"], {}).get("status", "todo") == "todo"]
        marks = {"todo": "·", "ok": "✓", "fixed": "✎", "rewritten": "✎", "skip": "–"}
        labels = {q["id"]: f"{marks[rows.get(q['id'], {}).get('status', 'todo')]}  {q['id']}  "
                           f"{q['q'][:44]}" for q in listed}
        if not listed:
            st.info("Nothing left in this filter.")
            return
        chosen = st.radio("Questions", [q["id"] for q in listed],
                          format_func=lambda i: labels[i], label_visibility="collapsed")

    question = BY_ID[chosen]
    row = row_for(question)
    is_write = question["kind"] == "write"

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown(f"### {question['id']}")
        st.markdown(f"**{question['q']}**")
        tags = " · ".join(question["clauses"])
        st.caption(f"{tags} — {'write' if is_write else 'read'}"
                   + (" — held out for scoring" if question["id"] in SCORING else ""))
        if question["id"] in SCORING:
            st.info("Scoring question. Check the rows rather than the look of the SQL — an "
                    "accepted-but-wrong query here flatters XiYanSQL in every later comparison.")

        if not row["draft_sql"]:
            if st.button("Ask XiYanSQL for a draft", type="primary"):
                with st.spinner("Drafting — 20 to 40 seconds…"):
                    try:
                        sql, _ = runner.draft(question["q"], is_admin=is_write)
                    except Exception as exc:                       # noqa: BLE001
                        st.error(f"Could not reach the model: {exc}")
                        st.stop()
                row["draft_sql"] = sql
                # Which model wrote it, recorded on the row: a dataset whose drafts came
                # from two different models, unlabelled, cannot be read back later.
                row["draft_model"] = settings.ollama_sql_model or settings.ollama_model
                row["final_sql"] = row["final_sql"] or sql
                store.save(row)
                st.rerun()
            st.stop()

        st.caption("XiYanSQL's draft")
        st.code(row["draft_sql"], language="sql")

        edited = st.text_area("Your version — edit it, or leave it as it is",
                              value=row["final_sql"] or row["draft_sql"], height=220,
                              key=f"sql_{question['id']}")
        notes = st.text_input("Note (optional — why it was wrong)", value=row.get("notes", ""),
                              key=f"note_{question['id']}")

        run_col, accept_col, save_col, skip_col = st.columns(4)
        if run_col.button("Run it", key=f"run_{question['id']}"):
            st.session_state[f"result_{question['id']}"] = runner.run(edited,
                                                                      allow_write=is_write)
        if accept_col.button("Draft is right", key=f"ok_{question['id']}"):
            row.update(final_sql=row["draft_sql"], status="ok", notes=notes)
            store.save(row)
            st.rerun()
        if save_col.button("Save correction", type="primary", key=f"save_{question['id']}"):
            changed = edited.strip() != row["draft_sql"].strip()
            row.update(final_sql=edited, notes=notes,
                       status="fixed" if changed else "ok")
            store.save(row)
            st.rerun()
        if skip_col.button("Skip", key=f"skip_{question['id']}"):
            row.update(status="skip", notes=notes)
            store.save(row)
            st.rerun()

        if st.button("Draft again", key=f"redraft_{question['id']}"):
            with st.spinner("Drafting…"):
                sql, _ = runner.draft(question["q"], is_admin=is_write)
            row["draft_sql"] = sql
            store.save(row)
            st.rerun()

    with right:
        st.caption("What your version returns")
        result = st.session_state.get(f"result_{question['id']}")
        if result is None:
            st.info("Press **Run it** to see the rows. For an UPDATE or DELETE you get the "
                    "before-and-after; nothing is saved either way.")
        else:
            show_result(result)


# =================================================================== the database tab
TABLES = ["company", "contact", "company_process", "company_product", "company_certification",
          "company_client", "deal", "deal_party", "deal_milestone", "reference_item", "app_user"]


def database_tab() -> None:
    st.caption("The evaluation database — 30 imagined companies, 50 deals, and 'today' fixed at "
               "15 September 2026. Nothing here is real, and the app never reads it.")

    table = st.selectbox("Table", TABLES)
    db = runner.eval_sessionmaker()()
    try:
        count = db.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        st.caption(f"{count} rows")
        result = db.execute(text(f"SELECT * FROM {table} LIMIT 200"))
        frame = pd.DataFrame([dict(zip(result.keys(), r)) for r in result.fetchall()])
        st.dataframe(frame.astype(str), use_container_width=True, hide_index=True, height=320)
    finally:
        db.rollback()
        db.close()

    st.divider()
    st.caption("Scratchpad — run any SELECT to check an answer while you correct. Reads only: "
               "the guard refuses anything else here.")
    scratch = st.text_area("SQL", value=st.session_state.get("scratch", ""),
                           height=120, key="scratch", label_visibility="collapsed")
    if st.button("Run", key="run_scratch") and scratch.strip():
        show_result(runner.run(scratch, allow_write=False))


# ============================================================ creating records is the app's job
def create_tab() -> None:
    st.caption("These 11 questions ask the assistant to create a record. It should not write "
               "SQL for them — it should say where in the app to do it. No model is called, so "
               "this checks instantly.")
    for question in store.questions(include_create=True):
        if question.get("kind") != "create":
            continue
        caught = newrecord.asks_to_create(question["q"])
        with st.expander(f"{'✓' if caught else '✗'}  {question['q']}", expanded=not caught):
            if caught:
                st.text(newrecord.handoff(question["q"], runner.eval_sessionmaker()()))
            else:
                st.error("Not recognised as a request to create a record — this one would go "
                         "to the SQL writer instead. Worth a phrase in app/chat/newrecord.py.")


# ============================================================================== export
def export_tab() -> None:
    rows = rows_state()
    ready = list(store.trainable(rows, SCORING))
    stats = store.progress(rows, QUESTIONS)

    a, b, c = st.columns(3)
    a.metric("Reviewed", f"{stats['done']} / {stats['total']}")
    b.metric("Ready to train on", len(ready))
    c.metric("Accepted unchanged", f"{stats['share']:.0%}" if stats["counted"] else "—")

    st.caption("Scoring questions are excluded from this count on purpose: a model trained on "
               "the questions it is scored against tells you nothing.")
    st.write(f"Corrections are saved to `{store.CORRECTIONS.relative_to(store.BACKEND)}` as you "
             f"go. Commit that file — it is the training data.")
    if ready:
        st.dataframe(pd.DataFrame([{"id": r["id"], "status": r["status"],
                                    "question": r["question"][:70], "sql": r["final_sql"][:90]}
                                   for r in ready]),
                     use_container_width=True, hide_index=True)


st.title("SQL Trainer")
st.caption("XiYanSQL drafts · you correct · the corrections become training data")
tabs = st.tabs(["Review", "Database", "Creating records", "Export"])
with tabs[0]:
    review_tab()
with tabs[1]:
    database_tab()
with tabs[2]:
    create_tab()
with tabs[3]:
    export_tab()
