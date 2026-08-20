# -*- coding: utf-8 -*-
# callback_plugins/nier_boot.py
#
# NieR:Automata "YoRHa boot screen" stdout callback for Ansible.
# Purely cosmetic: it changes how results are printed, never what runs.
#
#   [defaults]
#   callback_plugins = ./callback_plugins
#   stdout_callback  = nier_boot
#
# Preview without Ansible:  python3 tools/preview_boot.py

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
    name: nier_boot
    type: stdout
    short_description: Renders playbook runs as a YoRHa android boot sequence
    description:
      - Cosmetic stdout callback styled after the NieR:Automata boot screen.
      - One line per task; units are aggregated and only stragglers are listed.
    options:
      intro:
        description: Print the boot preamble before the first play.
        type: bool
        default: true
        env: [{name: NIER_INTRO}]
        ini: [{section: nier_boot, key: intro}]
      emblem:
        description: Draw the YoRHa emblem above the preamble.
        type: bool
        default: true
        env: [{name: NIER_EMBLEM}]
        ini: [{section: nier_boot, key: emblem}]
      wordmark:
        description: Text shown under the emblem, letter-spaced.
        type: str
        default: NANoNoDe
        env: [{name: NIER_WORDMARK}]
        ini: [{section: nier_boot, key: wordmark}]
      unit_name:
        description: Unit name reported in the preamble.
        type: str
        default: NANONODE
        env: [{name: NIER_UNIT_NAME}]
        ini: [{section: nier_boot, key: unit_name}]
      typewriter:
        description: Animate the preamble character by character. Needs a TTY.
        type: bool
        default: true
        env: [{name: NIER_TYPEWRITER}]
        ini: [{section: nier_boot, key: typewriter}]
      typewriter_delay:
        description: Seconds between characters while animating.
        type: float
        default: 0.006
        env: [{name: NIER_TYPEWRITER_DELAY}]
        ini: [{section: nier_boot, key: typewriter_delay}]
      animate_tasks:
        description:
          - Redraw the running task's line in place as units report. Needs a TTY;
            piped output prints final lines only.
        type: bool
        default: true
        env: [{name: NIER_ANIMATE_TASKS}]
        ini: [{section: nier_boot, key: animate_tasks}]
      spin_interval:
        description: Seconds between repaints of the running task line.
        type: float
        default: 0.08
        env: [{name: NIER_SPIN_INTERVAL}]
        ini: [{section: nier_boot, key: spin_interval}]
      show_ok:
        description: Print tasks where every unit was OK. False logs only changes and faults.
        type: bool
        default: true
        env: [{name: NIER_SHOW_OK}]
        ini: [{section: nier_boot, key: show_ok}]
      paint_background:
        description: Fill every line with the NieR olive background.
        type: bool
        default: true
        env: [{name: NIER_PAINT_BACKGROUND}]
        ini: [{section: nier_boot, key: paint_background}]
      clear_screen:
        description:
          - Retint the terminal and flood the viewport so no default-coloured gaps
            show through. Restored on exit. Needs a TTY.
        type: bool
        default: true
        env: [{name: NIER_CLEAR_SCREEN}]
        ini: [{section: nier_boot, key: clear_screen}]
      max_width:
        description: Cap layout width in columns. 0 uses the whole terminal.
        type: int
        default: 0
        env: [{name: NIER_MAX_WIDTH}]
        ini: [{section: nier_boot, key: max_width}]
      slow_threshold:
        description: Show a task's duration when it ran longer than this. 0 disables.
        type: float
        default: 5.0
        env: [{name: NIER_SLOW_THRESHOLD}]
        ini: [{section: nier_boot, key: slow_threshold}]
      diff_lines:
        description: Maximum diff lines printed per task under --diff. 0 is unlimited.
        type: int
        default: 40
        env: [{name: NIER_DIFF_LINES}]
        ini: [{section: nier_boot, key: diff_lines}]
      timing_report:
        description:
          - How many tasks the closing timing report lists, in execution order. A
            positive number keeps that many of the slowest, 0 disables the report,
            and a negative number lists every task that ran.
        type: int
        default: 10
        env: [{name: NIER_TIMING_REPORT}]
        ini: [{section: nier_boot, key: timing_report}]
