import json
from pathlib import Path
from skibodcs.generate import generate_scenario
from skibodcs.schema_tools import constrained_scenario_schema
from skibodcs import catalog

EX = json.loads((Path(__file__).parent.parent / "examples/iron_lantern.json").read_text())


class FakeLLM:
    def __init__(self, replies): self.replies, self.calls = list(replies), []
    def chat(self, messages, schema=None):
        self.calls.append((messages, schema)); return self.replies.pop(0)


def test_schema_has_real_enums():
    s = constrained_scenario_schema("Caucasus")
    d = s["$defs"]
    assert "Batumi" in d["Anchor"]["properties"]["near"]["enum"]
    assert "F-16C_50" in d["PlayerFlight"]["properties"]["aircraft"]["enum"]
    assert d["Meta"]["properties"]["theater"]["enum"] == ["Caucasus"]
    json.dumps(s)  # serialisable


def test_retry_feeds_errors_back():
    bad = json.loads(json.dumps(EX)); bad["player"][0]["start_airbase"] = "Batum"
    brief = {"situation": "s", "mission": "m", "execution": "e", "threats": "t", "roe": "r"}
    llm = FakeLLM([json.dumps(bad), json.dumps(EX), json.dumps(brief)])
    sc, log = generate_scenario(llm, "SEAD mission", "Caucasus")
    assert sc.briefing.mission == "m"
    assert "attempt 1 errors" in log[0] and "skeleton ok on attempt 2" in log[1]
    retry_msg = llm.calls[1][0][-1]["content"]
    assert "Batumi" in retry_msg                      # suggestion reached the model
    assert llm.calls[0][1] is not None                # schema was sent


def test_gives_up_after_retries():
    llm = FakeLLM(["{not json"] * 3)
    try:
        generate_scenario(llm, "x", "Caucasus", max_retries=3); assert False
    except RuntimeError as e:
        assert "failed validation" in str(e)


def test_prior_state_injected():
    brief = {"situation": "", "mission": "", "execution": "", "threats": "", "roe": ""}
    llm = FakeLLM([json.dumps(EX), json.dumps(brief)])
    generate_scenario(llm, "next", "Caucasus", prior_state={"destroyed": ["sam_site_1"]})
    assert "sam_site_1" in llm.calls[0][0][0]["content"]
