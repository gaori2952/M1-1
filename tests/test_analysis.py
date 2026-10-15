"""Small tests for the mistakes that would change the analysis conclusions."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import analysis


class AnalysisTests(unittest.TestCase):
    def write_export(self, directory, rows):
        path = Path(directory) / "Views.csv"
        path.write_text('sep=,\n"Views"\n"Date","Primary"\n' + rows, encoding="utf-16")
        return path

    def test_parser_preserves_zero_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_export(tmp, '"2026-01-01T00:00:00","0"\n"2026-01-02T00:00:00",""\n')
            series = analysis.read_metric(path, "views")
            self.assertEqual(series.iloc[0], 0)
            self.assertTrue(pd.isna(series.iloc[1]))

    def test_parser_rejects_duplicate_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_export(tmp, '"2026-01-01","2"\n"2026-01-01","3"\n')
            with self.assertRaisesRegex(ValueError, "duplicate"):
                analysis.read_metric(path, "views")

    def test_parser_rejects_negative_or_malformed_count(self):
        for value in ["-1", "oops", "1.5", "inf"]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                path = self.write_export(tmp, f'"2026-01-01","{value}"\n')
                with self.assertRaises(ValueError):
                    analysis.read_metric(path, "views")

    def test_daily_calendar_does_not_fill_gaps(self):
        series = pd.Series([0., 5.], index=pd.to_datetime(["2026-01-01", "2026-01-03"]), name="views")
        daily = analysis.join_daily([series])
        self.assertEqual(len(daily), 3)
        self.assertEqual(daily.iloc[0, 0], 0)
        self.assertTrue(pd.isna(daily.iloc[1, 0]))

    def test_change_handles_zero_and_does_not_forward_fill(self):
        got = analysis.percent_change(pd.Series([0., 10., 20., np.nan, 30.]))
        self.assertTrue(got.iloc[:2].isna().all())
        self.assertEqual(got.iloc[2], 100.)
        self.assertTrue(got.iloc[3:].isna().all())

    def test_lag_pairs_use_calendar_dates(self):
        frame = pd.DataFrame({"views": [10., 30., 40.], "follows": [1., 3., 4.]},
                             index=pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-04"]))
        pairs = analysis.lag_pairs(frame, "follows", 1)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs.iloc[0]["x"], 30.)
        self.assertEqual(pairs.iloc[0]["y"], 4.)

    def test_event_exclusion_checks_predictor_and_outcome_date(self):
        idx = pd.date_range("2026-09-21", periods=6)
        frame = pd.DataFrame({"views": range(6), "follows": range(6)}, index=idx)
        pairs = analysis.lag_pairs(frame, "follows", 1, exclude_event=True)
        self.assertEqual(list(pairs.index), [pd.Timestamp("2026-09-21"), pd.Timestamp("2026-09-25")])

    def test_pre_post_excludes_both_event_days(self):
        frame = pd.DataFrame({"views": 10.}, index=pd.date_range("2026-09-01", "2026-10-10"))
        frame.loc["2026-09-23":"2026-09-24", "views"] = 1000.
        periods = analysis.event_windows(frame)
        self.assertEqual(periods.loc[(14, "before", "views"), "n"], 14)
        self.assertEqual(periods.loc[(14, "after", "views"), "mean"], 10.)

    def test_window_ratios_weight_by_volume_and_trim_each_metric(self):
        frame = pd.DataFrame({"views": [100., 100., 100., 100., 1000.],
                              "visits": [10., 10., 10., 10., 100.],
                              "follows": [20., 3., 2., 1., 10.]},
                             index=pd.date_range("2026-01-01", periods=5))
        got = analysis.window_summary(frame, "2026-01-01", "2026-01-05")
        self.assertAlmostEqual(got["follows_per1000_views"], 36 / 1400 * 1000)
        # A large follows day need not be a large views day.
        self.assertEqual(got["follows_trim_top2_mean"], 2.)
        self.assertEqual(got["views_trim_top2_mean"], 100.)
        self.assertAlmostEqual(got["follows_per1000_views_without_top_view_day"], 26 / 400 * 1000)

    def test_window_refuses_calendar_gaps_and_keeps_zero_ratio_undefined(self):
        frame = pd.DataFrame({"views": 0., "visits": 0., "follows": 0.},
                             index=pd.date_range("2026-01-01", periods=5))
        got = analysis.window_summary(frame, "2026-01-01", "2026-01-05")
        self.assertTrue(np.isnan(got["follows_per1000_views"]))
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            analysis.window_summary(frame.drop(frame.index[1]), "2026-01-01", "2026-01-05")


if __name__ == "__main__":
    unittest.main()
