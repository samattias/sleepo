#!/bin/zsh
# Install SleePO for one person on their own Mac (DESIGN-PERSONALISATION.md phase 6).
#
#   scripts/install.sh [DATA_FOLDER] [--org-pack FILE] [--start-at-login] [--skip-venv]
#
# DATA_FOLDER (default ~/SleePO) holds everything that is yours: memory/ (your context pages, people, initiatives),
# inbox/, drafts/, briefs/, org/pack.json, CLAUDE.md and .claude/skills. The code stays where this script is. The
# database is in ~/Library/Application Support/Assist. Nothing here is ever overwritten: files that exist are kept.
# Run it from a folder outside OneDrive or iCloud (macOS keeps background apps out of those).
set -e
APP="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$HOME/SleePO"; ORG_PACK=""; LOGIN=0; SKIP_VENV=0
while [ $# -gt 0 ]; do
  case "$1" in
    --org-pack) ORG_PACK="$2"; shift 2 ;;
    --start-at-login) LOGIN=1; shift ;;
    --skip-venv) SKIP_VENV=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) DATA="$1"; shift ;;
  esac
done
DATA="${DATA:A}"
VENV="$HOME/.assist/venv"
say() { print -P "%B==>%b $1" }

# An install where code and data already live together (the original one) is left alone.
if [ ! -f "$HOME/.assist/home" ] && [ -d "$APP/memory" ] && [ "$DATA" != "$APP" ]; then
  print "This Mac already runs SleePO from $APP (code and data together). Not changing it."
  print "To move the data elsewhere, do it by hand and write the folder's path to ~/.assist/home."
  exit 1
fi

say "Code: $APP"
say "Your data: $DATA"

# 1. Python environment (~/.assist/venv) with SleePO's packages; `assist` importable from any folder
if [ "$SKIP_VENV" = 0 ]; then
  command -v python3 >/dev/null || { print "python3 is missing: install the Xcode Command Line Tools (xcode-select --install)."; exit 1 }
  [ -x "$VENV/bin/python" ] || { say "Creating $VENV"; python3 -m venv "$VENV" }
  say "Installing packages"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$APP/requirements.txt"
fi
if [ -x "$VENV/bin/python" ]; then
  SITE="$("$VENV/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
  print "$APP" > "$SITE/sleepo.pth"
fi

# 2. Your data folder, from the templates (existing files are kept)
mkdir -p "$DATA"/{inbox/queue,drafts,briefs,org,.claude}
cp -Rn "$APP/templates/data/." "$DATA/" 2>/dev/null || true
[ -d "$DATA/.claude/skills" ] || cp -R "$APP/.claude/skills" "$DATA/.claude/skills"
if [ -n "$ORG_PACK" ]; then
  [ -f "$ORG_PACK" ] || { print "No org pack at $ORG_PACK"; exit 1 }
  [ -f "$DATA/org/pack.json" ] || cp "$ORG_PACK" "$DATA/org/pack.json"
fi
mkdir -p "$HOME/.assist"
[ "$DATA" = "$APP" ] || print "$DATA" > "$HOME/.assist/home"

# 3. The launcher, the Claude Desktop relay and the database
cat > "$DATA/Open SleePO.command" <<EOF
#!/bin/zsh
# Double-click to open SleePO: starts the server if it is not running, then opens the app.
if ! curl -s --max-time 2 http://localhost:8765/status >/dev/null; then
  cd "$DATA" && ASSIST_HOME="$DATA" nohup "$VENV/bin/python" -m assist.cli serve 8765 >"\$TMPDIR/sleepo.out" 2>"\$TMPDIR/sleepo.err" &
  sleep 3
fi
open http://localhost:8765/
EOF
chmod +x "$DATA/Open SleePO.command"
[ -f "$HOME/.assist/sleepo_mcp.py" ] || cp "$APP/scripts/sleepo_mcp.py" "$HOME/.assist/sleepo_mcp.py"
[ -x "$VENV/bin/python" ] && (cd "$DATA" && ASSIST_HOME="$DATA" "$VENV/bin/python" -m assist.cli migrate >/dev/null) && say "Database ready"

# 4. Start at login (optional)
if [ "$LOGIN" = 1 ]; then
  PLIST="$HOME/Library/LaunchAgents/com.sleepo.serve.plist"
  if [ ! -f "$PLIST" ]; then
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.sleepo.serve</string>
  <key>ProgramArguments</key><array><string>$VENV/bin/python</string><string>-m</string><string>assist.cli</string><string>serve</string><string>8765</string></array>
  <key>WorkingDirectory</key><string>$DATA</string>
  <key>EnvironmentVariables</key><dict><key>ASSIST_HOME</key><string>$DATA</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/sleepo.log</string><key>StandardErrorPath</key><string>$HOME/Library/Logs/sleepo.log</string>
</dict></plist>
EOF
    launchctl load -w "$PLIST" && say "SleePO starts at login"
  fi
fi

# 5. What is left to do by hand
[ -f "$APP/web/dist/index.html" ] || print "\n! No built app pages in $APP/web/dist: build assist-web (pnpm build) and copy its dist there, or set ASSIST_WEB_DIST."
[ -d "$APP/.git" ] || print "\n! $APP was downloaded without git, so SleePO can't update itself. To get updates, download it again with: git clone <the GitHub address>"
cat <<EOF

Next: open SleePO and follow its setup (who you are, your company, what it can read on this Mac, your bets, the first import):
  open "$DATA/Open SleePO.command"

Recommended: SleePO runs without them, and works best with these two apps.
  - Granola (https://granola.ai): meeting notes and transcripts. Add its API key (Granola › Settings › API) in
    SleePO's setup, then sign in once for the slides shown in calls and the live call:
      $VENV/bin/python -m assist.cli granola-login
  - FluidVoice (https://github.com/altic-dev/FluidVoice): dictation into every SleePO box. The first time you click
    a microphone in SleePO, allow Python under System Settings › Privacy & Security › Accessibility.

Optional, later:
  - Claude Desktop: add to ~/Library/Application Support/Claude/claude_desktop_config.json
    "mcpServers": {"sleepo": {"command": "/usr/bin/python3", "args": ["$HOME/.assist/sleepo_mcp.py"]}}
  - Check the install:  ASSIST_HOME="$DATA" $VENV/bin/python -m assist.cli doctor
EOF