"""

import atexit
import difflib
import json
import os
import shutil
import signal
import sys
import threading
import time

DEFAULTS = {
    "intro": True,
    "emblem": True,
    "wordmark": "NANoNoDe",
    "unit_name": "NANONODE",
    "typewriter": True,
    "typewriter_delay": 0.006,
    "animate_tasks": True,
    "spin_interval": 0.08,
    "show_ok": True,
    "paint_background": True,
    "clear_screen": True,
    "max_width": 0,
    "slow_threshold": 5.0,
    "diff_lines": 40,
    "timing_report": 10,
}


def _coerce(value, default):
    """Env vars and ini values arrive as strings; DEFAULTS defines the type."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "on")
    if isinstance(default, float):
        return float(value or 0)
    if isinstance(default, int):
        return int(value or 0)
    return str(value)


try:  # only present under Ansible; used to detect --check
    from ansible import context as ansible_context
except ImportError:
    ansible_context = None

try:
    from ansible.plugins.callback import CallbackBase
except ImportError:  # --demo mode, outside Ansible

    class CallbackBase(object):  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass

        def get_option(self, name):
            # honour the same env vars Ansible would, so --demo can try options
            return os.environ.get("NIER_" + name.upper(), DEFAULTS.get(name))


# Palette: bone text on dark olive.
BG = (69, 65, 56)
FG = (209, 205, 183)
FG_BRIGHT = (245, 242, 226)
FG_DIM = (140, 136, 119)
FG_ALERT = (204, 76, 57)
FG_WARN = (198, 160, 74)

RESET = "\033[0m"
DOT = "·"
RULE = "─"
SPINNER = ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "▊", "▋", "▌", "▍", "▎"]

# Bars in the timing report, drawn with eighth-width blocks for sub-cell precision.
BAR_WIDTH = 16
BLOCK = "█"
EIGHTHS = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]

COLOUR = {
    "OK": FG,
    "SKIP": FG_DIM,
    "CHANGED": FG_BRIGHT,
    "WOULD CHANGE": FG_WARN,
    "IGNORED": FG_WARN,
    "FAILURE": FG_ALERT,
    "NO SIGNAL": FG_ALERT,
}
# Which result wins when units disagree; >= IGNORED always gets its own line.
SEVERITY = {
    "OK": 0,
    "SKIP": 1,
    "CHANGED": 2,
    "WOULD CHANGE": 2,
    "IGNORED": 3,
    "FAILURE": 4,
    "NO SIGNAL": 5,
}

# Distinct from None, which is a legitimate role ("STANDALONE").
_UNSET = object()

# YoRHa emblem, traced from the insignia by tools/update_emblem.py: it downsamples
# the image and maps each cell's coverage onto a density ramp. Baked in as text so
# nothing needs an image library at runtime. Re-run that script to change it.
EMBLEM_ART = """\
                   +`              :=
                  .%+              %*
                  +%-.            :@:-
                  %%.=     .      +@.+
                 .@% +     #+     %@.+
                 -@% +    -@+`    @@.=.
                 =@% +    #@.+   `@@.::
                 +@% =.   @@ +   :@@.`=
                 *@% -:  .@@ +   -@@..=
                 #@% :: .`@@ * ` =@@. +
                 #@% :-+*:@@ + #-=@@. *
                 #@% =-%@:@@ =:@*+@@.`*
                =+++=+++%+@@ =+#==++=++-
               =#%@+%@##-@@@ =@`##@#*@%#-
                  =@%.`%%*@@ =*%% `@@:
                  @%##  `:*@-=``  %#%%
            +**:  =@-#*-+@%:=@%+:#*=@:  :+*=
          -:@@@-*= -@*+##:%%@#-##+*%:.=+=@@@:`
          :**@**@@: +@%%*:#@@+=*%%@- -@@=%@=#`
        -##%+@@=%@+#@*  :+@@@%=`  #@+*@#=@@-*:-`
     .+@@#==@@@@++%=*+-: `*@@=` :-++=%=+@@@@*-.`-:
   `*%*-:::=`.:+@%=@@@@@:+%@@#+=@@@@@-%@+:.:*%@#+---.
 :##+-::.       -@-@@@@@@@:@%-@@@@@@@-@`       `-+**#+`
::.           -@@%.@=--=*@%::@@*=--+@+.:+`           `-`
             .@@#. *     =@@:#:    `@@*  +
             *@# :=.    :@@@  +.    `#@%.`=
            -@+`=`       %@@  +       :%@:=`
           .@+=:         +@@ :-         =%=+
           **-           .@@ +            +%=
          :*.             #@.+             `#.
                          -@+.
                           @*
                           -`
"""


