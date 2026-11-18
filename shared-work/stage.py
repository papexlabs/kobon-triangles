"""The kit's terminal show at full size.

`show.Show` draws a run plainly. This is the same run as a show, for a terminal with UTF-8 and room
(76 columns, 24 lines): Papex's name assembles out of sparks in large letters and a light passes
over it; each check of this computer is scanned and ticked; a batch runs inside a frame with the
count in large digits, the units as a field of cells whose colour moves like water and that flash
when they finish, a line the count travels along to Papex each time Papex is told, and the pace
as a small graph. When the last unit is done a ripple runs through the field and a light runs
once around the frame.

Nothing is said here that the plain lines do not say, and nothing is drawn that did not happen:
a mark travels to Papex only when a report was sent, and "Papex has N" only once Papex answered.
The colours are Papex's (petrol to its teals; the seal's terracotta for what needs a look), in
24-bit colour where the terminal has it and the nearest of the 256 otherwise, and they turn
darker on a light terminal. Only the standard library is used.
"""

import math
import os
import random
import re
import shutil
import sys
import threading
import time

from show import FIELD_MAX, LIST_TITLE, Show, about, clock, field_columns

# Block letters with a shadow, six rows high: the full blocks are the letter, the box lines its shadow.
LOGO = (
    "██████╗  █████╗ ██████╗ ███████╗██╗  ██╗",
    "██╔══██╗██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝",
    "██████╔╝███████║██████╔╝█████╗   ╚███╔╝ ",
    "██╔═══╝ ██╔══██║██╔═══╝ ██╔══╝   ██╔██╗ ",
    "██║     ██║  ██║██║     ███████╗██╔╝ ██╗",
    "╚═╝     ╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝",
)
DIGITS = {
    "0": (" ██████╗ ", "██╔═████╗", "██║██╔██║", "████╔╝██║", "╚██████╔╝", " ╚═════╝ "),
    "1": (" ██╗", "███║", "╚██║", " ██║", " ██║", " ╚═╝"),
    "2": ("██████╗ ", "╚════██╗", " █████╔╝", "██╔═══╝ ", "███████╗", "╚══════╝"),
    "3": ("██████╗ ", "╚════██╗", " █████╔╝", " ╚═══██╗", "██████╔╝", "╚═════╝ "),
    "4": ("██╗  ██╗", "██║  ██║", "███████║", "╚════██║", "     ██║", "     ╚═╝"),
    "5": ("███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"),
    "6": (" ██████╗ ", "██╔════╝ ", "███████╗ ", "██╔═══██╗", "╚██████╔╝", " ╚═════╝ "),
    "7": ("███████╗", "╚════██║", "    ██╔╝", "   ██╔╝ ", "   ██║  ", "   ╚═╝  "),
    "8": (" █████╗ ", "██╔══██╗", "╚█████╔╝", "██╔══██╗", "╚█████╔╝", " ╚════╝ "),
    "9": (" █████╗ ", "██╔══██╗", "╚██████║", " ╚═══██║", " █████╔╝", " ╚════╝ "),
}
COUNT_WIDE = 27   # three of the widest digits
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPARK = " ▁▂▃▄▅▆▇█"


def numerals(value):
    """A number in the large digits, as six rows of text."""
    return ["".join(DIGITS[d][row] for d in str(value)) for row in range(6)]


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def seen(text):
    """How many columns a painted text takes on the screen."""
    return len(ANSI.sub("", text))


def mix(a, b, t):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def light_background(stream):
    """True when the terminal says its background is light, False when dark, None when it does not say.

    Asked the usual way (OSC 11) and waited for a fifth of a second at most; a terminal that does not
    answer is taken as dark, which most are."""
    said = os.environ.get("PAPEX_KIT_BACKGROUND", "").lower()
    if said in ("light", "dark"):   # for a terminal that does not answer: say it yourself
        return said == "light"
    try:
        import select
        import termios
        import tty
        if not sys.stdin.isatty() or not stream.isatty():
            return None
        fd = sys.stdin.fileno()
        before = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            stream.write("\x1b]11;?\x07")
            stream.flush()
            answer, until = b"", time.monotonic() + 0.2
            while time.monotonic() < until:
                ready, _, _ = select.select([fd], [], [], max(0.0, until - time.monotonic()))
                if not ready:
                    break
                answer += os.read(fd, 64)
                if answer.endswith(b"\x07") or answer.endswith(b"\x1b\\"):
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, before)
        found = re.search(rb"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", answer)
        if not found:
            return None
        r, g, b = (int(part[:2], 16) for part in found.groups())
        return 0.299 * r + 0.587 * g + 0.114 * b > 140
    except Exception:  # never worth stopping a run for
        return None


