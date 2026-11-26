"""Open in Outlook desktop (assist/outlook_desktop.py): the mailto: link carries only real addresses, and the subject and
text are percent-encoded so a line in them cannot add a header or a recipient.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import unittest
from unittest import mock

from assist import outlook_desktop as od


class Desktop(unittest.TestCase):
    def test_the_link_is_safe_and_complete(self):
        u = od.url(["gray.selby@acme.example", "Gray", "x@y.com&bcc=evil@z.com"], ["rowan.lowell@acme.example"], "Re: Q4 & more",
                   "Hi Gray,\n\nbcc=evil@z.com\n-Sam")
        self.assertTrue(u.startswith("mailto:gray.selby@acme.example?cc=rowan.lowell@acme.example&subject=Re%3A%20Q4%20%26%20more&body=Hi%20Gray%2C%0A%0A"))
        self.assertNotIn("&bcc", u)
        self.assertEqual(u.count("&"), 2)

    def test_compose_opens_outlook_itself(self):
        with mock.patch.object(od.subprocess, "run") as run, mock.patch.object(od, "APP") as app:
            app.is_dir.return_value = True
            app.__str__.return_value = "/Applications/Microsoft Outlook.app"
            od.compose(["a@b.com"], [], "S", "B")
        self.assertEqual(run.call_args[0][0][:3], ["open", "-a", "/Applications/Microsoft Outlook.app"])


if __name__ == "__main__":
    unittest.main()
