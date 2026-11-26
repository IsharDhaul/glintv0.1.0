"""The launchd template renders to a valid plist: 09:15, logs under ~/GlintData/logs."""

import plistlib

from glint.core.settings import REPO_ROOT

TEMPLATE = REPO_ROOT / "scripts" / "launchd" / "com.glint.refresh.plist.template"


def test_template_renders_to_a_valid_plist() -> None:
    text = (
        TEMPLATE.read_text()
        .replace("__REPO__", "/Users/me/Glint Repo")
        .replace("__UV__", "/opt/homebrew/bin/uv")
        .replace("__HOME__", "/Users/me")
    )
    plist = plistlib.loads(text.encode())
    assert plist["Label"] == "com.glint.refresh"
    assert plist["StartCalendarInterval"] == {"Hour": 9, "Minute": 15}
    assert plist["ProgramArguments"][-1] == (
        "cd '/Users/me/Glint Repo/engine' && exec '/opt/homebrew/bin/uv' run glint refresh"
    )
    assert plist["StandardOutPath"] == "/Users/me/GlintData/logs/refresh.out.log"
    assert plist["RunAtLoad"] is False
    assert "__" not in text
