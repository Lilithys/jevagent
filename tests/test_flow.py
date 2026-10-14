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
    edit(flow, [], ["1.timeout=1800"])  # set by hand: an auto-battle that runs until the chests are full
    assert flow.steps[0].timeout_for(0) == 1800.0
    with pytest.raises(FlowError):
        edit(flow, [], ["1.timeout=4000"])


def test_look_point_moves_the_check_but_not_the_tap():
    flow = make_flow()
    assert flow.steps[0].check_point == (100, 100)
    edit(flow, [], ["1.look=2035,960"])
    assert flow.steps[0].look == [2035.0, 960.0] and flow.steps[0].check_point == (2035.0, 960.0)
    assert flow.steps[0].points[0][1:] == [100, 100]
    edit(flow, [], ["1.look=auto"])
    assert flow.steps[0].look is None
    for bad in ("1.look=5000,10", "1.look=abc", "1.look=1,2,3"):
        with pytest.raises(FlowError):
            edit(flow, [], [bad])


def test_tap_point_can_be_moved_without_re_recording():
    flow = make_flow()
    edit(flow, [], ["1.tap=1200,210", "2.tap=110,20"])
    assert flow.steps[0].points == [[0.0, 1200.0, 210.0], [0.1, 1200.0, 210.0]]
    assert flow.steps[1].points == [[0.0, 110.0, 20.0], [0.3, 500.0, 20.0]]  # the swipe moves as a whole
    for bad in ("2.tap=2300,20", "1.tap=auto", "1.tap=9999,1"):
        with pytest.raises(FlowError):
            edit(flow, [], [bad])


def test_re_recorded_tail_replaces_the_steps_from_n_on():
    from jevagent.flow import splice

    base = make_flow()  # 3 steps
    tail = Flow(
        name="商店",
        size=[2376, 1152],
        end_image="end-v2.jpg",
        end_gap=6.0,
        steps=[Step(points=[[0.0, 660, 222], [0.1, 660, 222]], gap=2.0, image="step-02-v2.jpg")],
    )
    merged = splice(base, tail, 2)
    assert [s.image for s in merged.steps] == ["step-01.jpg", "step-02-v2.jpg"]
    assert (merged.end_image, merged.end_gap, merged.revision) == ("end-v2.jpg", 6.0, 2)
    with pytest.raises(FlowError):
        splice(make_flow(), Flow(name="x", size=[1152, 2376], steps=tail.steps), 2)
    with pytest.raises(FlowError):
        splice(make_flow(), tail, 5)


def test_end_look_edit():
    flow = make_flow()
    edit(flow, [], ["end_look=1775,1052"])
    assert flow.end_look == [1775.0, 1052.0]
    edit(flow, [], ["end_look=auto"])
    assert flow.end_look is None
    with pytest.raises(FlowError):
        edit(flow, [], ["end_look=9999,1"])
