from dataclasses import asdict

import pytest
from fakes import ROUTES, FakeClock, FakePhone

import jevagent.cli as cli
from jevagent.flow import load, save
from jevagent.player import Player, new_run_dir
from jevagent.report import write_flow_report, write_run_report


@pytest.fixture
def data(tmp_path, monkeypatch, recorded):
    flow, folder = recorded
    monkeypatch.setattr(cli, "DATA", tmp_path / "data")
    target = tmp_path / "data" / "flows" / flow.name
    target.parent.mkdir(parents=True)
    folder.rename(target)
    save(flow, target)
    return flow, target


def test_reports_render_flow_and_runs(data, screens):
    flow, folder = data
    for start in ("home", "shop"):  # one success, one failure
        clock = FakeClock()
        run_dir = new_run_dir(folder)
        result = Player(
            FakePhone(screens, start, clock, ROUTES),
            flow,
            folder,
            clock=clock,
            sleep=clock.sleep,
            log=lambda s: None,
        ).run(run_dir)
        page = write_run_report(flow, folder, run_dir, asdict(result)).read_text(encoding="utf-8")
        assert ("成功" if start == "home" else "失败") in page and "last.jpg" in page
    page = write_flow_report(flow, folder).read_text(encoding="utf-8")
    assert page.count('class="card"') == len(flow.steps) + 1  # steps + end screen
    assert "step-01.jpg" in page and "回放记录" in page and page.count("<tr>") == 3


def test_list_show_edit(data, capsys):
    flow, folder = data
    assert cli.main(["list"]) == 0
    assert f"{flow.name}  4 步  回放 0 次" in capsys.readouterr().out
    assert cli.main(["show", flow.name, "--no-open"]) == 0
    out = capsys.readouterr().out
    assert "点击 (2190,210)" in out and (folder / "report.html").is_file()
    assert (
        cli.main(["edit", flow.name, "--delete", "4", "--set", "1.check=off", "--set", "2.label=打开礼包"])
        == 0
    )
    edited = load(folder)
    assert len(edited.steps) == 3 and not edited.steps[0].check and edited.revision == 2
    assert cli.main(["edit", flow.name, "--set", "9.check=off"]) == 1
    assert "没有第 9 步" in capsys.readouterr().out
    assert cli.main(["show", "不存在"]) == 1
