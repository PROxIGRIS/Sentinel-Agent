"""
SENTINEL — Tactical Containment HUD  v13.0  [MONOLITH]
=======================================================
Architecture:
  Single Canvas, Tag-Based State Machine.
  Three phases managed entirely via canvas tags and itemconfig.
  No widget hierarchy. No window-level movement. No recreation loops.

  Phase 1  (T-60 → T-17) : Dual corner surveillance feeds.
                            Independent async tear/aberration loops.
                            Telemetry accelerates at threat level 2 (T-30).
  Phase 2  (T-17 → T-15) : Catastrophic transmission failure.
                            Frame drops + horizontal tearing via canvas.move().
                            Offset drift resolved by _snap_to_origin() flush.
  Phase 3  (T-15 → T-00) : Monolith materializes.
                            ALL items pre-allocated at step 0.
                            Decryption loop uses itemconfig only — never recreates.
                            lbl_center_timer is always a valid canvas ID.

Design language: Cyberpunk Enterprise. Muted graphite void, amber tactical
accents, cyan telemetry. Octagonal geometry throughout. No gamer RGB.
"""

from __future__ import annotations

import queue
import random
import socket
import threading
import tkinter as tk
from datetime import datetime

# ── Psychological Arsenal ──────────────────────────────────────────────────────
MSGS = [
    "Hope you appreciate the cinematic lighting for your execution.",
    "Dimming the lights so you can really focus on your mistakes.",
    "Caught. That's the whole message.",
    "The admin already got a notification. Rough.",
    "We have the receipts.",
    "Not even a little sneaky.",
    "Screenshot secured. Evidence uploaded. RIP.",
    "Your keyboard history tells a story. Not a good one.",
    "In retrospect, probably not worth it.",
    "The IT guy just said 'not again'.",
    "This machine belongs to the school. It told on you.",
    "The freeze will end. The log will not.",
    "Every session is monitored. Today was the proof.",
    "Someone's getting called to the office.",
    "Evidence timestamped, uploaded, and vibing in the cloud.",
    "Certified school policy speedrun. Any%.",
    "The principal sends their regards.",
    "Bold. Wrong. But bold.",
    "You were warned. The login screen says so.",
    "Lesson learned? Hopefully.",
]

UPLOAD_STAGES = [
    "INITIATING FORENSIC CAPTURE...",
    "COMPRESSING MEMORY SNAPSHOT...",
    "ENCRYPTING PAYLOAD  [AES-256]...",
    "UPLOADING TO SENTINEL NODE...",
    "VERIFYING CHECKSUM...",
    "EVIDENCE SECURED.  AWAITING REVIEW.",
]

# Five-column comms log — left card body content
LOG_ENTRIES = [
    ("KEYLOG_CAPTURE",       "COMPLETE",  "OK"),
    ("SCREEN_SNAPSHOT",      "COMPLETE",  "OK"),
    ("BROWSER_HISTORY_DUMP", "COMPLETE",  "OK"),
    ("PROCESS_LIST",         "COMPLETE",  "OK"),
    ("CLIPBOARD_EXTRACT",    "COMPLETE",  "OK"),
    ("NETWORK_TRACE",        "COMPLETE",  "OK"),
    ("USER_IDENTITY_LOCK",   "ACTIVE",    "OK"),
    ("TIMESTAMP_SEAL",       "ACTIVE",    "OK"),
]

# ── Tactical Threat Palette ────────────────────────────────────────────────────
COLOR_TRANS_KEY  = "#000001"    # Window transparency key
COLOR_VOID       = "#070810"    # Deepest background
COLOR_PANEL      = "#0b0d18"    # Card fill
COLOR_PANEL_HDR  = "#11141f"    # Card header zone (slightly lighter)

COLOR_AMBER      = "#ffaa00"    # Primary tactical accent — Threat Level 1
COLOR_AMBER_DIM  = "#5c3d00"    # Dim amber for inactive geometry
COLOR_ORANGE     = "#ff5200"    # Threat escalation — Level 2 (T-30)

COLOR_RED        = "#ff0038"    # Critical — Judgment header
COLOR_RED_DIM    = "#55001a"    # Dim red for structural decoration

COLOR_CYAN       = "#00c8f0"    # Telemetry / Comms accent
COLOR_CYAN_DIM   = "#003848"    # Dim cyan for structural decoration

COLOR_TEXT_BRT   = "#d8e8f4"    # Primary readable text
COLOR_TEXT_MID   = "#6a8090"    # Secondary / labels
COLOR_TEXT_DIM   = "#2e404e"    # Decorative / inactive

