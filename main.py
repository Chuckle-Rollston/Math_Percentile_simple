# main.py
import time
import random
import sqlite3
from pathlib import Path
from dataclasses import dataclass

import streamlit as st

NUM_QUESTIONS = 10
MAX_ABS_ANSWER = 143
MAX_DIV_ANSWER = 12
DB_PATH = Path("global_scores.db")

st.set_page_config(page_title="Speed Math Global", page_icon="", layout="centered")

# ---------- Data ----------
@dataclass
class Question:
    text: str
    answer: int


# ---------- Question generation ----------
def clamp_ok(ans: int) -> bool:
    return abs(ans) <= MAX_ABS_ANSWER


def make_question(rng: random.Random) -> Question:
    op = rng.choice(["+", "-", "×", "÷"])

    if op == "÷":
        q = rng.randint(0, MAX_DIV_ANSWER)
        b = rng.randint(1, 12)
        a = b * q
        return Question(f"{a} ÷ {b}", q)

    if op == "×":
        while True:
            a = rng.randint(-12, 12)
            b = rng.randint(-12, 12)
            ans = a * b
            if clamp_ok(ans):
                return Question(f"{a} × {b}", ans)

    if op == "+":
        while True:
            a = rng.randint(-12, 12)
            b = rng.randint(-12, 12)
            ans = a + b
            if clamp_ok(ans):
                return Question(f"{a} + {b}", ans)

    while True:  # "-"
        a = rng.randint(-12, 12)
        b = rng.randint(-12, 12)
        ans = a - b
        if clamp_ok(ans):
            return Question(f"{a} - {b}", ans)