def duration(seconds):
    """Compact and monotonic in width: 8.4s, 1:47.3, 1:02:33."""
    if seconds < 60:
        return "%.1fs" % seconds
    if seconds < 3600:
        return "%d:%04.1f" % (seconds // 60, seconds % 60)
    return "%d:%02d:%02d" % (seconds // 3600, seconds % 3600 // 60, seconds % 60)


class Painter(object):
    """Builds SGR strings that keep the NieR background on every cell."""

    def __init__(self, background=True, enabled=True):
        self.background = background
        self.enabled = enabled

    def __call__(self, text, rgb=FG, bold=False):
        if not self.enabled:
            return text
        parts = (["1"] if bold else []) + ["38;2;%d;%d;%d" % rgb]
        if self.background:
            parts.append("48;2;%d;%d;%d" % BG)
        return "\033[%sm%s%s" % (";".join(parts), text, RESET)

    def bg_only(self):
        return "\033[48;2;%d;%d;%dm" % BG if self.enabled and self.background else ""


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "stdout"
    CALLBACK_NAME = "nier_boot"

    def __init__(self, *args, **kwargs):
        super(CallbackModule, self).__init__(*args, **kwargs)
        self._tty = sys.stdout.isatty()
        self._task = ""
        self._task_role = _UNSET  # role of the task currently buffered
        self._printed_role = _UNSET  # role whose header is already on screen
        self._intro_done = False
        self._opts_loaded = False
        self._screen_owned = False
        self._start = time.time()
        # live task-line state, shared with the repaint thread
        self._lock = threading.RLock()
        self._results = []
        self._notes = []
        self._seen_notes = set()
        self._task_start = time.time()
        self._timings = []  # (role, task, seconds) for the closing report
        self._pending = []  # units this task is still waiting on, in start order
        self._header_lines = 0  # header rows emitted with the current running line
        self._prev_printed_role = _UNSET
        self._open = False
        self._spin = 0
        self._ticker = None
        self._stop = None
        self._prev_signals = {}
        self.p = Painter()

    # -- options ------------------------------------------------------- #
    def set_options(self, task_keys=None, var_options=None, direct=None):
        try:
            super(CallbackModule, self).set_options(
                task_keys=task_keys, var_options=var_options, direct=direct
            )
        except AttributeError:
            pass
        self._load_opts()

    def _load_opts(self):
        if self._opts_loaded:
            return
        for name, default in DEFAULTS.items():
            try:
                value = self.get_option(name)
            except Exception:
                value = None
            setattr(self, "opt_" + name, _coerce(default if value is None else value, default))
        # animation and screen ownership only make sense on a terminal
        for name in ("typewriter", "animate_tasks", "clear_screen"):
            setattr(self, "opt_" + name, getattr(self, "opt_" + name) and self._tty)
        colour = not (os.environ.get("NO_COLOR") or os.environ.get("ANSIBLE_NOCOLOR"))
        colour = colour and (self._tty or bool(os.environ.get("NIER_FORCE_COLOR")))
        self.p = Painter(self.opt_paint_background, colour)
        self._opts_loaded = True

    # -- primitives ---------------------------------------------------- #
    @property
    def _cols(self):
        """Drawable width: the terminal minus one column.

        Filling the final column is what makes a terminal mark a line as soft
        wrapped. It then reflows those lines on any repaint - a resize, the
        screen waking up, some mouse events - and the whole log appears to shift.
        Stopping one column short means no line is ever a wrap candidate.
        """
        try:
            columns = shutil.get_terminal_size((100, 24)).columns
        except Exception:
            columns = 100
        return max(40, columns - 1)

    @property
    def _width(self):
        return min(self._cols, self.opt_max_width) if self.opt_max_width else self._cols

    def _write(self, text):
        sys.stdout.write(text)
        sys.stdout.flush()

    def _pad(self, used):
        return " " * max(0, self._cols - used)

    def _emit(self, text, animate=False):
        if animate and self.opt_typewriter and self.opt_typewriter_delay > 0:
            for char in text:
                self._write(char)
                time.sleep(self.opt_typewriter_delay)
            self._write("\n")
        else:
            self._write(text + "\n")

    def _blank(self):
        self._emit(self.p(self._pad(0)))

    def _dotted(self, label, right, rgb, bold=False, indent=2, note=""):
        """`  LABEL ······ note RIGHT`, padded to exactly the drawable width.

        The arithmetic is deliberately explicit: the line always keeps at least
        two leader dots, so that minimum has to be reserved before the label is
        measured. Reserving it afterwards overflows by two columns whenever the
        label happens to fill the budget - which then wraps and reflows.
        """
        label = " " * indent + label.upper()
        note = (note + " ") if note else ""
        width = self._cols
        if width - len(right) - len(note) - 4 < 1:  # pathologically narrow
            note = ""
            right = right[: max(0, width - 6)]
        avail = max(2, width - len(note) - len(right) - 2)  # 2 = spaces each side
        if len(label) > avail - 2:
            label = label[: max(0, avail - 3)] + "…"
        dots = max(2, avail - len(label))
        used = len(label) + 2 + dots + len(note) + len(right)
        return (
            self.p(label, FG)
            + self.p(" " + DOT * dots + " ", FG_DIM)
            + self.p(note, FG_DIM)
            + self.p(right, rgb, bold=bold)
            + self.p(self._pad(used))
        )

    def _centred(self, text, rgb=FG, bold=False):
        pad = max(0, (self._width - len(text)) // 2)
        self._emit(
            self.p(" " * pad)
            + self.p(text, rgb, bold=bold)
            + self.p(self._pad(pad + len(text)))
        )

    def _banner(self, text, rgb=FG_BRIGHT, animate=False):
        self._emit(
            self.p(text.upper(), rgb, bold=True) + self.p(self._pad(len(text))),
            animate=animate,
        )

    def _note(self, text, rgb=FG_DIM, indent=6):
        for raw in str(text).splitlines():
            line = (" " * indent + raw)[: self._width]
            self._emit(self.p(line, rgb) + self.p(self._pad(len(line))))

    @staticmethod
    def _note_colour(line, default):
        """Diff hunks read far better when additions and removals differ."""
        stripped = line.strip()
        if stripped.startswith("+") and not stripped.startswith("+++"):
            return FG_BRIGHT
        if stripped.startswith("-") and not stripped.startswith("---"):
            return FG_ALERT
        if stripped.startswith("@@"):
            return FG_WARN
        return default

    def _rule(self, label):
        label = " %s " % label.upper()
        fill = max(0, self._width - len(label) - 6)
        self._emit(
            self.p(RULE * 4, FG_DIM)
            + self.p(label, FG_BRIGHT, bold=True)
            + self.p(RULE * fill, FG_DIM)
            + self.p(self._pad(len(label) + fill + 4))
        )

    # -- screen ownership ---------------------------------------------- #
    def _fill_screen(self):
        """OSC 11/10 retint the terminal defaults so rows scrolling in later are
        already in palette; the erase floods what is on screen now."""
        if not (self.opt_clear_screen and self.p.enabled and self.p.background):
            return
        self._write(
            "\033]11;#%02x%02x%02x\007" % BG
            + "\033]10;#%02x%02x%02x\007" % FG
            + "\033[?7l"  # autowrap off: a miscounted width clips, never wraps
            # Mouse tracking left enabled by a previous program turns every
            # mouse move into bytes on stdin, which the tty echoes into our
            # output and drags the cursor off the line we are redrawing.
            + "\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l"
            + self.p.bg_only()
            + "\033[2J\033[3J\033[H"
        )
        self._screen_owned = True
        atexit.register(self._release_screen)
        # atexit alone loses the race if we are killed, which would leave the
        # user's terminal tinted; hand the colours back on the way out instead.
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._prev_signals[sig] = signal.getsignal(sig)
                signal.signal(sig, self._on_signal)
            except (ValueError, OSError):  # not the main thread, or unsupported
                self._prev_signals.pop(sig, None)

    def _on_signal(self, signum, frame):
        self._stop_spinner()
        self._release_screen()
        previous = self._prev_signals.get(signum)
        if callable(previous):
            previous(signum, frame)
        else:  # restore the default action and let it happen for real
            signal.signal(signum, previous or signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    def _release_screen(self):
        if not self._screen_owned:
            return
        self._screen_owned = False
        try:
            tail = "\n" if self._open else ""  # the running row has no newline yet
            self._open = False
            self._write(tail + "\033[?7h\033]110\007\033]111\007" + RESET)
        except Exception:
            pass

    # -- boot preamble -------------------------------------------------- #
    def _intro(self, playbook=""):
        if self._intro_done:
            return
        self._intro_done = True
        self._fill_screen()
        if not self.opt_intro:
            return
        self._blank()
        if self.opt_emblem:
            art = EMBLEM_ART.strip("\n").split("\n")
            art_width = max(len(line) for line in art)
            if self._width >= art_width + 2:
                lpad = max(0, (self._width - art_width) // 2)
                for line in art:
                    self._emit(
                        self.p(" " * lpad)
                        + self.p(line, FG_BRIGHT)
                        + self.p(self._pad(lpad + len(line)))
                    )
                    if self.opt_typewriter:
                        time.sleep(0.025)
                self._blank()
                self._centred(" ".join(self.opt_wordmark), FG_BRIGHT, bold=True)
        self._blank()
        self._emit(self.p("/" * self._cols, FG_DIM))
        self._banner("BOOT SYSTEM", FG_BRIGHT, animate=True)
        for line in (
            "UNIT  : %s ORCHESTRATION CONTROL" % self.opt_unit_name,
            "MODEL : ANSIBLE CONTROL NODE",
            "TASK  : %s" % (playbook or "UNSPECIFIED"),
            "MODE  : SIMULATION - NO CHANGES WILL BE COMMITTED"
            if self._check_mode
            else "MODE  : LIVE",
        ):
            self._banner(line, FG_WARN if line.startswith("MODE  : S") else FG, animate=True)
        self._emit(self.p("/" * self._cols, FG_DIM))
        self._blank()
        for check in (
            "CHECKING CONTROL NODE INTEGRITY",
            "CHECKING SSH TRANSPORT",
            "CHECKING INVENTORY DATA",
            "CHECKING VAULT CREDENTIALS",
            "LOADING COLLECTION INDEX",
            "LOADING ROLE DEFINITIONS",
        ):
            self._emit(self._dotted(check, "OK", FG, indent=0))
            if self.opt_typewriter:
                time.sleep(0.05)
        self._blank()
        self._banner("ALL SYSTEMS NOMINAL", FG_BRIGHT, animate=True)
        self._banner("INITIATING DEPLOYMENT SEQUENCE", FG, animate=True)
        self._blank()

    # -- the live task line --------------------------------------------- #
    def _verdict(self):
        """(text, colour, bold) for the right-hand side of a finished task."""
        statuses = [status for _, status in self._results]
        if not statuses:
            return "NO UNITS", FG_DIM, False
        if len(set(statuses)) == 1:
            only = statuses[0]
            return "ALL %s" % only, COLOUR.get(only, FG), only != "OK"
        worst = max(statuses, key=lambda s: SEVERITY.get(s, 0))
        text = "%d/%d %s" % (statuses.count(worst), len(statuses), worst)
        return text, COLOUR.get(worst, FG), True

    def _waiting_on(self):
        """Names of the units still to report, abbreviated if there are many."""
        names = [name for name in self._pending if name]
        if not names:
            return ""
        if len(names) <= 3:
            return " ".join(names)
        return "%s +%d" % (" ".join(names[:2]), len(names) - 2)

    def _task_line(self, final):
        elapsed = time.time() - self._task_start
        note = ""
        if final:
            right, rgb, bold = self._verdict()
            if self.opt_slow_threshold and elapsed >= self.opt_slow_threshold:
                note = duration(elapsed)
        else:
            expected = max(len(self._pending) + len(self._results), 1)
            right = "%s %d/%d" % (
                SPINNER[self._spin % len(SPINNER)],
                len(self._results),
                expected,
            )
            # clock ticks along with the bar; the names are the useful part when a
            # task sits there for minutes - they say who has not come back
            note = " ".join(filter(None, (duration(elapsed), self._waiting_on())))
            rgb, bold = FG_WARN, False
        return self._dotted(self._task, right, rgb, bold=bold, note=note)

    def _repaint(self):
        """Redraw the open line in place. Caller holds the lock.

        Carriage return, not cursor-up: the running line is left without a
        trailing newline, so the cursor is still on that row and \r is enough to
        rewrite it. Vertical cursor moves are the fragile part - anything else
        that reaches the terminal in between (echoed mouse-tracking bytes, a
        stray write) leaves them pointing at the wrong row, and the display
        walks up the screen.
        """
        if self._open:
            self._write("\r" + self._task_line(False))

    def _tick(self):
        while not self._stop.wait(self.opt_spin_interval):
            with self._lock:
                self._spin += 1
                self._repaint()

    def _open_line(self):
        """Open the in-flight line, emitting the module header first.

        The header has to go out now rather than at flush time: the running line
        is already on screen, so inserting a header later would shove it down the
        terminal. `_header_lines` records what was emitted so the whole block can
        be taken back if the task turns out to be silent.
        """
        if self._open or not self.opt_animate_tasks:
            return
        self._prev_printed_role = self._printed_role
        self._header_lines = 0
        if self._task_role != self._printed_role:
            self._blank()
            self._rule("MODULE %s" % (self._task_role or "STANDALONE"))
            self._printed_role = self._task_role
            self._header_lines = 2
        self._write(self._task_line(False))  # no newline: the row stays ours
        self._open = True
        if self._ticker is None:
            self._stop = threading.Event()
            self._ticker = threading.Thread(target=self._tick, name="nier-spin")
            self._ticker.daemon = True
            self._ticker.start()

    def _stop_spinner(self):
        if self._stop is not None:
            self._stop.set()
        if self._ticker is not None:
            self._ticker.join(timeout=1.0)
            self._ticker = None

    def _rewind_open_block(self):
        """Put the cursor back above the running line and any header emitted with
        it, so whatever comes next overwrites the lot. Every line is padded to the
        full width, so nothing of the old block survives."""
        if self._open:
            # back to the start of the running row, then up over any header
            self._write("\r" + "\033[F" * self._header_lines)
            if self._header_lines:
                self._printed_role = self._prev_printed_role
        self._open = False
        self._header_lines = 0

    def _finish_task(self):
        """Ansible never says 'task done', so the previous line is closed when the
        next task, the next play, or the recap arrives."""
        with self._lock:
            if not self._results and not self._notes:
                self._rewind_open_block()
                return
            if self._results:
                self._timings.append(
                    (self._task_role, self._task, time.time() - self._task_start)
                )
            quiet = not self.opt_show_ok and all(
                status in ("OK", "SKIP") for _, status in self._results
            )
            if quiet:
                self._rewind_open_block()
            else:
                # The header is decided by the role of the task being flushed, not
                # by whatever task started most recently - includes, meta tasks and
                # skipped tasks produce no output and must not move a header.
                if self._task_role != self._printed_role:
                    if self._open:
                        self._write("\r")  # reuse the running row for the header
                        self._open = False
                    self._blank()
                    self._rule("MODULE %s" % (self._task_role or "STANDALONE"))
                    self._printed_role = self._task_role
                self._write(("\r" if self._open else "") + self._task_line(True) + "\n")
                statuses = [status for _, status in self._results]
                majority = max(set(statuses), key=statuses.count) if statuses else None
                for host, status in self._results:
                    if SEVERITY.get(status, 0) >= SEVERITY["IGNORED"] or status != majority:
                        self._emit(
                            self._dotted(host, status, COLOUR.get(status, FG), True, 7)
                        )
                for _, text, rgb in sorted(self._notes, key=lambda n: n[0]):
                    for line in str(text).splitlines():
                        self._note(line, self._note_colour(line, rgb))
            self._open = False
            self._results = []
            self._notes = []
            self._seen_notes = set()
            self._pending = []

    # -- Ansible hooks --------------------------------------------------- #
    def v2_playbook_on_start(self, playbook):
        self._load_opts()
        try:
            name = os.path.basename(playbook._file_name)
        except Exception:
            name = ""
        self._intro(name)

    def v2_playbook_on_play_start(self, play):
        self._load_opts()
        self._finish_task()
        self._intro()
        self._printed_role = _UNSET
        self._blank()
        self._rule("PLAY %s" % (play.get_name().strip() or "UNNAMED"))

    def v2_playbook_on_task_start(self, task, is_conditional):
        self._track(task)

    def v2_playbook_on_handler_task_start(self, task):
        self._track(task, handler=True)

    def _track(self, task, handler=False):
        self._load_opts()
        self._finish_task()
        try:
            role = task._role.get_name() if task._role else None
        except Exception:
            role = None
        name = task.get_name().strip()
        if role and name.startswith(role + " : "):
            name = name[len(role) + 3 :]
        with self._lock:
            self._task = ("HANDLER " if handler else "") + name
            self._task_role = role
            self._task_start = time.time()
            self._header_lines = 0

    def v2_runner_on_start(self, host, task):
        """Ansible names the unit it is about to run on, which is what lets the
        running line say which one has not reported back yet."""
        self._load_opts()
        try:
            name = host.get_name()
        except Exception:
            name = ""
        with self._lock:
            self._pending.append(name)
            self._repaint() if self._open else self._open_line()

    @property
    def _check_mode(self):
        try:
            return bool(ansible_context.CLIARGS.get("check"))
        except Exception:
            return False

    @property
    def _verbosity(self):
        return getattr(getattr(self, "_display", None), "verbosity", 0)

    def _add_note(self, text, rgb, rank=0):
        """Buffer a note, dropping duplicates - every unit reports the same
        warning, and three copies of it is noise. `rank` orders the block:
        faults and warnings first, bulky diff output last."""
        text = str(text).strip()
        if text and text not in self._seen_notes:
            self._seen_notes.add(text)
            self._notes.append((rank, text, rgb))

    def _collect_warnings(self, res):
        for warning in res.get("warnings") or []:
            self._add_note("WARNING: %s" % warning, FG_WARN)
        for item in res.get("deprecations") or []:
            if isinstance(item, dict):
                text = item.get("msg", "")
                if item.get("version"):
                    text = "%s (removed in %s)" % (text, item["version"])
            else:
                text = item
            self._add_note("DEPRECATION: %s" % text, FG_WARN)

    def _record(self, result, status, note_rgb=None):
        with self._lock:
            try:
                host = result._host.get_name()
            except Exception:
                host = "UNKNOWN"
            if host in self._pending:
                self._pending.remove(host)
            elif self._pending:
                self._pending.pop(0)  # unnamed start, drop the oldest
            self._results.append((host, status))
            self._collect_warnings(result._result)
            if note_rgb is not None:
                self._add_note(self._error(result), note_rgb)
            self._repaint()

    def v2_runner_on_ok(self, result):
        if not result._result.get("changed"):
            status = "OK"
        elif result._result.get("_ansible_check_mode") or self._check_mode:
            status = "WOULD CHANGE"
        else:
            status = "CHANGED"
        self._record(result, status)

    def v2_runner_on_skipped(self, result):
        self._record(result, "SKIP")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._record(
            result,
            "IGNORED" if ignore_errors else "FAILURE",
            FG_WARN if ignore_errors else FG_ALERT,
        )

    def v2_runner_on_unreachable(self, result):
        self._record(result, "NO SIGNAL", FG_ALERT)

    # Loop items are not units: Ansible still sends one final result per host
    # after the loop, so only a failing item is worth keeping.
    def v2_runner_item_on_ok(self, result):
        pass

    def v2_runner_item_on_skipped(self, result):
        pass

    def v2_runner_item_on_failed(self, result):
        with self._lock:
            self._add_note(self._error(result), FG_ALERT)

    def v2_runner_retry(self, result):
        res = result._result
        with self._lock:
            self._add_note(
                "RETRY %s/%s" % (res.get("attempts", 0), res.get("retries", 0)), FG_WARN
            )

    def v2_on_file_diff(self, result):
        """Ansible calls this once per host under --diff. Identical diffs are
        deduplicated, so a fleet-wide change is shown once, not once per unit."""
        diffs = result._result.get("diff") or []
        if isinstance(diffs, dict):
            diffs = [diffs]
        with self._lock:
            for diff in diffs:
                if not isinstance(diff, dict) or diff.get("prepared"):
                    text = (diff or {}).get("prepared", "")
                    if text:
                        self._add_note(text, FG_DIM, rank=1)
                    continue
                for line in self._render_diff(diff):
                    self._add_note(line, FG_DIM, rank=1)

    def _render_diff(self, diff):
        before, after = diff.get("before"), diff.get("after")
        if before is None and after is None:
            return []
        if not isinstance(before, str) or not isinstance(after, str):
            return ["DIFF: binary or structured content"]
        lines = list(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                diff.get("before_header") or "before",
                diff.get("after_header") or "after",
                lineterm="",
                n=2,
            )
        )
        limit = self.opt_diff_lines
        if limit and len(lines) > limit:
            hidden = len(lines) - limit
            lines = lines[:limit] + ["... %d more diff lines" % hidden]
        return lines

    def v2_playbook_on_no_hosts_matched(self):
        self._finish_task()
        self._note("NO UNITS MATCHED THIS DIRECTIVE", FG_WARN, indent=2)

    def v2_playbook_on_no_hosts_remaining(self):
        self._finish_task()
        self._note("NO OPERATIONAL UNITS REMAINING", FG_ALERT, indent=2)

    def _error(self, result):
        """One line normally; with -v, the module and a tail of its output."""
        res = result._result
        lines = []
        for key in ("msg", "stderr", "module_stderr", "reason"):
            if res.get(key):
                lines.append(str(res[key]).strip())
                break
        if not lines:
            try:
                lines.append(json.dumps(res)[:400])
            except Exception:
                lines.append("UNSPECIFIED FAULT")
        if self._verbosity >= 1:
            action = getattr(getattr(result, "_task", None), "action", None)
            head = "MODULE %s" % action if action else ""
            if res.get("rc") is not None:
                head = (head + "  RC %s" % res["rc"]).strip()
            if head:
                lines.append(head)
            if res.get("cmd"):
                cmd = res["cmd"]
                lines.append("CMD %s" % (" ".join(cmd) if isinstance(cmd, list) else cmd))
            for key in ("stdout", "module_stdout", "stderr"):
                text = str(res.get(key) or "").strip()
                if text and text not in lines:
                    tail = text.splitlines()[-8:]
                    lines.append("%s:" % key.upper())
                    lines.extend("  " + line for line in tail)
        return "\n".join(lines)

    def _timing_report(self):
        """Tasks in execution order, with a bar proportional to the slowest of
        them so the hog still stands out while the run reads chronologically."""
        limit = self.opt_timing_report
        if not limit or not self._timings:
            return
        ordered = list(enumerate(self._timings))
        if limit > 0:
            # keep the N slowest, then put them back in the order they ran
            ordered = sorted(ordered, key=lambda item: item[1][2], reverse=True)[:limit]
            ordered.sort(key=lambda item: item[0])
        slowest = max(entry[2] for _, entry in ordered) or 1.0
        self._blank()
        self._rule("OPERATION TIMING")
        self._blank()
        for _, (role, task, seconds) in ordered:
            label = "%s : %s" % (role, task) if role else task
            filled = seconds / slowest * BAR_WIDTH
            bar = BLOCK * int(filled)
            remainder = int((filled - int(filled)) * 8)
            if remainder:
                bar += EIGHTHS[remainder]
            self._emit(
                self._dotted(
                    label,
                    duration(seconds).rjust(8),
                    FG_BRIGHT,
                    note=bar.ljust(BAR_WIDTH),
                )
            )
        self._blank()
        self._emit(
            self._dotted(
                "TOTAL RUNTIME",
                duration(time.time() - self._start).rjust(8),
                FG,
                note=" " * BAR_WIDTH,
            )
        )

    # -- diagnostic report ------------------------------------------------ #
    def v2_playbook_on_stats(self, stats):
        self._load_opts()
        self._finish_task()
        self._stop_spinner()
        self._blank()
        self._rule("SYSTEM DIAGNOSTIC")
        self._blank()

        degraded = False
        for host in sorted(stats.processed.keys()):
            s = stats.summarize(host)
            if s["failures"] or s["unreachable"]:
                degraded = True
                verdict = "SIGNAL LOST" if s["unreachable"] else "DAMAGE DETECTED"
                rgb = FG_ALERT
            elif s["changed"]:
                if self._check_mode:
                    verdict, rgb = "WOULD RECONFIGURE", FG_WARN
                else:
                    verdict, rgb = "RECONFIGURED", FG_BRIGHT
            else:
                verdict, rgb = "NOMINAL", FG
            detail = "ok %-4d changed %-4d skipped %-4d failed %-4d unreachable %-4d" % (
                s["ok"],
                s["changed"],
                s["skipped"],
                s["failures"],
                s["unreachable"],
            )
            self._emit(self._dotted("UNIT %s  %s" % (host, detail), verdict, rgb, True))

        self._timing_report()

        if not (self.opt_timing_report and self._timings):
            elapsed = time.time() - self._start  # the report already totals this
            self._blank()
            self._banner("ELAPSED %s" % duration(elapsed), FG_DIM)
        self._blank()
        if degraded:
            closing = ("WARNING: SYSTEM DAMAGE DETECTED", "BOOT SEQUENCE INCOMPLETE")
        elif self._check_mode:
            closing = ("ALL SYSTEMS NORMAL", "SIMULATION COMPLETE - NOTHING COMMITTED")
        else:
            closing = ("ALL SYSTEMS NORMAL", "BOOT SEQUENCE COMPLETE")
        for text in closing:
            self._banner(text, FG_ALERT if degraded else FG_BRIGHT, animate=True)
        self._blank()
        self._emit(self.p("/" * self._cols, FG_DIM))
        self._blank()