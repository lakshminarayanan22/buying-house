"""A generated query that Postgres rejects gets one repair, then a plain answer — never a crash.

Found on the first real run with Qwen: an aggregate without its GROUP BY escaped the graph as a
ProgrammingError and failed the whole request.
"""
from sqlalchemy.exc import ProgrammingError

from app.chat import branches


class FakeModel:
    """Replies with each canned statement in turn, and remembers what it was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)

        class Reply:
            content = self.replies.pop(0)
        return Reply()


def _pg_error(message):
    return ProgrammingError("SELECT ...", {}, Exception(message))


def test_a_failed_query_is_repaired_once_using_the_postgres_error(monkeypatch):
    calls = []

    def run_select(sql):
        calls.append(sql)
        if len(calls) == 1:
            raise _pg_error('column "company.name" must appear in the GROUP BY clause')
        return {"rows": [{"company": "Darling Downs", "owed": 6660.0}]}

    monkeypatch.setattr(branches, "run_select", run_select)
    model = FakeModel(
        "SELECT company.name, SUM(deal_party.commission_amount) FROM deal_party JOIN company "
        "ON company.id = deal_party.company_id GROUP BY company.name",   # the repair
        "Darling Downs owes $6,660.",                                      # the phrasing
    )
    state = {"question": "who owes us?", "trace": []}
    out = branches._run_generated(
        state, "SELECT SUM(commission_amount), company.name FROM deal_party JOIN company "
               "ON company.id = deal_party.company_id",
        is_admin=False, model=model, prompt="PROMPT")

    assert len(calls) == 2
    assert "GROUP BY company.name" in calls[1]
    assert "must appear in the GROUP BY" in model.prompts[0]     # the model saw the error
    assert out["answer"] == "Darling Downs owes $6,660."
    assert any("query failed" in t for t in out["trace"])


def test_if_the_repair_fails_too_the_user_gets_a_plain_answer_not_an_error(monkeypatch):
    def run_select(sql):
        raise _pg_error('column "nonsense" does not exist')

    monkeypatch.setattr(branches, "run_select", run_select)
    model = FakeModel("SELECT nonsense FROM deal")
    out = branches._run_generated({"question": "q", "trace": []}, "SELECT nonsense FROM deal",
                                  is_admin=False, model=model, prompt="PROMPT")
    assert out["answer"] == branches.COULD_NOT_QUERY
    assert len(model.prompts) == 1          # exactly one repair, no loop


def test_a_repaired_statement_still_goes_through_the_guard(monkeypatch):
    """A 'repair' that turns into a write for a member is refused like any other statement."""
    import pytest
    from app.chat import guard

    def run_select(sql):
        raise _pg_error("syntax error")

    monkeypatch.setattr(branches, "run_select", run_select)
    with pytest.raises(guard.SqlRejected) as refusal:
        guard.check("DELETE FROM deal", allow_write=False)

    model = FakeModel("DELETE FROM deal")
    out = branches._run_generated({"question": "q", "trace": []}, "SELECT * FROM deal",
                                  is_admin=False, model=model, prompt="PROMPT")
    assert out["answer"] == str(refusal.value)       # the guard's refusal, word for word
    assert out.get("pending_write") is None


def test_the_schema_prompt_names_allowed_values_and_the_commission_rules():
    prompt = branches._schema_prompt()
    assert "'IN_PROGRESS'" in prompt and "'ON_HOLD'" in prompt
    assert "'DUE', 'INVOICED'" in prompt
    assert "role = 'BUYER'" in prompt
    assert "password_hash" not in prompt and "google_sub" not in prompt


def test_sql_is_pulled_out_of_whatever_the_model_wrapped_it_in():
    assert branches._clean_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert branches._clean_sql("Here it is:\n```\nSELECT 2\n```") == "SELECT 2"
    assert branches._clean_sql("sql\nSELECT 3") == "SELECT 3"
    assert branches._clean_sql("SELECT 4") == "SELECT 4"


def test_a_change_that_matches_nothing_is_retried_then_refused_not_offered(monkeypatch):
    previews = []

    def preview_write(checked):
        previews.append(checked.sql)
        return {"kind": "UPDATE", "table": "deal", "affected": 0, "diff": []}

    monkeypatch.setattr(branches, "preview_write", preview_write)
    model = FakeModel("UPDATE deal SET status = 'ON_HOLD' WHERE title ILIKE '%Kaimei%'")
    out = branches._run_generated(
        {"question": "put the Kaimei deal on hold", "trace": []},
        "UPDATE deal SET status = 'ON_HOLD' WHERE deal_no = 'Kaimei cooling finish'",
        is_admin=True, model=model, prompt="PROMPT")

    assert len(previews) == 2 and "ILIKE" in previews[1]      # one repair, using title
    assert "matched no rows" in model.prompts[0]
    assert out.get("pending_write") is None                   # no confirm button for a no-op
    assert "didn't match any record" in out["answer"]


def test_the_prompts_say_who_we_are():
    assert "buying house" in branches.WHO_WE_ARE
    assert "don't manufacture" in branches.WHO_WE_ARE


def test_machinery_detail_is_pointed_at_the_documents_not_the_tables():
    """Live runs routed "what machinery does X run" to the tables, which hold only a note, and
    it answered "0 spindles" from an empty result while the machine list sat in a PDF."""
    from app.chat.classifier import CATEGORY_DEFINITIONS

    assert "machine and equipment lists" in CATEGORY_DEFINITIONS
    assert "spindle count" in CATEGORY_DEFINITIONS
    assert "only a sentence of free-text notes" in CATEGORY_DEFINITIONS or \
           "a sentence of free-text notes" in CATEGORY_DEFINITIONS
