import json
import unittest

from docktui import report


def _c(name, state="running", status="Up 1 hour", project="", cid=None):
    return {
        "id": cid or f"{name}-id".ljust(12, "0"),
        "name": name,
        "state": state,
        "status": status,
        "image": "img",
        "compose_project": project,
        "compose_service": "",
    }


class TestParsing(unittest.TestCase):
    def test_container_health(self):
        self.assertEqual(report.container_health("Up 2 hours (healthy)"), "healthy")
        self.assertEqual(report.container_health("Up 1 second (unhealthy)"), "unhealthy")
        self.assertEqual(report.container_health("Up 1 second (health: starting)"), "starting")
        self.assertEqual(report.container_health("Up 5 minutes"), "")

    def test_container_exit_code(self):
        self.assertEqual(report.container_exit_code("Exited (3) 2 minutes ago"), 3)
        self.assertEqual(report.container_exit_code("Restarting (1) 5 seconds ago"), 1)
        self.assertIsNone(report.container_exit_code("Up 3 hours"))

    def test_parse_percent(self):
        self.assertEqual(report.parse_percent("12.5%"), 12.5)
        self.assertIsNone(report.parse_percent("--"))
        self.assertIsNone(report.parse_percent(None))


class TestSelection(unittest.TestCase):
    def test_include_and_exclude_globs_match_names_and_projects(self):
        containers = [_c("web-1", project="shop"), _c("db-1", project="shop"), _c("cache")]
        self.assertEqual(
            [c["name"] for c in report.select_containers(containers, include=["shop"])],
            ["web-1", "db-1"],
        )
        self.assertEqual(
            [c["name"] for c in report.select_containers(containers, exclude=["db-*"])],
            ["web-1", "cache"],
        )

    def test_build_rows_merges_stats_by_short_id(self):
        rows = report.build_rows(
            [_c("web", cid="abcdef123456")],
            {"abcdef123456": {"cpu": "5.0%", "mem_perc": "10%", "memory": "1MiB / 1GiB"}},
        )
        self.assertEqual(rows[0]["cpu_percent"], 5.0)
        self.assertEqual(rows[0]["mem_percent"], 10.0)


class TestEvaluate(unittest.TestCase):
    def test_all_healthy_is_ok(self):
        rows = report.build_rows([_c("web", status="Up 1 hour (healthy)")])
        findings = report.evaluate(rows)
        self.assertEqual(findings, [])
        self.assertEqual(report.overall_level(findings), report.EXIT_OK)
        self.assertTrue(report.format_check(findings, rows).startswith("DOCKTUI OK"))

    def test_problem_containers_are_flagged(self):
        rows = report.build_rows(
            [
                _c("sick", status="Up 1 minute (unhealthy)"),
                _c("loop", state="restarting", status="Restarting (1) 2 seconds ago"),
                _c("crashed", state="exited", status="Exited (2) 1 hour ago"),
                _c("stopped", state="exited", status="Exited (0) 1 hour ago"),
                _c("sigterm", state="exited", status="Exited (143) 1 hour ago"),
                _c("oom", state="exited", status="Exited (137) 1 hour ago"),
            ]
        )
        findings = report.evaluate(rows)
        by_name = {f.container: f.level for f in findings}
        self.assertEqual(by_name["sick"], report.EXIT_CRITICAL)
        self.assertEqual(by_name["loop"], report.EXIT_CRITICAL)
        self.assertEqual(by_name["crashed"], report.EXIT_CRITICAL)
        self.assertEqual(by_name["oom"], report.EXIT_WARNING)
        self.assertNotIn("stopped", by_name)
        self.assertNotIn("sigterm", by_name)
        self.assertEqual(report.overall_level(findings), report.EXIT_CRITICAL)

    def test_resource_thresholds_warn(self):
        rows = report.build_rows(
            [_c("busy", cid="busy00000000")],
            {"busy00000000": {"cpu": "95%", "mem_perc": "50%"}},
        )
        findings = report.evaluate(rows, cpu_warn=90, mem_warn=80)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, report.EXIT_WARNING)
        self.assertIn("CPU", findings[0].message)

    def test_required_containers(self):
        rows = report.build_rows([_c("db", state="exited", status="Exited (0) now")])
        findings = report.evaluate(rows, require_running=["db", "web*"])
        messages = {f.container: f.message for f in findings}
        self.assertIn("not running", messages["db"])
        self.assertIn("not found", messages["web*"])

    def test_check_json_payload(self):
        rows = report.build_rows([_c("sick", status="Up (unhealthy)")])
        payload = json.loads(report.check_json(report.evaluate(rows), rows))
        self.assertEqual(payload["status"], "CRITICAL")
        self.assertEqual(payload["exit_code"], 2)
        self.assertEqual(payload["summary"]["unhealthy"], 1)
        self.assertEqual(payload["findings"][0]["container"], "sick")


class TestFormatTable(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(report.format_table([]), "No containers found.")

    def test_table_lists_containers_and_summary(self):
        rows = report.build_rows([_c("web"), _c("job", state="exited", status="Exited (0)")])
        text = report.format_table(rows)
        self.assertIn("NAME", text.splitlines()[0])
        self.assertIn("web", text)
        self.assertIn("2 containers: 1 running, 1 exited", text)
        self.assertNotIn("\033[", text)
        self.assertIn("\033[", report.format_table(rows, color=True))


if __name__ == "__main__":
    unittest.main()
