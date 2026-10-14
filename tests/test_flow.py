import pytest

from jevagent.flow import Flow, FlowError, Step, edit, load, save, validate_name


def make_flow() -> Flow:
    return Flow(
        name="商店",
        size=[2376, 1152],
        steps=[
            Step(points=[[0.0, 100, 100], [0.1, 100, 100]], gap=3.0, image="step-01.jpg"),
            Step(
                points=[[0.0, 10, 10], [0.3, 400, 10]], gap=0.4, image="step-02.jpg", check=False, note="快"
            ),
            Step(points=[[0.0, 50, 60], [0.9, 50, 60]], gap=25.0, image="step-03.jpg"),
        ],
        end_image="end.jpg",
        end_gap=4.0,
    )


def test_round_trip(tmp_path):
    flow = make_flow()
    save(flow, tmp_path)
    assert load(tmp_path) == flow


def test_kinds_and_replay_defaults():
    tap, swipe, hold = make_flow().steps
    assert (tap.kind, swipe.kind, hold.kind) == ("tap", "swipe", "long_press")
    assert tap.delay_for(0) == 0 and tap.timeout_for(0) == 5.0  # start screen should already be there
    assert swipe.delay_for(1) == 0.4  # unchecked: recorded rhythm
    assert hold.delay_for(2) == 1.5 and hold.timeout_for(2) == 50.0  # checked: settle, then wait for screen
    assert make_flow().end_timeout() == 10.0


def test_edit_applies_settings_then_deletes():
    flow = make_flow()
    changes = edit(
        flow, [2], ["1.check=off", "1.timeout=30", "1.label=打开商店", "end_check=off", "3.delay=auto"]
    )
    assert len(changes) == 6 and flow.revision == 2
    assert [s.image for s in flow.steps] == ["step-01.jpg", "step-03.jpg"]
    first = flow.steps[0]
    assert (first.check, first.timeout, first.label) == (False, 30.0, "打开商店")
    assert flow.end_check is False


@pytest.mark.parametrize(
    "delete, assignments",
    [
        ([], ["9.check=off"]),
        ([], ["1.threshold=2"]),
        ([], ["1.colour=red"]),
        ([], ["1.check=maybe"]),
        ([1, 2, 3], []),
        ([4], []),
        ([], ["1.timeout=-1"]),
    ],
)
def test_invalid_edits_change_nothing(delete, assignments):
    flow = make_flow()
    with pytest.raises(FlowError):
        edit(flow, delete, assignments)
    assert flow == make_flow()


def test_names():
    assert validate_name(" 领取每日奖励 ") == "领取每日奖励"
    for bad in ("", "../x", "a/b", ".hidden"):
        with pytest.raises(FlowError):
            validate_name(bad)


def test_missing_flow(tmp_path):
    with pytest.raises(FlowError):
        load(tmp_path / "nope")


def test_v1_flows_switch_to_the_edge_match_default(tmp_path):
    flow = make_flow()
    data = flow.to_json()
    data["version"] = 1
    data["steps"][0]["threshold"] = 0.8  # what v1 always stored
    data["steps"][1]["threshold"] = 0.7  # a value someone chose
    (tmp_path / "flow.json").write_text(__import__("json").dumps(data), encoding="utf-8")
    loaded = load(tmp_path)
    assert loaded.steps[0].threshold is None and loaded.steps[0].threshold_value == 0.6
    assert loaded.steps[1].threshold_value == 0.7
    save(loaded, tmp_path)
    assert load(tmp_path).to_json()["version"] == 2


def test_threshold_can_be_reset_to_default():
    flow = make_flow()
    edit(flow, [], ["1.threshold=0.75"])
    assert flow.steps[0].threshold_value == 0.75
    edit(flow, [], ["1.threshold=auto"])
    assert flow.steps[0].threshold is None


def test_a_one_minute_battle_gets_a_long_enough_wait():
    battle = Step(points=[[0.0, 1, 1], [0.1, 1, 1]], gap=70.0, image="x.jpg")  # tap ✕ after ~70 s of fighting
    assert battle.timeout_for(1) == 140.0
    assert Step(points=[[0.0, 1, 1], [0.1, 1, 1]], gap=400.0, image="x.jpg").timeout_for(1) == 600.0
    flow = make_flow()
    edit(flow, [], ["1.timeout=600"])
    assert flow.steps[0].timeout_for(0) == 600.0
