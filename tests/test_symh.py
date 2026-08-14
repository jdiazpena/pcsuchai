from datetime import timezone

from pcsuchai.symh import load_symh, plot_symh


def test_reads_broken_text_and_plots_inclusive_interval(tmp_path) -> None:
    source = tmp_path / "symh.txt"
    source.write_text(
        "header\n22-08-2018 00:00:00.000 -8 -6 "
        "22-08-2018 00:01:00.000 -9 -7\nbroken\n"
        "22-08-2018 00:02:00.000 -10 -8"
    )
    times, values = load_symh(source)
    assert values.tolist() == [-6, -7, -8]
    assert times[0].tzinfo == timezone.utc
    output = tmp_path / "symh.png"
    metadata = plot_symh(times, values, output, start=times[1], end=times[2])
    assert metadata["points_rendered"] == 2
    assert output.stat().st_size > 0