def fits(stream=None):
    """Whether this terminal has the characters and the room for the show at full size."""
    stream = stream or sys.stdout
    encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
    size = shutil.get_terminal_size((80, 24))
    return encoding.startswith("utf") and size.columns >= 76 and size.lines >= 24


class Stage(Show):
    """The show at full size. Every method keeps the meaning of the plain one it stands for."""

    def __init__(self, stream=None):
        super().__init__(stream)
        ground = light_background(self.out)
        self.light = ground is True
        if ground is True:     # a light terminal: the same hues, darker, and the flash goes to petrol
            self.stops = [(9, 58, 58), (15, 107, 102), (36, 145, 136), (40, 160, 165)]
            self.flash, self.edge, self.seal = (4, 34, 34), (120, 160, 156), (166, 58, 18)
        elif ground is False:  # a dark terminal: up to the pale teal, and the flash is white
            self.stops = [(15, 107, 102), (36, 145, 136), (79, 182, 194), (170, 235, 225)]
            self.flash, self.edge, self.seal = (244, 252, 250), (24, 88, 84), (232, 130, 90)
        else:                  # a terminal that does not say: teals that read on dark and on light
            self.stops = [(15, 107, 102), (36, 145, 136), (60, 165, 170), (79, 182, 194)]
            self.flash, self.edge, self.seal = (140, 225, 215), (40, 110, 106), (201, 88, 47)
        self.paper, self.plate = (244, 246, 246), (9, 58, 58)
        self.done_at, self.finishes, self.packets = {}, [], []
        self.seen_report = None
        self.acked_at = -10.0
        self.marquee = self.ripple = None
        self.staged = False

    # ---------------------------------------------------------------- colour

    def code(self, rgb, ground=False):
        if self.true_colour:
            return ("48" if ground else "38") + ";2;%d;%d;%d" % rgb
        # The 256 colours' cube has the levels 0, 95, 135, 175, 215, 255 for each of red, green and blue.
        r, g, b = (0 if c < 48 else 1 if c < 115 else (c - 35) // 40 for c in rgb)
        return ("48" if ground else "38") + ";5;%d" % (16 + 36 * r + 6 * g + b)

    def ink(self, text, fg=None, bg=None, bold=False, dim=False):
        codes = (["1"] if bold else []) + (["2"] if dim else [])
        if fg:
            codes.append(self.code(fg))
        if bg:
            codes.append(self.code(bg, True))
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if codes else text

    def grad(self, t):
        """Papex's teals, from the deep one (0) to the pale one (1)."""
        t = 0.0 if t < 0 else 1.0 if t > 1 else t
        at = t * (len(self.stops) - 1)
        i = min(int(at), len(self.stops) - 2)
        return mix(self.stops[i], self.stops[i + 1], at - i)

    def shaded(self, rows, body, shadow=None):
        """Rows of block letters as text: body(x, y) colours a full block (None hides it), the box lines are the shadow."""
        lines = []
        for y, row in enumerate(rows):
            out = []
            for x, ch in enumerate(row):
                if ch == " ":
                    out.append(" ")
                    continue
                colour = body(x, y)
                if colour is None:
                    out.append(" ")
                elif ch == "█":
                    out.append(self.ink(ch, fg=colour))
                else:
                    out.append(self.ink(ch, fg=shadow(x, y) if shadow else mix(colour, self.edge, 0.72)))
            lines.append("".join(out))
        return lines

    def play(self, frame, seconds, rate=30):
        """Paint frame(t) for `seconds`, then leave its last picture standing as ordinary lines."""
        self.cursor(False)
        start = time.monotonic()
        try:
            with self.lock:
                self.region = 0
            while True:
                t = time.monotonic() - start
                with self.lock:
                    self.repaint(frame(min(t, seconds)))
                if t >= seconds:
                    break
                time.sleep(1.0 / rate)
        finally:
            with self.lock:
                self.region = 0
            self.cursor(True)

    # ---------------------------------------------------------------- the opening

    def open(self, check):
        """PAPEX assembles out of sparks, a light passes over it, and the line under it is typed."""
        width = self.width()
        high, wide = len(LOGO), len(LOGO[0])
        rnd = random.Random(11)
        born = [[x / wide * 0.5 + rnd.random() * 0.28 for x in range(wide)] for _ in range(high)]
        words = ("Shared work", f"  ·  {LIST_TITLE}")
        typed_all = len(words[0]) + len(words[1])
        rule = min(wide, width - 4)
        flicker = random.Random()

        def frame(t):
            sweep = (t - 0.95) / 0.6 * 1.5 - 0.25   # the light's place, across and a little down
            lines = [""]
            for y, row in enumerate(LOGO):
                out = ["  "]
                for x, ch in enumerate(row):
                    age = t - born[y][x]
                    if ch == " " or age < 0:
                        out.append(" ")
                        continue
                    base = self.grad(0.12 + 0.82 * x / wide)
                    if age < 0.3:   # a cell arrives as a spark, flickering through shades, and cools into place
                        out.append(self.ink("░▒▓"[flicker.randrange(3)], fg=mix(self.flash, base, age / 0.3)))
                        continue
                    glow = max(0.0, 1 - abs((x / wide + 0.05 * y) - sweep) / 0.09)
                    lit = mix(base, self.flash, glow * 0.9)
                    out.append(self.ink(ch, fg=lit if ch == "█" else mix(lit, self.edge, 0.72)))
                lines.append("".join(out))
            lines.append("")
            typed = max(0, min(typed_all, int((t - 0.9) * 70)))
            first, second = words[0][:typed], words[1][:max(0, typed - len(words[0]))]
            caret = self.ink("▌", fg=self.grad(0.9)) if 0 < typed < typed_all else ""
            lines.append("  " + self.ink(first, bold=True) + self.ink(second, dim=True) + caret)
            drawn = max(0, min(rule, int((t - 1.15) / 0.45 * rule)))
            lines.append("  " + "".join(
                self.ink("◢◣"[i % 2], fg=mix(self.grad(0.1 + 0.6 * i / rule), self.flash,
                                             max(0.0, 1 - abs(i - drawn) / 3) if drawn < rule else 0.0))
                for i in range(drawn)))
            lines.append("")
            return lines

        self.play(frame, 1.75)

    # ---------------------------------------------------------------- the checks

    def scanner(self, t, cells=14):
        """A light that runs back and forth along a short track while a check is at work."""
        at = (t * 1.4) % 2
        head = (at if at < 1 else 2 - at) * (cells - 1)
        return "".join(self.ink("━", fg=mix(self.edge, self.flash, max(0.0, 1 - abs(i - head) / 3.2))) for i in range(cells))

    def step(self, label, work, detail=None):
        """One check of this computer: scanned while it runs, then ticked with what it found and how long it took."""
        box, started = {}, time.monotonic()

        def run():
            try:
                box["value"] = work()
            except BaseException as error:  # SystemExit carries the kit's own message
                box["error"] = error
            box["took"] = time.monotonic() - started

        def frame(tick):
            if "took" in box and tick < 0:
                if box.get("stopped"):
                    return ["  " + self.ink("·", dim=True) + f" {label:<11}" + self.ink("stopped", dim=True)]
                if "value" not in box:
                    return ["  " + self.ink("✗", fg=self.seal, bold=True) + f" {label}"]
                took = f"{box['took']:.1f} s" if box["took"] >= 0.1 else ""
                found = detail(box["value"]) if detail else ""
                room = self.width() - 4 - 2 - 11 - len(took) - 2
                return ["  " + self.ink("✓", fg=self.grad(0.75), bold=True) + f" {label:<11}"
                        + self.ink((found if len(found) <= room else found[:room - 1] + "…").ljust(room), dim=True)
                        + "  " + self.ink(took, dim=True)]
            return ["  " + self.ink(SPIN[int((time.monotonic() - started) * 14) % len(SPIN)], fg=self.grad(0.8))
                    + f" {label:<11}" + self.scanner(time.monotonic() - started)]

        worker = threading.Thread(target=run, daemon=True)
        self.start_painting(frame, rate=24)
        worker.start()
        try:
            # Even a check that takes no time is on the stage long enough to be seen.
            while worker.is_alive() or time.monotonic() - started < 0.45:
                worker.join(0.03)
                if not worker.is_alive():
                    time.sleep(0.03)
        except KeyboardInterrupt:
            box["stopped"] = True
            raise
        finally:
            box.setdefault("took", time.monotonic() - started)
            self.end_painting(frame)
        if "error" in box:
            raise box["error"]
        return box["value"]

    def tools(self, cadical_version, checker_version, tests):
        if "failed" in tests.values():
            self.write("  " + self.ink("✗ " + ", ".join(f"{name} {state}" for name, state in tests.items()),
                                       fg=self.seal, bold=True) + "\n")

    def banner(self, text, seconds=0.8):
        """A petrol plate with one line on it, and a light that passes over it once."""
        span = min(self.width() - 4, max(56, len(text) + 8))
        pad = (span - len(text)) // 2

        def frame(t):
            sweep = t / (seconds - 0.1) * 1.4 - 0.2

            def cell(i, ch):
                ground = mix(mix(self.plate, self.stops[1] if not self.light else self.stops[2], i / span * 0.9),
                             (190, 235, 228), max(0.0, 1 - abs(i / span - sweep) / 0.1) * 0.55)
                return self.ink(ch, fg=self.paper, bg=ground, bold=True)

            middle = " " * pad + text + " " * (span - pad - len(text))
            blank = " " * span
            return [""] + ["  " + "".join(cell(i, ch) for i, ch in enumerate(row)) for row in (blank, middle, blank)] + [""]

        self.play(frame, seconds)

    def ready(self):
        self.banner("✓  THIS COMPUTER IS READY")
        self.write("  " + self.ink("Next", bold=True) + "  Take units on the list's page on papex.org,\n"
                   "        then run the command your batch page shows.\n\n")

    # ---------------------------------------------------------------- a batch running

    def batch(self, key, total, keep, already):
        self.batch_key, self.keep_count, self.already = key, keep, already
        if already >= total:   # nothing left to run: there is no frame to carry this line
            super().batch(key, total, keep, already)

    def live(self, units, keep, done, workers, progress, with_key, expected_seconds):
        self.units, self.keep, self.finished = list(units), set(keep), set(done)
        self.busy, self.workers, self.progress, self.with_key = set(), workers, progress, with_key
        self.expected = expected_seconds / max(1, workers)
        self.started, self.done_at_start = time.monotonic(), len(self.finished)
        self.place = {key: n for n, key in enumerate(self.units)}
        self.live_on = True
        self.write("\n")
        self.start_painting(self.frame_lines, rate=15)

    def unit_done(self, record, done, total):
        with self.lock:
            self.busy.discard(record["key"])
            if record["outcome"] in ("UNSAT", "SAT"):
                self.finished.add(record["key"])
                self.done_at[record["key"]] = time.monotonic()
                self.finishes.append(time.monotonic())
            self.last = record

    def dash_cell(self, key, t, columns):
        n = self.place[key]
        x, y = n % columns, n // columns
        kept = key in self.keep
        if key in self.finished:
            # The colour moves through the finished cells like light on water.
            base = self.grad(0.42 + 0.3 * math.sin(x * 0.42 + y * 0.8 - t * 1.7))
            age = t - self.done_at.get(key, -10)
            if age < 0.55:   # a unit that just finished flashes and cools
                base = mix(self.flash, base, age / 0.55)
            if self.ripple is not None:   # the finale: a ring of light widening from the last unit
                ox, oy, radius = self.ripple
                ring = max(0.0, 1 - abs(math.hypot(x - ox, (y - oy) * 2.0) - radius) / 1.6)
                base = mix(base, self.flash, ring)
            return self.ink("▣" if kept else "■", fg=base)
        if key in self.busy:
            return self.ink(SPIN[(int(t * 12) + n) % len(SPIN)], fg=self.grad(0.95))
        return self.ink("□", fg=self.grad(0.6)) if kept else self.ink("·", dim=True)

    def big_count(self, value, t):
        """The count in the large digits, right-aligned; it glows when it has just grown."""
        rows = [row.rjust(COUNT_WIDE) for row in numerals(value)]
        glow = max(0.0, 1 - (t - (self.finishes[-1] if self.finishes else -10)) / 0.45)
        return self.shaded(rows, lambda x, y: mix(self.grad(0.95 - 0.45 * y / 6), self.flash, glow * 0.85))

    def link_line(self, t, track):
        """This computer, a line, Papex. A mark travels the line each time the count is sent."""
        if not self.with_key:
            return self.ink("○ Nothing leaves this computer in this run.", dim=True)
        progress = self.progress
        if progress is not None and progress.at != self.seen_report:
            self.seen_report = progress.at
            self.packets.append(t)
        self.packets = [start for start in self.packets if t - start < 0.7]
        heads = [(t - start) / 0.7 * track for start in self.packets]
        line = []
        for i in range(track):
            near = min((abs(i - head) for head in heads), default=99)
            behind = min((head - i for head in heads if head >= i), default=99)
            if near < 0.6:
                line.append(self.ink("◆", fg=self.flash, bold=True))
            elif behind < 4:
                line.append(self.ink("━", fg=mix(self.flash, self.edge, behind / 4)))
            else:
                line.append(self.ink("─", fg=self.edge))
        acked = progress is not None and progress.ok and progress.sent is not None
        if acked and progress.sent != getattr(self, "acked_count", None):
            self.acked_count, self.acked_at = progress.sent, t
        name = self.ink("Papex", fg=mix(self.flash, self.grad(0.8), min(1.0, (t - self.acked_at) / 0.5)), bold=True)
        if acked:
            said = f"has {progress.sent}" + self.ink("  ·  your batch page shows it", dim=True)
        elif progress is not None and progress.failed:
            said = self.ink("could not be told; the run goes on", fg=self.seal)
        else:
            said = self.ink("being told…", dim=True)
        return (self.ink("this computer ", dim=True) + self.ink("●", fg=self.grad(0.7)) + "".join(line)
                + self.ink("▶ ", fg=self.grad(0.7)) + name + "  " + said)

    def frame_width(self):
        """The frame's width: a column of margin on each side, so no line reaches the terminal's last column."""
        return max(40, min(shutil.get_terminal_size((80, 24)).columns - 2, 100))

    def frame_lines(self, tick):
        """The run inside its frame. `tick` below zero asks for the picture that stays."""
        t = time.monotonic()
        total, done = len(self.units), len(self.finished)
        width = self.frame_width()
        inner = width - 4
        columns = field_columns(total, min(inner - COUNT_WIDE - 4, 62))
        field_rows = math.ceil(total / columns)
        height = shutil.get_terminal_size((80, 24)).lines
        self.staged = False
        if total > FIELD_MAX or field_rows + 12 > height:
            return super().live_lines(tick)   # no room for the stage: the plain picture
        elapsed = t - self.started
        fresh = done - self.done_at_start
        left = "all units done" if done >= total else about(elapsed / fresh * (total - done)) + " left" if fresh >= 3 \
            else about(self.expected) + " of computing"
        body = []

        # The count in large digits, the field beside it, and the pace at the right when there is room.
        digits = self.big_count(done, t) if total < 1000 else [self.ink(f"{done:>{COUNT_WIDE}}", bold=True)]
        left_block = digits + [self.ink(f"{'of ' + str(total) + ' units':>{COUNT_WIDE}}", dim=True)]
        cells = [" ".join(self.dash_cell(key, t, columns) for key in self.units[start:start + columns])
                 for start in range(0, total, columns)]
        legend = self.ink("■", fg=self.grad(0.5)) + self.ink(" done   · to do", dim=True)
        if self.keep:
            legend += "   " + self.ink("□", fg=self.grad(0.6)) + self.ink(" proof kept", dim=True)
        cells += ["", legend]
        field_wide = max(seen(row) for row in cells)
        stats = []
        if inner >= COUNT_WIDE + 3 + field_wide + 4 + 22:
            recent = [sum(1 for at in self.finishes if t - 5 * (n + 1) < at <= t - 5 * n) for n in range(15, -1, -1)]
            top = max(recent) or 1
            per_minute = fresh / elapsed * 60 if fresh >= 3 and elapsed > 0 else None
            stats = [self.ink(clock(elapsed), bold=True) + self.ink("  elapsed", dim=True),
                     left,
                     self.ink(f"{per_minute:.0f} units a minute" if per_minute else "", dim=True),
                     "",
                     "".join(self.ink(SPARK[min(8, math.ceil(n / top * 8))], fg=self.grad(0.35 + 0.5 * n / top)) for n in recent),
                     self.ink("pace, last 80 s", dim=True),
                     self.ink(f"{self.workers} worker{'s' if self.workers != 1 else ''}", dim=True)]
        for n in range(max(len(left_block), len(cells), len(stats))):
            a = left_block[n] if n < len(left_block) else ""
            b = cells[n] if n < len(cells) else ""
            line = a + " " * (COUNT_WIDE - seen(a)) + "   " + b + " " * (field_wide - seen(b))
            if n < len(stats):
                line += "    " + stats[n]
            body.append(line)
        if not stats:
            body.append("")
            body.append(self.ink(f"{clock(elapsed)}  ·  {left}  ·  {self.workers} worker{'s' if self.workers != 1 else ''}", dim=True))
        body.append("")

        # A bar the whole width: its filled part carries the gradient and a light that keeps moving.
        filled = inner * done / max(1, total)
        glint = (t * 0.45) % 1.4 - 0.2
        bar = []
        for i in range(inner):
            if i < int(filled):
                bar.append(self.ink("━", fg=mix(self.grad(0.2 + 0.7 * i / inner), self.flash,
                                               max(0.0, 1 - abs(i / inner - glint * filled / inner) / 0.05) * 0.7), bold=True))
            elif i == int(filled) and done < total:
                bar.append(self.ink("╸", fg=self.flash, bold=True))
            else:
                bar.append(self.ink("─", fg=self.edge))
        body.append("".join(bar))
        body.append("")
        body.append(self.link_line(t, max(8, min(26, inner - 62))))
        if self.last:
            record = self.last
            shown = {"UNSAT": "no solution, proof " + record.get("check", "").lower(), "SAT": "A SOLUTION WAS FOUND",
                     "UNKNOWN": "not finished"}[record["outcome"]]
            text = f"{record['key']}  {shown}  {record.get('seconds', 0)} s"
            body.append(self.ink(text, fg=self.seal, bold=True) if record["outcome"] == "SAT" else self.ink(text, dim=True))
        else:
            body.append("")
        for note in self.notes[-2:]:
            body.extend(self.ink(part, fg=self.seal) for part in self.wrap(note, inner))

        # The frame: the batch's name in its top edge; in the finale a light runs once around it.
        rows = len(body)
        around = 2 * width + 2 * rows

        def edge(index, ch):
            if self.marquee is None:
                return self.ink(ch, fg=self.edge)
            behind = (self.marquee - index) % around
            return self.ink(ch, fg=mix(self.flash, self.edge, behind / 14) if behind < 14 else self.edge)

        title = f" Batch {self.batch_key} "
        facts = f" {total} units" + (f"  ·  {self.keep_count} keep their proof{'s' if self.keep_count != 1 else ''}" if self.keep_count else "") + " "
        fill = width - 2 - 1 - len(title) - len(facts) - 1
        top = (edge(0, "╭") + edge(1, "─") + self.ink(title, bold=True)
               + "".join(edge(2 + len(title) + i, "─") for i in range(fill)) + self.ink(facts, dim=True)
               + edge(width - 2, "─") + edge(width - 1, "╮"))
        hint = " Ctrl-C stops; the same command continues " if tick >= 0 else ""
        low_fill = width - 2 - len(hint) - 1
        low = (edge(2 * width + rows - 1, "╰")
               + "".join(edge(2 * width + rows - 2 - i, "─") for i in range(low_fill))
               + self.ink(hint, dim=True) + edge(width + rows, "─") + edge(width + rows - 1, "╯"))
        lines = [" " + top]
        for n, text in enumerate(body):
            lines.append(" " + edge(around - 1 - n, "│") + " " + text + " " * max(0, inner - seen(text)) + " " + edge(width + n, "│"))
        lines.append(" " + low)
        if len(lines) >= height:              # notes made it taller than the screen
            return super().live_lines(tick)
        self.staged = True
        return lines

    def settle(self):
        """The run is over: the picture that stays. When every unit is done it ends with a ripple and a light."""
        if not self.live_on:
            return
        self.live_on = False
        if self.painter:
            self.stop_painting.set()
            self.painter.join(1.0)
            self.painter = None
        total = len(self.units)
        columns = field_columns(total, min(self.frame_width() - 4 - COUNT_WIDE - 4, 62)) if total else 1
        if self.staged and total and len(self.finished) >= total and self.region:
            last = self.place.get(self.last["key"], total // 2) if self.last else total // 2
            reach = math.hypot(columns, math.ceil(total / columns) * 2.0) + 2
            start = time.monotonic()
            while time.monotonic() - start < 0.75:   # a ring of light widens from the last unit
                self.ripple = (last % columns, last // columns, (time.monotonic() - start) / 0.75 * reach)
                with self.lock:
                    self.repaint(self.frame_lines(-1))
                time.sleep(1 / 30)
            self.ripple = None
            around = 2 * self.frame_width() + 2 * (self.region - 2)
            start = time.monotonic()
            while time.monotonic() - start < 0.8:    # and a light runs once around the frame
                self.marquee = int((time.monotonic() - start) / 0.8 * (around + 14))
                with self.lock:
                    self.repaint(self.frame_lines(-1))
                time.sleep(1 / 30)
            self.marquee = None
        self.end_painting(self.frame_lines)

    # ---------------------------------------------------------------- the end of a run

    def flight(self, label, seconds=0.55, track=22):
        """A mark flies from this computer to Papex: something was just sent."""
        def frame(t):
            head = t / seconds * track
            line = "".join(self.ink("◆", fg=self.flash, bold=True) if abs(i - head) < 0.6
                           else self.ink("━", fg=mix(self.flash, self.edge, (head - i) / 5)) if 0 <= head - i < 5
                           else self.ink("─", fg=self.edge) for i in range(track))
            return ["  " + self.ink(SPIN[int(t * 14) % len(SPIN)], fg=self.grad(0.8)) + f" {label:<11}"
                    + self.ink("this computer ", dim=True) + self.ink("●", fg=self.grad(0.7)) + line
                    + self.ink("▶ ", fg=self.grad(0.7)) + self.ink("Papex", bold=True)]
        self.play(frame, seconds)
        with self.lock:
            self.write("\x1b[1F\x1b[2K")   # the flight's line is replaced by what it led to

    def done(self, verified, total, result_path):
        self.settle()
        told = f"✓  {verified} OF {total} UNITS HAVE NO SOLUTION, EACH WITH A CHECKED PROOF"
        if verified == total and len(told) + 4 <= self.width() - 4:
            self.banner(told, 0.9)
        else:
            mark = self.ink("✓", fg=self.grad(0.75), bold=True) if verified == total else self.ink("!", fg=self.seal, bold=True)
            self.write(f"\n  {mark} " + self.ink(f"{verified} of {total} units", bold=True)
                       + " have no solution, each with a checked proof.\n")
        self.result_path = result_path
        self.after = ["Upload the result file on your batch page on papex.org,",
                      "choose how you are shown, and send it."]
        self.archive = None

    def sent(self, ok, why=None, closed=False, page=None):
        if ok:
            self.flight("Result")
            self.write("  " + self.ink("✓", fg=self.grad(0.75), bold=True) + f" {'Result':<11}" + self.ink("with Papex", dim=True) + "\n")
            self.after = ["Go back to your batch page, choose how you are shown,", "and press Send."] + ([page] if page else [])
        else:
            self.write("  " + self.ink(f"✗ The result was not sent ({why}).", fg=self.seal) + "\n")
            if closed:
                self.after = ["This batch no longer takes a result, on the batch page either."]

    def box(self, title, lines):
        """What to do next, in a frame whose edge carries the gradient."""
        inner = max(len(line) for line in lines + [title]) + 2
        edge = lambda text, at: self.ink(text, fg=self.grad(0.25 + 0.6 * at))  # noqa: E731
        top = "╭─ " + title + " " + "─" * (inner - len(title) - 3) + "╮"
        self.write("  " + "".join(self.ink(ch, bold=True) if 3 <= i < 3 + len(title) else edge(ch, i / len(top))
                                  for i, ch in enumerate(top)) + "\n")
        for line in lines:
            link = line.startswith("http") or line.startswith("/")
            self.write("  " + edge("│", 0) + " " + (self.ink(line, fg=self.grad(0.85), bold=True) if link else line)
                       + " " * (inner - 1 - len(line)) + edge("│", 1) + "\n")
        low = "╰" + "─" * inner + "╯"
        self.write("  " + "".join(edge(ch, i / len(low)) for i, ch in enumerate(low)) + "\n\n")
