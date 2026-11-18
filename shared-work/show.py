"""What the kit shows in the terminal.

Two ways, chosen once at the start:

- Plain: one line after another, exactly the lines the kit has always printed. Used whenever the
  output is not a terminal a person looks at (a pipe, a log, an AI app running the kit), with
  NO_COLOR set, in a terminal that does not say it has 256 colours, or with --plain.
- Show: the same facts, drawn. A header with Papex's name, the checks of this computer ticking
  off, and while a batch runs its units as a field of cells that fill as they finish (the same
  picture the batch page on papex.org draws), the count, the time left, and whether Papex has the
  count. Nothing is said in the show that the plain lines do not say.

Only the standard library is used. Colours are Papex's own (petrol, its teal on a dark ground,
the seal's terracotta for what needs a look), in 24-bit colour where the terminal says it has it
and in the nearest of the 256 otherwise. Without UTF-8 the cells are ASCII.
"""

import math
import os
import shutil
import sys
import threading
import time

LIST_TITLE = "Kobon a(11) check"
FIELD_MAX = 300          # more units than this are a bar, not a field
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPIN_ASCII = "|/-\\"


RICH_TERMS = ("xterm-kitty", "xterm-ghostty", "alacritty", "wezterm", "foot", "contour")


def wanted(argv, stream=None):
    """True when the show may be drawn: a person's terminal that has 256 colours or more, colour
    allowed, not asked to be plain. A terminal that does not say so gets the plain lines."""
    stream = stream or sys.stdout
    term = os.environ.get("TERM", "")
    if "--plain" in argv or os.environ.get("NO_COLOR") or term in ("", "dumb", "linux"):
        return False
    if not ("256color" in term or "direct" in term or term in RICH_TERMS
            or os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")):
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def field_columns(total, width):
    """About four cells wide for each one high, as on the batch page: 100 units are 20 by 5."""
    return max(1, min(total, 30, (max(width, 12) - 4) // 2, math.ceil(math.sqrt(total * 4))))


def clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 \
        else f"{seconds // 60:02d}:{seconds % 60:02d}"


def about(seconds):
    minutes = round(seconds / 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 90:
        return f"about {minutes} min"
    rest = minutes % 60
    return f"about {minutes // 60} h" + (f" {rest} min" if rest else "")


class Plain:
    """The kit's lines as they have always been. Every method prints at once or not at all."""

    fancy = False

    def __init__(self):
        self.lock = threading.Lock()

    def say(self, line=""):
        with self.lock:
            print(line, flush=True)

    def open(self, check):
        pass

    def leaves(self, with_key):
        if with_key:
            self.say("With the key, this run tells Papex how many units are done and sends the result "
                     "file at the end. Nothing else leaves this computer.")

    def step(self, label, work, detail=None):
        return work()

    def tools(self, cadical_version, checker_version, tests):
        self.say(f"CaDiCaL {cadical_version}: self-test {tests['cadical']}. "
                 f"lrat-check ({checker_version}): self-test {tests['lrat-check']}.")

    def ready(self):
        self.say("This computer is ready. Take units on the list's page on papex.org and run the "
                 "command your batch page shows.")

    def batch(self, key, total, keep, already):
        self.say(f"Batch {key}: {total} units, {keep} marked to keep their proofs, {already} already done.")

    def running(self, count, workers, expected_seconds):
        self.say(f"Running {count} units with {workers} worker{'s' if workers != 1 else ''}; "
                 f"about {max(1, round(expected_seconds / workers / 60))} min on a computer like the one of the "
                 "original run. Stop with Ctrl-C and run the same command again to continue.")

    def live(self, units, keep, done, workers, progress, with_key, expected_seconds):
        pass

    def unit_started(self, key):
        pass

    def unit_done(self, record, done, total):
        shown = {"UNSAT": "no solution, proof " + record.get("check", "").lower(),
                 "SAT": "A SOLUTION WAS FOUND", "UNKNOWN": "not finished"}[record["outcome"]]
        self.say(f"[{done}/{total}] {record['key']}: {shown}, {record.get('seconds', 0)} s")

    def note(self, line):
        self.say(line)

    def settle(self):
        pass

    def done(self, verified, total, result_path):
        self.say()
        self.say(f"Done: {verified} of {total} units have no solution, each with a checked proof.")
        self.say(f"Result file:  {result_path}")

    def sent(self, ok, why=None, closed=False, page=None):
        if ok:
            self.say("  Sent to Papex. Go back to your batch page, choose how you are shown, and press Send.")
            if page:
                self.say(f"  {page}")
            return
        self.say(f"  It was not sent ({why}).")
        self.say("  This batch no longer takes a result, on the batch page either." if closed
                 else "  Upload it on your batch page on papex.org, choose how you are shown, and send it.")

    def upload_by_hand(self):
        self.say("  Upload it on your batch page on papex.org, choose how you are shown, and send it.")

    def kept(self, archive, count, megabytes):
        self.say(f"Kept proofs:  {archive} ({count} proof{'s' if count != 1 else ''}, {megabytes:.1f} MB)")
        self.say("  Keep this file. If Papex Labs asks for the proofs, put it at a direct https link and\n"
                 "  give that link for each marked unit on the batch page.")

    def next_steps(self):
        pass

    def fail(self, message):
        """The kit's last word (why it stops). False here: Python prints it, as it always did."""
        return False

    def close(self):
        pass


class Show(Plain):
    """The same run, drawn. One thread paints; everything it reads is set under the lock."""

    fancy = True

    def __init__(self, stream=None):
        super().__init__()
        self.out = stream or sys.stdout
        encoding = (getattr(self.out, "encoding", "") or "").lower().replace("-", "")
        self.utf8 = encoding.startswith("utf")
        self.true_colour = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
        self.rows = []            # the checks: [label, state, detail]
        self.region = 0           # lines of the part that is painted again and again
        self.painter = None
        self.stop_painting = threading.Event()
        self.live_on = False
        self.cursor_hidden = False
        self.notes = []
        self.last = None
        self.started = None
        self.wave = None          # the finale's lit column, while it plays

    # ---------------------------------------------------------------- colour and characters

    def colour(self, name):
        """Papex's colours: teal (the action colour on a dark ground), petrol as a plate, the seal."""
        rgb, near = {"teal": ((36, 145, 136), 36), "seal": ((201, 88, 47), 166),
                     "plate": ((9, 58, 58), 23), "paper": ((244, 246, 246), 255)}[name]
        return ("2;%d;%d;%d" % rgb) if self.true_colour else ("5;%d" % near)

    def paint(self, text, fg=None, bg=None, bold=False, dim=False):
        codes = []
        if bold:
            codes.append("1")
        if dim:
            codes.append("2")
        if fg:
            codes.append("38;" + self.colour(fg))
        if bg:
            codes.append("48;" + self.colour(bg))
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if codes else text

    def glyph(self, name):
        return ({"done": "■", "todo": "·", "busy": "▪", "keep": "□", "keep_done": "▣", "ok": "✓", "no": "✗",
                 "dot": "●", "ring": "○", "rule": "─", "bar": "█", "rest": "░", "sep": "·",
                 "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯", "v": "│", "arrow": "→"} if self.utf8 else
                {"done": "#", "todo": ".", "busy": "*", "keep": "o", "keep_done": "@", "ok": "+", "no": "x",
                 "dot": "*", "ring": "o", "rule": "-", "bar": "#", "rest": ".", "sep": "-",
                 "tl": "+", "tr": "+", "bl": "+", "br": "+", "v": "|", "arrow": "->"})[name]

    def width(self):
        return max(40, min(shutil.get_terminal_size((80, 24)).columns, 100))

    def write(self, text):
        self.out.write(text)
        self.out.flush()

    def cursor(self, shown):
        if shown == self.cursor_hidden:
            self.write("\x1b[?25h" if shown else "\x1b[?25l")
            self.cursor_hidden = not shown

    # ---------------------------------------------------------------- the part painted in place

    def repaint(self, lines):
        """Draw `lines` over what was drawn the last time (the lock is held by the caller)."""
        text = f"\x1b[{self.region}F" if self.region else ""
        text += "".join("\x1b[2K" + line + "\n" for line in lines)
        text += "\x1b[J" if len(lines) < self.region else ""
        self.region = len(lines)
        self.write(text)

    def paint_loop(self, frame, rate):
        tick = 0
        while not self.stop_painting.wait(1.0 / rate):
            tick += 1
            with self.lock:
                self.repaint(frame(tick))

    def start_painting(self, frame, rate=10):
        self.stop_painting.clear()
        self.cursor(False)
        with self.lock:
            self.region = 0
            self.repaint(frame(0))
        self.painter = threading.Thread(target=self.paint_loop, args=(frame, rate), daemon=True)
        self.painter.start()

    def end_painting(self, frame):
        """Stop the painter and leave the last picture standing as ordinary lines."""
        if self.painter:
            self.stop_painting.set()
            self.painter.join(1.0)
            self.painter = None
        with self.lock:
            self.repaint(frame(-1))
            self.region = 0
        self.cursor(True)

    # ---------------------------------------------------------------- header and checks

    def open(self, check):
        """Papex's name on a petrol plate, then a row of cells that fills once and settles to a rule."""
        cells = min(self.width() - 4, 44)
        head = "  " + self.paint(" Papex ", fg="paper", bg="plate", bold=True) + "  " \
            + self.paint("Shared work", bold=True) + self.paint(f"  {self.glyph('sep')}  {LIST_TITLE}", dim=True)
        self.write("\n" + head + "\n")
        self.cursor(False)
        try:
            for filled in range(0, cells + 1, 2):
                self.write("\r\x1b[2K  " + self.paint(self.glyph("done") * filled, fg="teal")
                           + self.paint(self.glyph("todo") * (cells - filled), dim=True))
                time.sleep(0.012)
            time.sleep(0.12)
        finally:
            self.write("\r\x1b[2K  " + self.paint(self.glyph("rule") * cells, dim=True) + "\n\n")
            self.cursor(True)

    def leaves(self, with_key):
        line = ("With the key, this run tells Papex how many units are done and sends the result "
                "file at the end. Nothing else leaves this computer.") if with_key \
            else "With a batch file, this run sends nothing anywhere."
        for part in self.wrap(line, self.width() - 4):
            self.write("  " + self.paint(part, dim=True) + "\n")
        self.write("\n")

    def wrap(self, text, width):
        lines, line = [], ""
        for word in text.split():
            if line and len(line) + 1 + len(word) > width:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        return lines + ([line] if line else [])

    def row_lines(self, tick):
        spin = SPIN if self.utf8 else SPIN_ASCII
        lines = []
        for label, state, detail in self.rows:
            mark = {"run": self.paint(spin[tick % len(spin)], fg="teal"),
                    "ok": self.paint(self.glyph("ok"), fg="teal", bold=True),
                    "no": self.paint(self.glyph("no"), fg="seal", bold=True)}[state]
            lines.append(f"  {mark} {label:<12}" + (self.paint(detail, dim=state != "no") if detail else ""))
        return lines

    def step(self, label, work, detail=None):
        """Run one check of this computer with its row turning, then ticked with what it found."""
        row = [label, "run", ""]
        self.rows = [row]
        box = {}

        def run():
            try:
                box["value"] = work()
            except BaseException as error:  # SystemExit carries the kit's own message
                box["error"] = error

        worker = threading.Thread(target=run, daemon=True)
        self.start_painting(self.row_lines, rate=12)
        worker.start()
        try:
            while worker.is_alive():
                worker.join(0.05)
        finally:
            # Ticked only when the work came back with something; a stop or Ctrl-C leaves a cross.
            row[1] = "ok" if "value" in box else "no"
            if "value" in box and detail:
                row[2] = detail(box["value"])
            self.end_painting(self.row_lines)
        if "error" in box:
            raise box["error"]
        return box["value"]

    def tools(self, cadical_version, checker_version, tests):
        if "failed" in tests.values():
            self.rows = [["Self-test", "no", "  ".join(f"{name} {state}" for name, state in tests.items())]]
            with self.lock:
                self.write("\x1b[1F\x1b[2K" + self.row_lines(0)[0] + "\n")

    def ready(self):
        self.write("\n")
        self.plate(self.glyph("ok") + " This computer is ready.")
        self.write("  " + self.paint("Next", bold=True) + "  Take units on the list's page on papex.org,\n"
                   "        then run the command your batch page shows.\n\n")

    def plate(self, text):
        inner = f"  {text}  "
        self.write("  " + self.paint(inner, fg="paper", bg="plate", bold=True) + "\n\n")

    # ---------------------------------------------------------------- a batch running

    def batch(self, key, total, keep, already):
        parts = [f"{total} unit{'s' if total != 1 else ''}"]
        if keep:
            parts.append(f"{keep} keep their proof{'s' if keep != 1 else ''}")
        if already:
            parts.append(f"{already} already done")
        self.write("\n  " + self.paint(f"Batch {key}", bold=True) + "  "
                   + self.paint(f"  {self.glyph('sep')}  ".join(parts), dim=True) + "\n\n")

    def running(self, count, workers, expected_seconds):
        self.expected = expected_seconds / max(1, workers)

    def live(self, units, keep, done, workers, progress, with_key, expected_seconds):
        self.units, self.keep, self.finished = list(units), set(keep), set(done)
        self.busy, self.workers, self.progress, self.with_key = set(), workers, progress, with_key
        self.expected = expected_seconds / max(1, workers)
        self.started, self.done_at_start = time.monotonic(), len(self.finished)
        self.live_on = True
        self.start_painting(self.live_lines, rate=6)

    def unit_started(self, key):
        with self.lock:
            self.busy.add(key)

    def unit_done(self, record, done, total):
        with self.lock:
            self.busy.discard(record["key"])
            if record["outcome"] in ("UNSAT", "SAT"):
                self.finished.add(record["key"])
            self.last = record

    def note(self, line):
        with self.lock:
            if self.live_on:
                self.notes.append(line)
            else:
                for part in self.wrap(line, self.width() - 4):
                    self.write("  " + self.paint(part, fg="seal") + "\n")

    def cell(self, key, tick, lit=True):
        kept = key in self.keep
        if key in self.finished:
            return self.paint(self.glyph("keep_done" if kept else "done"), fg="teal", dim=not lit)
        if key in self.busy:
            # A unit being solved is a small cell that breathes between the faint and the full teal;
            # only a finished unit is a full cell, so the full cells are the count.
            return self.paint(self.glyph("busy"), fg="teal", dim=tick % 6 < 3)
        return self.paint(self.glyph("keep"), fg="teal") if kept else self.paint(self.glyph("todo"), dim=True)

    def live_lines(self, tick):
        total, done = len(self.units), len(self.finished)
        width = self.width()
        lines = []
        height = shutil.get_terminal_size((80, 24)).lines
        columns = field_columns(total, width)
        if total <= FIELD_MAX and math.ceil(total / columns) + 8 <= height:
            # `wave` is the finale: the cells light column by column, once, when every unit is done.
            for start in range(0, total, columns):
                lines.append("  " + " ".join(self.cell(key, tick, self.wave is None or at <= self.wave)
                                             for at, key in enumerate(self.units[start:start + columns])))
            legend = [self.paint(self.glyph("done"), fg="teal") + self.paint(" done", dim=True),
                      self.paint(self.glyph("todo") + " to do", dim=True)]
            if self.keep:
                legend.append(self.paint(self.glyph("keep"), fg="teal") + self.paint(" proof kept", dim=True))
            lines.append("  " + "   ".join(legend))
        else:
            span = max(10, min(width - 4, 50))
            filled = span * done // max(1, total)
            lines.append("  " + self.paint(self.glyph("bar") * filled, fg="teal")
                         + self.paint(self.glyph("rest") * (span - filled), dim=True))
        lines.append("")
        elapsed = time.monotonic() - self.started
        fresh = done - self.done_at_start
        if done >= total:
            left = "all units done"
        elif fresh >= 3:
            left = about(elapsed / fresh * (total - done)) + " left"
        else:
            left = about(self.expected) + " of computing"
        sep = self.paint(f"  {self.glyph('sep')}  ", dim=True)
        lines.append("  " + self.paint(f"{done}", bold=True) + f" of {total} units" + sep + clock(elapsed)
                     + sep + left + sep + self.paint(f"{self.workers} worker{'s' if self.workers != 1 else ''}", dim=True))
        lines.append("  " + self.papex_line())
        if self.last:
            record = self.last
            if record["outcome"] == "SAT":
                shown = self.paint("A SOLUTION WAS FOUND", fg="seal", bold=True)
            else:
                shown = self.paint({"UNSAT": "no solution, proof " + record.get("check", "").lower(),
                                    "UNKNOWN": "not finished"}[record["outcome"]], dim=True)
            lines.append("  " + self.paint(f"{record['key']}  ", dim=True) + shown
                         + self.paint(f"  {record.get('seconds', 0)} s", dim=True))
        else:
            lines.append("")
        for note in self.notes[-2:]:
            for part in self.wrap(note, width - 4):
                lines.append("  " + self.paint(part, fg="seal"))
        if tick >= 0:
            lines.append("  " + self.paint("Ctrl-C stops; the same command continues.", dim=True))
        return lines

    def papex_line(self):
        """Whether Papex has the count: the page on papex.org shows what this line says it has."""
        if not self.with_key:
            return self.paint(self.glyph("ring") + " Nothing leaves this computer in this run.", dim=True)
        progress = self.progress
        if progress is not None and progress.ok and progress.sent is not None:
            return self.paint(self.glyph("dot"), fg="teal") + f" Papex has {progress.sent}" \
                + self.paint("  your batch page shows it", dim=True)
        if progress is not None and progress.failed:
            return self.paint("! Papex could not be told how far the run is. The run goes on.", fg="seal")
        return self.paint(self.glyph("ring") + " Telling Papex…" if self.utf8 else "o Telling Papex...", dim=True)

    def settle(self):
        if not self.live_on:
            return
        self.live_on = False
        if self.painter:
            self.stop_painting.set()
            self.painter.join(1.0)
            self.painter = None
        total = len(self.units)
        if total and len(self.finished) >= total:
            # Every unit is done: the field lights once from left to right, then stays.
            for column in range(-1, field_columns(total, self.width()) + 1):
                self.wave = column
                with self.lock:
                    self.repaint(self.live_lines(-1))
                time.sleep(0.022)
        self.wave = None
        self.end_painting(self.live_lines)

    # ---------------------------------------------------------------- the end of a run

    def done(self, verified, total, result_path):
        self.settle()
        ok = verified == total
        mark = self.paint(self.glyph("ok"), fg="teal", bold=True) if ok else self.paint("!", fg="seal", bold=True)
        self.write(f"\n  {mark} " + self.paint(f"{verified} of {total} units", bold=True)
                   + " have no solution, each with a checked proof.\n")
        self.result_path = result_path
        self.after = ["Upload the result file on your batch page on papex.org,",
                      "choose how you are shown, and send it."]
        self.archive = None

    def sent(self, ok, why=None, closed=False, page=None):
        if ok:
            self.write("  " + self.paint(self.glyph("ok"), fg="teal", bold=True) + " The result is with Papex.\n")
            self.after = ["Go back to your batch page, choose how you are shown,", "and press Send."] \
                + ([page] if page else [])
        else:
            self.write("  " + self.paint(f"! The result was not sent ({why}).", fg="seal") + "\n")
            if closed:
                self.after = ["This batch no longer takes a result, on the batch page either."]

    def upload_by_hand(self):
        pass  # the box at the end says it

    def kept(self, archive, count, megabytes):
        self.archive = (archive, count, megabytes)

    def next_steps(self):
        """What the person does now, in a box, then where the files are."""
        self.write("\n")
        self.box("Next", self.after)
        self.write("  " + self.paint("Result file  ", dim=True) + f"{self.result_path}\n")
        if not self.archive:
            self.write("\n")
            return
        archive, count, megabytes = self.archive
        size = f"({count} proof{'s' if count != 1 else ''}, {megabytes:.1f} MB)"
        apart = 15 + len(archive) + 2 + len(size) >= self.width()   # no room beside the path: on its own line
        self.write("  " + self.paint("Kept proofs  ", dim=True) + f"{archive}"
                   + (self.paint("\n               " + size if apart else "  " + size, dim=True)) + "\n")
        note = ("Keep this file. If Papex Labs asks for the proofs, put it at a direct https link and give "
                "that link for each marked unit on the batch page.")
        for part in self.wrap(note, self.width() - 17):
            self.write("               " + self.paint(part, dim=True) + "\n")
        self.write("\n")

    def box(self, title, lines):
        inner = max(len(line) for line in lines + [title]) + 2
        teal = lambda text: self.paint(text, fg="teal")  # noqa: E731
        top = self.glyph("tl") + self.glyph("rule") + f" {title} " + self.glyph("rule") * (inner - len(title) - 3) + self.glyph("tr")
        self.write("  " + teal(top) + "\n")
        for line in lines:
            self.write("  " + teal(self.glyph("v")) + f" {line:<{inner - 1}}" + teal(self.glyph("v")) + "\n")
        self.write("  " + teal(self.glyph("bl") + self.glyph("rule") * inner + self.glyph("br")) + "\n\n")

    def fail(self, message):
        """The kit's last word (why it stops), wrapped to the terminal and in the show's hand."""
        self.close()
        calm = message.lstrip().startswith("Stopped")
        for line in message.split("\n"):
            lead = len(line) - len(line.lstrip())
            for part in self.wrap(line.strip(), self.width() - 4 - lead) if line.strip() else [""]:
                text = " " * lead + part
                self.write("  " + (text if calm or lead else self.paint(text, fg="seal")) + "\n")
        return True

    def close(self):
        """Whatever ended the run: stop painting, and give the terminal its cursor back."""
        if self.painter:
            self.stop_painting.set()
            self.painter.join(1.0)
            self.painter = None
        self.live_on = False
        self.cursor(True)


def make(argv):
    """Plain lines, the drawn run, or (with UTF-8 and room for it) the show at full size."""
    if not wanted(argv):
        return Plain()
    import stage
    return stage.Stage() if stage.fits() else Show()
