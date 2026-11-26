"""Polling a drafting job never fails because another job's file vanished during the clean-up (22 Oct 2026: a 500 from
/api/replies/jobs/<id> when a finishing job removed its .prompt between the folder listing and the age check).
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from assist import replies


class VanishingFile(unittest.TestCase):
    def test_job_survives_a_file_removed_mid_listing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(replies, "JOB_DIR", pathlib.Path(d)):
            jid = "abcdef123456"
            (pathlib.Path(d) / f"{jid}.json").write_text(json.dumps({"running": False, "ok": True, "body": "hi"}))
            (pathlib.Path(d) / "000000000000.prompt").write_text("x")
            real = pathlib.Path.stat

            def stat(self, *a, **k):   # the .prompt is gone by the time it is looked at
                if self.name.endswith(".prompt"):
                    raise FileNotFoundError(self)
                return real(self, *a, **k)

            with mock.patch.object(pathlib.Path, "stat", stat):
                self.assertEqual(replies.job(jid)["body"], "hi")


if __name__ == "__main__":
    unittest.main()
