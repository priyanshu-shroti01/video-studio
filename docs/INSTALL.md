# Installing Video Studio on your Mac

This guide is for people who don't usually use the Terminal. You need to type two things: one command that
installs everything, and one that opens the app.

**You need:**

- a Mac with Apple silicon (M1 or newer). On an Intel Mac it installs, but making videos is slow;
- a recent version of macOS (13 Ventura or newer);
- about 6 GB of free disk space, plus room for your videos;
- an internet connection (only while installing; after that, everything runs on your Mac);
- the password you use to log in to the Mac.

## 1. Open Terminal

Terminal is an app that comes with every Mac.

1. Press **Command (⌘) + Space** to open Spotlight search.
2. Type **Terminal** and press **Return**.

A window with a blinking cursor opens. You type commands there and press **Return** to run them.

## 2. Paste the install command

Copy this whole line, paste it into Terminal (**⌘ + V**), and press **Return**:

```bash
curl -fsSL https://raw.githubusercontent.com/priyanshu-shroti01/video-studio/main/install.sh | bash
```

The installer shows numbered steps, from `[1/12] Checking your Mac` to `[12/12] Adding the videostudio command`.
Leave the window open until it says **Video Studio is installed.**

### What it asks you

- **Your Mac password.** This only happens if Homebrew (the free tool Video Studio uses to install ffmpeg, node and
  the other parts) is not on your Mac yet. Type the password you use to log in to the Mac and press **Return**.
  **Nothing appears on screen while you type the password.** That is normal.
- **"Press RETURN to continue"** (also from Homebrew): press **Return**.
- **A window asking to install the "command line developer tools".** Click **Install** and wait for it to
  finish. The installer then carries on by itself.

Nothing else needs your input.

### How long it takes

Usually 20 to 60 minutes, depending on your internet speed. It downloads about 4 GB in total:

| Part | Size |
|---|---|
| Voices (read your scripts aloud, on your Mac) | about 840 MB |
| AI writing model (writes video ideas, on your Mac) | about 2.5 GB |
| Browser that draws the videos | about 150 MB |
| Video engine and Python parts | about 500 MB |
| Homebrew tools (ffmpeg, node, uv, Ollama), if missing | a few hundred MB |

While a long step runs, the installer prints `still working (N min so far)...` every 30 seconds.

### If the internet drops or something fails

Run the same install command again. Finished steps are skipped (it says `Already done, skipping.`), so it
continues where it stopped. If it still fails, it prints the path of a log file, for example
`~/VideoStudio/.pipeline/install/logs/install-20261114-101500.log`. Send that file to whoever helps you with
Video Studio.

## 3. Open Video Studio

When the installer has finished, **close the Terminal window and open a new one** (so the Mac finds the new
command). Then type:

```bash
videostudio
```

The Studio opens in your web browser at **http://127.0.0.1:8765/**. This address is on your own Mac: nothing is put on
the internet, and nothing is published without your explicit confirmation.

Next time, open Terminal and type `videostudio` again. You can also bookmark http://127.0.0.1:8765/; the bookmark
works while the Studio is running.

## Everyday commands

Type these in Terminal:

| Command | What it does |
|---|---|
| `videostudio` | Starts the Studio if needed and opens it in your browser |
| `videostudio stop` | Stops the Studio (it keeps running in the background until you do this or restart the Mac) |
| `videostudio status` | Tells you whether the Studio is running |
| `videostudio update` | Downloads the newest version. Your videos, projects and brands are kept |
| `videostudio doctor` | Checks that everything Video Studio needs is installed |
| `videostudio logs` | Shows the Studio's recent messages (`videostudio logs -f` keeps watching) |

## Where your files are

Everything lives in the **VideoStudio** folder in your home folder (in Finder: **Go → Home**, then
**VideoStudio**):

- `video-out/`: copies of your finished videos, sorted by brand. Start here;
- `output/`: everything the Studio made (productions, previews, reports);
- `projects/`, `brands/`, `knowledge/`: your briefs, your websites' brand settings and their verified facts;
- `.pipeline/`: the Studio's own records (hidden folder; press **⌘ + Shift + .** in Finder to show it).

