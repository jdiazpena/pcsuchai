from pcsuchai.counter_experiment import counter_command, probe_counter_group, read_group_result


def test_counter_command_groups_full_job_with_compatible_scopes(tmp_path):
    command = counter_command(["python", "-m", "pcsuchai", "analyze"], ("cycles:u", "instructions:u"), tmp_path / "raw.csv")
    assert command[command.index("-e") + 1] == "{cycles:u,instructions:u}"
    assert "--no-scale" in command and "--no-big-num" in command
    assert command[-4:] == ["python", "-m", "pcsuchai", "analyze"]


def test_group_quality_and_ipc_are_saved_without_rounded_integer_loss(tmp_path):
    path = tmp_path / "raw.csv"
    path.write_text("9007199254740993;;cycles:u;1000000000;100.00\n18014398509481986;;instructions:u;1000000000;100.00\n")
    report = read_group_result(path, ("cycles:u", "instructions:u"), 95)
    assert report["status"] == "acceptable"
    assert report["accounting"]["events"][0]["reported_value"] == 9007199254740993
    assert report["ipc"]["value"] == 2


def test_group_requires_exact_requested_events_not_just_matching_count(tmp_path):
    path = tmp_path / "raw.csv"
    path.write_text("100;;cycles:u;1000;100.00\n200;;branches:u;1000;100.00\n")
    report = read_group_result(path, ("cycles:u", "instructions:u"), 95)
    assert report["status"] == "unavailable_or_poor_coverage"
    assert report["ipc"]["value"] is None


def test_closed_gzip_counter_text_is_read_without_reexecuting_perf(tmp_path):
    import gzip
    path = tmp_path / "raw.csv.gz"
    with gzip.open(path, "wt") as source:
        source.write("100;;cycles:u;1000;100.00\n200;;instructions:u;1000;100.00\n")
    assert read_group_result(path, ("cycles:u", "instructions:u"), 95)["ipc"]["value"] == 2


def test_missing_tool_capability_retains_reason_not_fake_counter_values(tmp_path, monkeypatch):
    import pcsuchai.counter_experiment as counters
    monkeypatch.setattr(counters.shutil, "which", lambda _: None)
    report = probe_counter_group(("cycles:u",), tmp_path / "probe", {})
    assert report["status"] == "unsupported"
    assert report["reason"] == "perf executable not found"
    assert "probe_result" not in report
    assert (tmp_path / "probe/capability.json").is_file()