# ── Typography ─────────────────────────────────────────────────────────────────
F_NANO   = ("Consolas",  8)
F_MICRO  = ("Consolas",  9)
F_BODY   = ("Consolas", 10)
F_LABEL  = ("Consolas", 11, "bold")
F_TITLE  = ("Consolas", 13, "bold")
F_HUGE   = ("Consolas", 50, "bold")
F_QUOTE  = ("Consolas",  9, "italic")
F_GLITCH = ("Consolas", 11, "bold")

# Decryption noise characters — no emoji, pure ASCII/block art
_NOISE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*█▓▒░■□▪▫◆◇"


# ══════════════════════════════════════════════════════════════════════════════
#  FreezeHUD — Async Canvas Architecture
# ══════════════════════════════════════════════════════════════════════════════
class FreezeHUD:
    PAD = 36

    def __init__(
        self,
        trigger:     str        = "POLICY_VIOLATION",
        duration:    int        = 60,
        workstation: str | None = None,
        cinematic:   bool       = True,
    ):
        self.trigger      = trigger.upper()[:28].replace(" ", "_")
        self.duration     = max(1, duration)
        self.workstation  = (workstation or _hostname()).upper()[:16]
        self.remaining    = self.duration
        self.cinematic    = cinematic
        self.running      = True

        self.msg_idx      = 0
        self.anim_tick    = 0
        self.phase        = "containment"   # containment → transition → judgment
        self.threat_level = 1               # 1 = amber, 2 = orange (T-30)

        self.final_quote  = random.choice(MSGS)
        self.glitch_targets: list[dict] = []

        # Accumulated positional offsets for tear-heal tracking
        self._left_offset  = 0
        self._right_offset = 0

        self._root:   tk.Tk       | None = None
        self._bg_win: tk.Toplevel | None = None
        self._q: queue.Queue[str] = queue.Queue()

    # ── Public API ─────────────────────────────────────────────────────────────
    def show(self) -> None:
        threading.Thread(target=self._build, daemon=True, name="FreezeHUD").start()

    def dismiss(self) -> None:
        self.running = False
        self._q.put("destroy")

    # ── Bootstrap ──────────────────────────────────────────────────────────────
    def _build(self) -> None:
        root      = tk.Tk()
        self._root = root
        self.sw   = root.winfo_screenwidth()
        self.sh   = root.winfo_screenheight()

        # Cinematic dim overlay (separate Toplevel so transparency key works)
        if self.cinematic:
            bg = tk.Toplevel(root)
            self._bg_win = bg
            bg.overrideredirect(True)
            bg.attributes("-topmost", True)
            bg.attributes("-alpha", 0.70)
            bg.configure(bg="#000000")
            bg.geometry(f"{self.sw}x{self.sh}+0+0")

        # Main transparent canvas window
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", COLOR_TRANS_KEY)
        root.configure(bg=COLOR_TRANS_KEY)
        root.geometry(f"{self.sw}x{self.sh}+0+0")

        self.cvs = tk.Canvas(
            root, width=self.sw, height=self.sh,
            bg=COLOR_TRANS_KEY, highlightthickness=0,
        )
        self.cvs.pack(fill="both", expand=True)

        # Layer 0: persistent chrome (never deleted during phase transitions)
        self._draw_global_chrome()

        # Layer 1: phase 1 surveillance feeds
        self._draw_phase1()

        if self.cinematic and self._bg_win:
            self._bg_win.lift()
        root.lift()

        # Start all independent async loops
        self._poll_queue()
        self._tick()
        self._global_anim_loop()
        self._left_feed_loop()
        self._right_feed_loop()
        self._aberration_loop()
        self._rotate_msg()
        self._stay_on_top()

        root.mainloop()

    def _poll_queue(self) -> None:
        try:
            while True:
                cmd = self._q.get_nowait()
                if cmd == "destroy" and self._root:
                    self._root.destroy()
                    return
        except queue.Empty:
            pass
        if self._root:
            self._root.after(100, self._poll_queue)

    # ══════════════════════════════════════════════════════════════════════════
    #  Canvas Primitive Library
    # ══════════════════════════════════════════════════════════════════════════
    def _octa(self, x, y, w, h, chamfer: int = 20, **kw):
        """Create an octagonal polygon (chamfered rectangle)."""
        c = chamfer
        pts = [
            x + c,     y,
            x + w - c, y,
            x + w,     y + c,
            x + w,     y + h - c,
            x + w - c, y + h,
            x + c,     y + h,
            x,         y + h - c,
            x,         y + c,
        ]
        return self.cvs.create_polygon(pts, **kw)

    def _bracket(self, x, y, arm: int, color: str, tags, flip_x=False, flip_y=False):
        """L-shaped corner bracket accent."""
        sx = -arm if flip_x else arm
        sy = -arm if flip_y else arm
        self.cvs.create_line(x, y, x + sx, y,         fill=color, width=1, tags=tags)
        self.cvs.create_line(x, y, x,      y + sy,     fill=color, width=1, tags=tags)

    def _hline(self, x1, y, x2, color, tags, **kw):
        return self.cvs.create_line(x1, y, x2, y, fill=color, tags=tags, **kw)

    def _glitch_text(self, x, y, tags, **kw) -> dict:
        """
        Create a chromatic-aberration text triple.
        Returns a target dict suitable for _aberration_loop.
        The red layer sits right, cyan layer sits left — standard CA direction.
        """
        base_color = kw.pop("fill", COLOR_TEXT_BRT)
        # Draw order: red (back) → cyan (mid) → base (front)
        t_r = self.cvs.create_text(x, y, fill=COLOR_RED,  tags=tags, **kw)
        t_c = self.cvs.create_text(x, y, fill=COLOR_CYAN, tags=tags, **kw)
        t_b = self.cvs.create_text(x, y, fill=base_color, tags=tags, **kw)
        self.cvs.itemconfig(t_r, state="hidden")
        self.cvs.itemconfig(t_c, state="hidden")
        target = {
            "base": t_b, "cyan": t_c, "red": t_r,
            "x": x, "y": y, "glitching": False,
        }
        self.glitch_targets.append(target)
        return target

    # ══════════════════════════════════════════════════════════════════════════
    #  Layer 0: Global Chrome (Persistent Across All Phases)
    # ══════════════════════════════════════════════════════════════════════════
    def _draw_global_chrome(self) -> None:
        """
        Screen-edge corner brackets + status bar.
        Tag: "chrome". Never deleted.
        """
        pad = self.PAD - 8
        arm = 20

        # Four corner brackets
        self._bracket(pad, pad, arm, COLOR_TEXT_DIM, ("chrome",))
        self._bracket(self.sw - pad, pad, arm, COLOR_TEXT_DIM, ("chrome",), flip_x=True)
        self._bracket(pad, self.sh - pad, arm, COLOR_TEXT_DIM, ("chrome",), flip_y=True)
        self._bracket(self.sw - pad, self.sh - pad, arm, COLOR_TEXT_DIM, ("chrome",),
                      flip_x=True, flip_y=True)

        # Status bar — centre-top
        ts = datetime.now().strftime("%Y.%m.%d  %H:%M:%S")
        self.lbl_chrome_status = self.cvs.create_text(
            self.sw // 2, pad + 8,
            text=(
                f"SENTINEL CONTAINMENT SYSTEM  ·  NODE: {self.workstation}"
                f"  ·  SESSION: {ts}"
            ),
            font=F_NANO, fill=COLOR_TEXT_DIM, tags=("chrome",),
        )

        # Global scanline (single moving line — no particle rain)
        self.scanline = self.cvs.create_line(
            0, 0, self.sw, 0,
            fill=COLOR_TEXT_DIM, stipple="gray25", tags=("chrome",),
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  Layer 1: Phase 1 — Surveillance Feeds  (T-60 → T-17)
    # ══════════════════════════════════════════════════════════════════════════
    def _draw_phase1(self) -> None:
        self.cvs.delete("phase1")
        self.glitch_targets.clear()
        self._left_offset  = 0
        self._right_offset = 0
        self._draw_right_card()
        self._draw_left_card()

    # ─── Right Card: UPLINK TELEMETRY ─────────────────────────────────────────
    def _draw_right_card(self) -> None:
        rw, rh = 470, 310
        rx = self.sw - rw - self.PAD
        ry = self.sh - rh - self.PAD

        # Store bar origin so _tick can update coords without recalculating
        self._bar_bx = rx + 28
        self._bar_by = ry + 268

        T       = ("phase1", "right_card")
        T_DYN_O = ("phase1", "right_card", "dyn_outline")
        T_DYN_F = ("phase1", "right_card", "dyn_fill")
        T_DYN_T = ("phase1", "right_card", "dyn_text")

        # ── Body ──
        self._octa(rx, ry, rw, rh, 28, fill=COLOR_PANEL,    outline="",           tags=T)
        self._octa(rx, ry, rw, rh, 28, fill="",             outline=COLOR_AMBER,  width=2, tags=T_DYN_O)
        self._octa(rx+3, ry+3, rw-6, rh-6, 26,
                                         fill="",             outline=COLOR_AMBER_DIM, width=1, tags=T)

        # ── Header bar ──
        self.cvs.create_rectangle(
            rx+28, ry, rx+rw-28, ry+36,
            fill=COLOR_AMBER, outline="", tags=T_DYN_F,
        )
        self.cvs.create_text(
            rx+44, ry+18, text="UPLINK·TELEMETRY", font=F_LABEL,
            fill=COLOR_VOID, anchor="w", tags=T,
        )
        self.cvs.create_text(
            rx+rw-44, ry+18, text=self.workstation, font=F_MICRO,
            fill=COLOR_VOID, anchor="e", tags=T,
        )

        # ── Inner corner brackets ──
        arm_i = 10
        self._bracket(rx+16, ry+46,     arm_i, COLOR_AMBER_DIM, T)
        self._bracket(rx+rw-16, ry+46,  arm_i, COLOR_AMBER_DIM, T, flip_x=True)

        # ── Telemetry hex dump (live) ──
        self.lbl_telemetry = self.cvs.create_text(
            rx+20, ry+52,
            text="", font=F_NANO,
            fill=COLOR_TEXT_DIM, anchor="nw", tags=T,
        )

        # ── Divider ──
        self._hline(rx+20, ry+118, rx+rw-20, COLOR_TEXT_DIM, T)

        # ── Section label ──
        self.cvs.create_text(
            rx+26, ry+128, text="CONTAINMENT DURATION", font=F_MICRO,
            fill=COLOR_TEXT_MID, anchor="w", tags=T_DYN_T,
        )

        # ── Giant countdown (glitch text) ──
        self.gt_timer = self._glitch_text(
            rx + rw - 28, ry + 210,
            tags=T_DYN_T,
            text=self._fmt(self.remaining),
            font=F_HUGE, fill=COLOR_AMBER, anchor="e",
        )

        # Decorative bracket around timer
        brace_x = rx + rw - 218
        self.cvs.create_line(
            brace_x+18, ry+130,
            brace_x,    ry+130,
            brace_x,    ry+228,
            brace_x+18, ry+228,
            fill=COLOR_AMBER_DIM, width=1, tags=T,
        )

        # ── Progress bar ──
        self.bar_w = rw - 56
        bx, by = self._bar_bx, self._bar_by
        self.cvs.create_rectangle(
            bx, by, bx + self.bar_w, by + 6,
            outline=COLOR_TEXT_DIM, fill="", tags=T,
        )
        self.bar_fill = self.cvs.create_rectangle(
            bx, by, bx, by + 6,
            outline="", fill=COLOR_AMBER, tags=T_DYN_F,
        )

        # ── Upload stage readout ──
        self.lbl_upload = self.cvs.create_text(
            bx, by + 16, text=UPLOAD_STAGES[0], font=F_NANO,
            fill=COLOR_TEXT_MID, anchor="w", tags=T,
        )

    # ─── Left Card: ADMIN OVERWATCH ───────────────────────────────────────────
    def _draw_left_card(self) -> None:
        lw, lh = 420, 280
        lx = self.PAD
        ly = self.sh - lh - self.PAD

        T       = ("phase1", "left_card")
        T_DYN_T = ("phase1", "left_card", "dyn_text")

        # ── Body ──
        self._octa(lx, ly, lw, lh, 24, fill=COLOR_PANEL,    outline="",           tags=T)
        self._octa(lx, ly, lw, lh, 24, fill="",             outline=COLOR_CYAN_DIM, width=2, tags=T)
        self._octa(lx+3, ly+3, lw-6, lh-6, 22,
                                         fill="",             outline=COLOR_CYAN_DIM, width=1, tags=T)

        # ── Header ──
        self.cvs.create_rectangle(
            lx+24, ly, lx+lw-24, ly+36,
            fill=COLOR_PANEL_HDR, outline="", tags=T,
        )
        self.cvs.create_text(
            lx+40, ly+18, text="ADMIN·OVERWATCH", font=F_LABEL,
            fill=COLOR_CYAN, anchor="w", tags=T,
        )
        # Live status indicator
        self.cvs.create_oval(lx+lw-68, ly+13, lx+lw-58, ly+23,
                             fill=COLOR_CYAN, outline="", tags=T)
        self.cvs.create_text(lx+lw-54, ly+18, text="LIVE",
                             font=F_NANO, fill=COLOR_CYAN, anchor="w", tags=T)

        # ── Inner corner brackets ──
        arm_i = 10
        self._bracket(lx+14, ly+46, arm_i, COLOR_CYAN_DIM, T)
        self._bracket(lx+lw-14, ly+46, arm_i, COLOR_CYAN_DIM, T, flip_x=True)

        # Divider
        self._hline(lx+16, ly+46, lx+lw-16, COLOR_TEXT_DIM, T)

        # ── Comms log entries ──
        log_y = ly + 56
        for i, (action, status, result) in enumerate(LOG_ENTRIES[:7]):
            col = COLOR_CYAN if i < 2 else (COLOR_TEXT_MID if i < 5 else COLOR_TEXT_DIM)
            row = f"{action:<24}  {status:<10}  {result}"
            self.cvs.create_text(
                lx+20, log_y + i * 17,
                text=row, font=F_NANO, fill=col, anchor="nw", tags=T,
            )

        # Divider before message zone
        self._hline(lx+16, ly+180, lx+lw-16, COLOR_TEXT_DIM, T)

        # ── Rotating message (glitch text) ──
        self.gt_msg = self._glitch_text(
            lx+20, ly+195,
            tags=T,
            text=MSGS[0], font=F_MICRO,
            fill=COLOR_TEXT_BRT, anchor="nw", width=lw-40,
        )

        # ── Typing indicator ──
        self.lbl_typing = self.cvs.create_text(
            lx+20, ly+252,
            text="Admin is reviewing .",
            font=F_MICRO, fill=COLOR_AMBER_DIM, anchor="w", tags=T_DYN_T,
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  Layer 2: Phase 2 — Transmission Failure  (T-17 → T-15)
    # ══════════════════════════════════════════════════════════════════════════
    def _execute_transmission_failure(self, step: int) -> None:
        """
        Catastrophic video-feed collapse. Horizontal tearing + frame drops.
        Runs for ~2.2 seconds (44 steps × 50ms).
        No window movement. All motion via canvas.move().
        """
        if not self.running or not self._root:
            return

        TOTAL = 44

        # Deepen overlay to seal focus on center
        if self._bg_win and step < 22:
            alpha = 0.70 + (0.22 * (step / 22.0))
            self._bg_win.attributes("-alpha", alpha)

        # Frame-drop: randomly blank each card each even step
        if step % 2 == 0:
            l_vis = "hidden" if random.random() < 0.45 else "normal"
            r_vis = "hidden" if random.random() < 0.45 else "normal"
            self.cvs.itemconfig("left_card",  state=l_vis)
            self.cvs.itemconfig("right_card", state=r_vis)

        # Signal tearing: large horizontal displacements
        dx_l = random.randint(-80, 80)
        dx_r = random.randint(-80, 80)
        self._left_offset  += dx_l
        self._right_offset += dx_r
        self.cvs.move("left_card",  dx_l, 0)
        self.cvs.move("right_card", dx_r, 0)

        # Heal back to exact origin 25ms later
        self._root.after(25, self._snap_to_origin)

        if step < TOTAL:
            self._root.after(50, lambda: self._execute_transmission_failure(step + 1))
        else:
            # Final flush, delete feeds, spawn the Monolith
            self._snap_to_origin()
            self.cvs.delete("phase1")
            self.glitch_targets.clear()
            self._left_offset  = 0
            self._right_offset = 0
            self._spawn_judgment_card()

    def _snap_to_origin(self) -> None:
        """Flush accumulated tear offsets back to zero in one move."""
        if not self._root:
            return
        try:
            if self._left_offset != 0:
                self.cvs.move("left_card",  -self._left_offset,  0)
                self._left_offset = 0
            if self._right_offset != 0:
                self.cvs.move("right_card", -self._right_offset, 0)
                self._right_offset = 0
        except Exception:
            pass

    def _heal_tear(self, tag: str, dx: int) -> None:
        """Micro-tear heal for Phase 1 feed loops."""
        try:
            self.cvs.move(tag, dx, 0)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    #  Layer 3: Phase 3 — The Judgment Monolith  (T-15 → T-00)
    # ══════════════════════════════════════════════════════════════════════════
    def _spawn_judgment_card(self) -> None:
        """
        Pre-allocate ALL Monolith canvas items at step 0.
        The decryption loop (_decrypt_step) calls itemconfig ONLY — never
        recreates items. This guarantees lbl_center_timer is always a valid ID.
        """
        self.phase = "judgment"
        self.cvs.delete("main_card")

        W, H = 920, 360
        x = (self.sw - W) // 2
        y = (self.sh - H) // 2

        # ── Structural geometry ──
        # Outer halo
        self._octa(x-6, y-6, W+12, H+12, 48,
                   fill="", outline=COLOR_RED_DIM, width=1, tags="main_card")
        # Main body
        self._octa(x, y, W, H, 44,
                   fill=COLOR_PANEL, outline=COLOR_RED, width=3, tags="main_card")
        # Inner accent ring
        self._octa(x+5, y+5, W-10, H-10, 42,
                   fill="", outline=COLOR_RED_DIM, width=1, tags="main_card")

        # ── Header bar ──
        self.cvs.create_rectangle(
            x+44, y, x+W-44, y+42,
            fill=COLOR_RED, outline="", tags="main_card",
        )
        self.cvs.create_text(
            x + W//2, y+21,
            text="[ SYSTEM CONTAINMENT LOCKED ]",
            font=F_TITLE, fill=COLOR_VOID, anchor="center", tags="main_card",
        )

        # ── Decorative corner brackets (inside card) ──
        arm = 16
        self._bracket(x+18,   y+54,   arm, COLOR_RED_DIM, "main_card")
        self._bracket(x+W-18, y+54,   arm, COLOR_RED_DIM, "main_card", flip_x=True)
        self._bracket(x+18,   y+H-18, arm, COLOR_RED_DIM, "main_card", flip_y=True)
        self._bracket(x+W-18, y+H-18, arm, COLOR_RED_DIM, "main_card", flip_x=True, flip_y=True)

        # ── Text items — PRE-ALLOCATED with empty strings ──
        # They are updated by _decrypt_step, never recreated.

        # Row 1: Giant violation title
        self._mono_title = self.cvs.create_text(
            x + W//2, y + 128,
            text="", font=F_HUGE, fill=COLOR_RED, anchor="center",
            tags="main_card",
        )

        # Row 2: Trigger cause
        self._mono_sub = self.cvs.create_text(
            x + W//2, y + 196,
            text="", font=F_GLITCH, fill=COLOR_ORANGE, anchor="center",
            tags="main_card",
        )

        # Row 3: Sarcastic quote
        self._mono_quote = self.cvs.create_text(
            x + W//2, y + 224,
            text="", font=F_QUOTE, fill=COLOR_TEXT_MID, anchor="center",
            tags="main_card",
        )

        # Horizontal rule before countdown (hidden until mid-animation)
        self._mono_rule = self._hline(
            x + 70, y + 248, x + W - 70, COLOR_RED_DIM, "main_card",
        )
        self.cvs.itemconfig(self._mono_rule, state="hidden")

        # Row 4: Release countdown — ALWAYS a valid canvas ID from this point on
        self.lbl_center_timer = self.cvs.create_text(
            x + W//2, y + 308,
            text="", font=F_BODY, fill=COLOR_TEXT_MID, anchor="center",
            tags="main_card",
        )

        # Begin decryption sequence
        self._decrypt_step(0)

    def _decrypt_step(self, step: int) -> None:
        """
        Gradually resolve scrambled text into final strings.
        Updates pre-allocated canvas items only — no delete/recreate.
        """
        if not self.running or not self._root:
            return

        TOTAL    = 22
        progress = step / TOTAL

        title_str  = "CRITICAL  POLICY  VIOLATION"
        sub_str    = f"TRIGGER CAUGHT :  {self.trigger}"
        quote_str  = f'"{self.final_quote}"'
        timer_str  = f"RELEASING IN {self.remaining}s   ·   EVIDENCE SECURED"

        def _scramble(target: str, prog: float) -> str:
            n = int(len(target) * min(prog, 1.0))
            resolved  = target[:n]
            noise     = "".join(random.choice(_NOISE) for _ in range(len(target) - n))
            return resolved + noise

        # Title resolves from step 0
        self.cvs.itemconfig(self._mono_title,
                            text=_scramble(title_str, progress))

        # Sub resolves from step 5
        if step >= 5:
            self.cvs.itemconfig(self._mono_sub,
                                text=_scramble(sub_str, (step - 5) / (TOTAL - 5)))

        # Quote resolves from step 9
        if step >= 9:
            self.cvs.itemconfig(self._mono_quote,
                                text=_scramble(quote_str, (step - 9) / (TOTAL - 9)))

        # Rule + countdown appear from step 14
        if step >= 14:
            self.cvs.itemconfig(self._mono_rule, state="normal")
            self.cvs.itemconfig(self.lbl_center_timer,
                                text=_scramble(timer_str, (step - 14) / (TOTAL - 14)))

        if step < TOTAL:
            self._root.after(40, lambda: self._decrypt_step(step + 1))

    # ══════════════════════════════════════════════════════════════════════════
    #  Logic & Clock
    # ══════════════════════════════════════════════════════════════════════════
    def _tick(self) -> None:
        if not self.running or not self._root:
            return

        if self.remaining > 0:
            self.remaining -= 1

        # Threat escalation: amber → orange at T-30
        if self.remaining == 30 and self.phase == "containment":
            self.threat_level = 2
            try:
                self.cvs.itemconfig("dyn_outline", outline=COLOR_ORANGE)
                self.cvs.itemconfig("dyn_fill",    fill=COLOR_ORANGE)
                for gt in self.glitch_targets:
                    if "dyn_text" in self.cvs.gettags(gt["base"]):
                        self.cvs.itemconfig(gt["base"],  fill=COLOR_ORANGE)
            except Exception:
                pass

        # Phase 1 updates
        if self.phase == "containment":
            fmt = self._fmt(self.remaining)
            for key in ("base", "cyan", "red"):
                try:
                    self.cvs.itemconfig(self.gt_timer[key], text=fmt)
                except Exception:
                    pass

            pct       = self.remaining / self.duration if self.duration else 0
            fill_w    = max(1, int(self.bar_w * (1.0 - pct)))
            bx, by    = self._bar_bx, self._bar_by
            self.cvs.coords(self.bar_fill, bx, by, bx + fill_w, by + 6)

            if self.remaining == 17:
                self.phase = "transition"
                self._execute_transmission_failure(0)

        # Phase 3 countdown update — lbl_center_timer is always valid here
        elif self.phase == "judgment":
            try:
                self.cvs.itemconfig(
                    self.lbl_center_timer,
                    text=f"RELEASING IN {self.remaining}s   ·   EVIDENCE SECURED",
                )
            except Exception:
                pass

        if self.remaining <= 0:
            self.dismiss()
            return

        self._root.after(1000, self._tick)

    # ══════════════════════════════════════════════════════════════════════════
    #  Asynchronous Animation Engines
    # ══════════════════════════════════════════════════════════════════════════
    def _global_anim_loop(self) -> None:
        """Scanline sweep + hex telemetry + typing indicator."""
        if not self.running or not self._root:
            return
        self.anim_tick += 1

        # Scanline sweep (3px/tick = 180px/sec at 60fps)
        sy = (self.anim_tick * 3) % self.sh
        self.cvs.coords(self.scanline, 0, sy, self.sw, sy)

        if self.phase == "containment":
            # Typing dots
            if self.anim_tick % 12 == 0 and hasattr(self, "lbl_typing"):
                dots = "." * ((self.anim_tick // 12) % 5)
                self.cvs.itemconfig(self.lbl_typing,
                                    text=f"Admin is reviewing {dots}")

            # Hex dump (faster at threat level 2)
            rate = 5 if self.threat_level == 1 else 2
            if self.anim_tick % rate == 0 and hasattr(self, "lbl_telemetry"):
                lines = []
                for _ in range(5):
                    addr = f"0x{random.randint(0, 0xFFFFFF):06X}"
                    vals = " ".join(f"{random.randint(0, 255):02X}"
                                   for _ in range(6))
                    lines.append(f"{addr}  {vals}")
                self.cvs.itemconfig(self.lbl_telemetry, text="\n".join(lines))

        self._root.after(50, self._global_anim_loop)

    def _left_feed_loop(self) -> None:
        """Independent micro-tear loop for the left card."""
        if not self.running or not self._root or self.phase != "containment":
            return

        delay = (random.randint(900, 2800) if self.threat_level == 1
                 else random.randint(350, 900))

        if random.random() < 0.55:
            dx = random.randint(-8, 8)
            self.cvs.move("left_card", dx, 0)
            self._root.after(
                random.randint(25, 65),
                lambda d=dx: self._heal_tear("left_card", -d),
            )

        self._root.after(delay, self._left_feed_loop)

    def _right_feed_loop(self) -> None:
        """Independent micro-tear loop for the right card."""
        if not self.running or not self._root or self.phase != "containment":
            return

        delay = (random.randint(700, 2200) if self.threat_level == 1
                 else random.randint(280, 700))

        if random.random() < 0.50:
            dx = random.randint(-6, 10)
            self.cvs.move("right_card", dx, 0)
            self._root.after(
                random.randint(30, 75),
                lambda d=dx: self._heal_tear("right_card", -d),
            )

        self._root.after(delay, self._right_feed_loop)

    def _aberration_loop(self) -> None:
        """
        RGB chromatic aberration: red layer shifts right, cyan shifts left.
        Independent async loop running at 30ms intervals.
        """
        if not self.running or not self._root or self.phase != "containment":
            return

        chance = 0.04 if self.threat_level == 1 else 0.14

        for gt in self.glitch_targets:
            if not gt["glitching"] and random.random() < chance:
                gt["glitching"] = True
                dx = random.randint(4, 9)

                self.cvs.itemconfig(gt["base"], state="hidden")
                self.cvs.itemconfig(gt["cyan"], state="normal")
                self.cvs.itemconfig(gt["red"],  state="normal")
                self.cvs.coords(gt["cyan"], gt["x"] - dx, gt["y"])   # cyan left
                self.cvs.coords(gt["red"],  gt["x"] + dx, gt["y"])   # red right

                heal_ms = random.randint(45, 130)
                self._root.after(heal_ms, lambda t=gt: self._heal_aberration(t))

        self._root.after(30, self._aberration_loop)

    def _heal_aberration(self, gt: dict) -> None:
        if not self.running or not self._root:
            return
        try:
            self.cvs.itemconfig(gt["base"], state="normal")
            self.cvs.itemconfig(gt["cyan"], state="hidden")
            self.cvs.itemconfig(gt["red"],  state="hidden")
            self.cvs.coords(gt["cyan"], gt["x"], gt["y"])
            self.cvs.coords(gt["red"],  gt["x"], gt["y"])
            gt["glitching"] = False
        except Exception:
            pass

    def _rotate_msg(self) -> None:
        """Cycle the sarcasm message in the left card every 5 seconds."""
        if not self.running or not self._root:
            return
        if self.phase == "containment":
            self.msg_idx = (self.msg_idx + 1) % len(MSGS)
            txt = MSGS[self.msg_idx]
            try:
                self.cvs.itemconfig(self.gt_msg["base"], text=txt)
                self.cvs.itemconfig(self.gt_msg["cyan"], text=txt)
                self.cvs.itemconfig(self.gt_msg["red"],  text=txt)
            except Exception:
                pass
            if hasattr(self, "lbl_upload"):
                stage = UPLOAD_STAGES[(self.msg_idx // 2) % len(UPLOAD_STAGES)]
                self.cvs.itemconfig(self.lbl_upload, text=stage)

        self._root.after(5000, self._rotate_msg)

    def _stay_on_top(self) -> None:
        if not self.running or not self._root:
            return
        if self.cinematic and self._bg_win:
            self._bg_win.attributes("-topmost", True)
            self._bg_win.lift()
        self._root.attributes("-topmost", True)
        self._root.lift()
        self._root.after(500, self._stay_on_top)

    @staticmethod
    def _fmt(s: int) -> str:
        return f"{s // 60:02d}:{s % 60:02d}"


# ── Environment Bridge ─────────────────────────────────────────────────────────
def _hostname() -> str:
    try:    return socket.gethostname()
    except: return "UNKNOWN-NODE"


_hud: FreezeHUD | None = None
_hud_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
#  Public API (drop-in replacement — identical signatures)
# ══════════════════════════════════════════════════════════════════════════════
def engage_freeze_with_hud(
    warden      = None,
    duration:    int        = 60,
    trigger:     str        = "POLICY_VIOLATION",
    workstation: str | None = None,
    cinematic:   bool       = True,
) -> None:
    if warden and getattr(warden, "system_frozen", False):
        return
    if warden:
        warden.engage_freeze(duration=duration)
    _show(trigger=trigger, duration=duration, workstation=workstation, cinematic=cinematic)


def dismiss_freeze_hud(warden=None) -> None:
    _dismiss()
    if warden is not None:
        warden.disengage_freeze()


def _show(
    trigger:     str        = "POLICY_VIOLATION",
    duration:    int        = 60,
    workstation: str | None = None,
    cinematic:   bool       = True,
) -> None:
    global _hud
    with _hud_lock:
        if _hud is not None:
            _hud.dismiss()
        _hud = FreezeHUD(
            trigger=trigger, duration=duration,
            workstation=workstation or _hostname(), cinematic=cinematic,
        )
        _hud.show()


def _dismiss() -> None:
    global _hud
    with _hud_lock:
        if _hud is not None:
            _hud.dismiss()
            _hud = None


if __name__ == "__main__":
    import time
    print("Deploying Sentinel HUD v13.0 [MONOLITH] — standalone test (60s) …")
    engage_freeze_with_hud(
        warden=None,
        trigger="PROXY_BYPASS_DETECTED",
        duration=60,
        cinematic=True,
    )
    time.sleep(75)
    print("Execution finalized.")