Updating (`videostudio update`, or running the install command again) replaces only the program files. It never
replaces anything in `output/`, `video-out/`, `projects/`, `brands/`, `knowledge/`, `.pipeline/`,
`public/brands/` or `audio/music/`. It only adds new example files that you don't have yet. Before each update it also
saves a copy of your brands, facts and projects in `.pipeline/backups/`.

## Uninstalling

1. Stop the Studio: `videostudio stop`.
2. **Keep your videos:** copy `~/VideoStudio/video-out` (and `output`, `projects`, `brands`, `knowledge` if you
   want to keep your work) somewhere else, for example your Documents folder.
3. Delete the `VideoStudio` folder from your home folder (drag it to the Bin). This removes the program, the voices
   and everything inside it.
4. Remove the command: in Terminal, type `rm ~/.local/bin/videostudio`.
5. Optional, to free more space:
   - the AI model: `ollama rm qwen3:4b-instruct-2507-q4_K_M` (about 2.5 GB);
   - download caches: delete `~/.cache/uv` and `~/.npm` (they are recreated if needed);
   - the tools, if nothing else uses them: `brew uninstall ffmpeg uv node ollama`.
6. Optional: the installer added a line starting with `export PATH="$HOME/.local/bin` to the file `.zprofile` in
   your home folder (under a line saying `# Added by the Video Studio installer`). You can delete those lines. They do no harm
   if you leave them.

## Troubleshooting

**`zsh: command not found: videostudio`**: open a new Terminal window (the installer changed a setting that only new
windows see). If it still happens, run `~/.local/bin/videostudio`, or run the install command again.

**The installer says "Something went wrong"**: run the install command again. It skips what is already done. The
message names the step and the log file. Common causes:

- no internet connection, or the connection dropped during a large download;
- the disk is full (the installer warns when there is less than 10 GB free);
- the Mac password was typed wrongly three times (Homebrew step): run the command again.

**`curl: (6) Could not resolve host`**: no internet connection. Check Wi-Fi and try again.

**The browser shows "This site can't be reached"**: the Studio is not running. Type `videostudio` in Terminal. If it
says it could not start, run `videostudio logs` and `videostudio doctor` and send the output to whoever helps you.

**"Something else is running on port 8765"**: another copy of the Studio was started in a different way (for
example in another Terminal window). Close that window, or press **Control + C** in it, then type `videostudio`.

**`videostudio doctor` shows FAIL lines**: run the install command again; it fixes missing parts. `WARN` lines are
fine. For example, `sfx.kit` only means the optional sound-effects kit is missing.

**"This Mac has an Intel processor"**: Video Studio still installs, but it is made for Apple silicon. Videos take
much longer to make.

## For helpers and developers

- See what the installer would do, without changing anything:
  `curl -fsSL …/install.sh | bash -s -- --dry-run` (or `VIDEOSTUDIO_DRY_RUN=1`).
- `--verbose` (or `VIDEOSTUDIO_VERBOSE=1`) shows every command's output on screen, not only in the log.
- `VIDEOSTUDIO_HOME=/some/folder` installs somewhere other than `~/VideoStudio`. The `videostudio` command finds
  its folder through the `~/.local/bin/videostudio` link.
- Finished steps are recorded in `~/VideoStudio/.pipeline/install/*.done`. Each file holds a key: a hash of
  `package-lock.json` for the video engine, of `uv.lock` for the Python parts, the model name for the AI model,
  and so on. A step runs again when its key changes or its output is missing. Delete a `.done` file to force that
  step to run again.
- The Studio's process id and log are in `~/VideoStudio/.pipeline/studio/` (`studio.pid`, `studio.log`).
  `VIDEOSTUDIO_PORT` changes the port, and `VIDEOSTUDIO_NO_BROWSER=1` starts the Studio without opening the browser.
- The installer refuses to download over a Git checkout (a folder containing `.git`). Developers update with `git pull`
  and follow the README Quick start.