# ---------- Global communal DB (SQLite file) ----------
def _get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            score REAL NOT NULL,
            accuracy REAL NOT NULL,
            time_taken REAL NOT NULL
        );
        """
    )
    conn.commit()
    return conn


@st.cache_resource
def db_conn() -> sqlite3.Connection:
    return _get_db_connection()


def insert_score(score: float, accuracy: float, time_taken: float) -> None:
    conn = db_conn()
    conn.execute(
        "INSERT INTO scores (ts, score, accuracy, time_taken) VALUES (?, ?, ?, ?)",
        (int(time.time()), float(score), float(accuracy), float(time_taken)),
    )
    conn.commit()


def get_global_scores() -> list[float]:
    conn = db_conn()
    rows = conn.execute("SELECT score FROM scores").fetchall()
    return [float(r[0]) for r in rows]


def percentile_rank(user_score: float, history: list[float]) -> float | None:
    if not history:
        return None
    worse = sum(1 for s in history if s > user_score)  # lower score is better
    return 100.0 * worse / len(history)


# ---------- Helpers ----------
def reset_all():
    for k in ["started", "finished", "start_time", "questions", "idx", "user_answers", "last_run", "focus_nonce"]:
        st.session_state.pop(k, None)
    st.rerun()


def finish_quiz(show_answers: bool):
    end_time = time.perf_counter()
    time_taken = end_time - st.session_state.start_time

    questions: list[Question] = st.session_state.questions
    user_answers: list[int | None] = st.session_state.user_answers

    correct = 0
    for q, ua in zip(questions, user_answers):
        if ua is not None and ua == q.answer:
            correct += 1

    accuracy = correct / len(questions)
    score = float("inf") if accuracy == 0 else (1.0 / accuracy) * time_taken

    history = get_global_scores()
    pct = None if score == float("inf") else percentile_rank(score, history)

    if score != float("inf"):
        insert_score(score, accuracy, time_taken)

    st.session_state.finished = True
    st.session_state.last_run = {
        "time_taken": time_taken,
        "correct": correct,
        "accuracy": accuracy,
        "score": score,
        "percentile": pct,
        "show_answers": show_answers,
    }
    st.rerun()


def autofocus_text_input():
    """
    Forces focus onto the first text input on the page.
    Streamlit doesn't expose a native autofocus param, so we do a tiny JS poke.
    This runs fast and reduces the "click-to-focus" time tax.
    """
    st.components.v1.html(
        """
        <script>
        const tryFocus = () => {
          const input = window.parent.document.querySelector('input[type="text"]');
          if (input) { input.focus(); input.select?.(); return true; }
          return false;
        };
        // Try immediately, then a few more times (DOM timing)
        let attempts = 0;
        const iv = setInterval(() => {
          attempts++;
          if (tryFocus() || attempts > 20) clearInterval(iv);
        }, 25);
        </script>
        """,
        height=0,
    )


# ---------- UI ----------
st.title("Global Speed Math")
st.caption("Score = (1/accuracy) × time_taken_seconds  •  lower is better   •  Percentile is vs everyone ")

show_answers = st.checkbox("Show correct answers at end", value=True)
st.divider()

if "started" not in st.session_state:
    st.session_state.started = False
if "finished" not in st.session_state:
    st.session_state.finished = False
if "focus_nonce" not in st.session_state:
    st.session_state.focus_nonce = 0  # changes force component refresh

if not st.session_state.started:
    st.write("Press **Start**. Then complete questions until finished (10 questions)")

    if st.button("Start", type="primary", use_container_width=True):
        rng = random.Random()  # no seed (removed)
        st.session_state.questions = [make_question(rng) for _ in range(NUM_QUESTIONS)]
        st.session_state.user_answers = [None] * NUM_QUESTIONS
        st.session_state.idx = 0
        st.session_state.start_time = time.perf_counter()
        st.session_state.started = True
        st.session_state.finished = False
        st.session_state.focus_nonce += 1
        st.rerun()

else:
    if st.session_state.finished:
        r = st.session_state.last_run
        st.success("Done")

        st.write(f"**Time taken:** {r['time_taken']:.3f} s")
        st.write(f"**Accuracy:** {r['correct']}/{NUM_QUESTIONS} = {r['accuracy']*100:.1f}%")
        st.write(f"**Final score:** {r['score']:.4f}" if r["score"] != float("inf") else "**Final score:** ∞ (accuracy was 0)")

        if r["percentile"] is None:
            st.write("**Percentile:** N/A (not enough global data yet, or score was ∞)")
        else:
            st.write(f"**Percentile:** {r['percentile']:.1f}th (higher = better)")

        st.caption(f"Global attempts recorded: **{len(get_global_scores())}**")

        if r.get("show_answers", True):
            st.divider()
            st.subheader("Review")
            for i, q in enumerate(st.session_state.questions, start=1):
                ua = st.session_state.user_answers[i - 1]
                ok = (ua == q.answer)
                st.write(
                    f"Q{i}. {q.text} = **{q.answer}**  |  you: **{ua if ua is not None else '—'}**  "
                    f"{'✅' if ok else '❌'}"
                )

        st.divider()
        if st.button("New run", use_container_width=True):
            reset_all()

    else:
        idx = st.session_state.idx
        questions: list[Question] = st.session_state.questions
        q = questions[idx]

        st.info("Timer is running - Enter submits instantly")
        st.progress(idx / NUM_QUESTIONS)
        st.write(f"**Question {idx+1}/{NUM_QUESTIONS}**")
        st.markdown(f"### {q.text} = ?")

        # Render autofocus hook (nonce forces refresh per question)
        _ = st.session_state.focus_nonce
        autofocus_text_input()

        # One-question form => Enter submits => next question
        with st.form(f"single_q_form_{idx}", clear_on_submit=True):
            raw = st.text_input("Answer", value="", placeholder="e.g. 42")
            submitted = st.form_submit_button("Next (Enter)")

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            if st.button("⏭ Skip", use_container_width=True):
                st.session_state.user_answers[idx] = None
                st.session_state.idx += 1
                st.session_state.focus_nonce += 1
                if st.session_state.idx >= NUM_QUESTIONS:
                    finish_quiz(show_answers)
                st.rerun()

        with c2:
            if st.button("Finish Quiz", type="primary", use_container_width=True):
                finish_quiz(show_answers)

        with c3:
            if st.button("Reset", use_container_width=True):
                reset_all()

        if submitted:
            raw = raw.strip()
            try:
                val = int(raw)
            except Exception:
                val = None

            st.session_state.user_answers[idx] = val
            st.session_state.idx += 1
            st.session_state.focus_nonce += 1  # force autofocus refresh next Q

            if st.session_state.idx >= NUM_QUESTIONS:
                finish_quiz(show_answers)
            else:
                st.rerun()
