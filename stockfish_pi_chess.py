import time
import queue
import struct
import wave
import tempfile
import sys
import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path


import chess
import chess.pgn
import chess.engine
import chess.syzygy

from PySide6.QtCore import QRectF, Qt, Signal, QObject, QRect, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QComboBox, QSpinBox, QProgressBar, QTabWidget, QPlainTextEdit, QGroupBox,
    QFormLayout, QLineEdit, QCheckBox, QSplitter, QSizePolicy)

PIECES = {
    "P":"♙","N":"♘","B":"♗","R":"♖","Q":"♕","K":"♔",
    "p":"♟","n":"♞","b":"♝","r":"♜","q":"♛","k":"♚",
}

@dataclass
class ReviewRow:
    ply: int
    san: str
    uci: str
    mover: chess.Color
    score_before: int | None
    score_after: int | None
    loss: int | None
    classification: str
    bestmove: str
    pv: str
    fen_after: str

class Bridge(QObject):
    position_done = Signal(object)
    review_progress = Signal(int, int, str)
    review_done = Signal(object)
    failed = Signal(str)

class RemoteStockfish:
    """Launches Stockfish locally or through Windows OpenSSH and lets python-chess speak UCI."""
    def __init__(self):
        self.engine = None
        self.lock = threading.Lock()

    def connect(self, command: str):
        self.close()
        argv = shlex.split(command, posix=False)
        # shlex on Windows may retain quotes in odd places; strip matching quotes.
        argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'" else a for a in argv]
        self.engine = chess.engine.SimpleEngine.popen_uci(argv)
        return self.engine.id.get("name", "Stockfish")

    def configure(self, threads=4, hash_mb=512):
        if not self.engine:
            raise RuntimeError("Stockfish is not connected.")
        options = {}
        if "Threads" in self.engine.options:
            options["Threads"] = int(threads)
        if "Hash" in self.engine.options:
            options["Hash"] = int(hash_mb)
        if options:
            with self.lock:
                self.engine.configure(options)
        return options

    def close(self):
        if self.engine:
            try:
                self.engine.quit()
            except Exception:
                try: self.engine.close()
                except Exception: pass
        self.engine = None

    def analyse(self, board, seconds=1.0, multipv=1):
        if not self.engine:
            raise RuntimeError("Stockfish is not connected.")
        with self.lock:
            return self.engine.analyse(
                board,
                chess.engine.Limit(time=max(0.05, float(seconds))),
                multipv=max(1, int(multipv)),
            )

    def play(self, board, level="Medium"):
        """Ask Stockfish for one move using a deliberately limited playing level."""
        if not self.engine:
            raise RuntimeError("Stockfish is not connected.")
        settings = {
            "Easy":   {"skill": 1,  "time": 0.12},
            "Medium": {"skill": 8,  "time": 0.45},
            "Hard":   {"skill": 18, "time": 1.20},
        }
        s = settings.get(level, settings["Medium"])
        options = {}
        if "Skill Level" in self.engine.options:
            options["Skill Level"] = s["skill"]
        with self.lock:
            result = self.engine.play(
                board,
                chess.engine.Limit(time=s["time"]),
                options=options or None,
            )
        return result.move

class BoardWidget(QWidget):
    move_requested = Signal(object)

    def __init__(self, app):
        super().__init__()
        self.parent_window=app
        self.app = app
        self.selected = None
        self.legal_targets = set()
        self.arrow = None
        self.review_played_arrow = None
        self.review_classification = None
        self.candidate_arrows = []
        self.anim_move = None
        self.anim_progress = 0.0
        self.anim_piece = None
        self.anim_callback = None
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._animation_tick)
        self.anim_duration_ms = 520
        self.setMinimumSize(520, 520)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(640, 640)

    def geometry_data(self):
        side = min(self.width(), self.height()) - 16
        side = max(80, side)
        sq = side / 8
        x0 = (self.width() - side) / 2
        y0 = (self.height() - side) / 2
        return x0, y0, side, sq

    def display_to_square(self, col, row):
        if not self.app.flipped:
            file_ = col
            rank = 7 - row
        else:
            file_ = 7 - col
            rank = row
        return chess.square(file_, rank)

    def square_to_display(self, square):
        f = chess.square_file(square)
        r = chess.square_rank(square)
        if not self.app.flipped:
            return f, 7-r
        return 7-f, r

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        x0, y0, side, sq = self.geometry_data()
        x, y = ev.position().x(), ev.position().y()
        if not (x0 <= x < x0+side and y0 <= y < y0+side):
            return
        col, row = int((x-x0)//sq), int((y-y0)//sq)
        target = self.display_to_square(col, row)
        board = self.app.board

        if self.selected is None:
            piece = board.piece_at(target)
            if piece and piece.color == board.turn:
                self.selected = target
                self.legal_targets = {m.to_square for m in board.legal_moves if m.from_square == target}
                self.update()
            return

        if target == self.selected:
            self.selected = None
            self.legal_targets.clear()
            self.update()
            return

        candidates = [m for m in board.legal_moves if m.from_square == self.selected and m.to_square == target]
        if candidates:
            move = candidates[0]
            if any(m.promotion == chess.QUEEN for m in candidates):
                move = next(m for m in candidates if m.promotion == chess.QUEEN)
            self.selected = None
            self.legal_targets.clear()
            self.move_requested.emit(move)
            self.update()
            return

        piece = board.piece_at(target)
        if piece and piece.color == board.turn:
            self.selected = target
            self.legal_targets = {m.to_square for m in board.legal_moves if m.from_square == target}
        else:
            self.selected = None
            self.legal_targets.clear()
        self.update()

    def animate_move(self, move, callback=None, duration_ms=520):
        """Animate a piece smoothly from its source square to its destination."""
        if self.anim_timer.isActive():
            self.anim_timer.stop()
        self.anim_move = move
        self.anim_progress = 0.0
        self.anim_piece = self.app.board.piece_at(move.from_square)
        self.anim_callback = callback
        self.anim_duration_ms = max(120, int(duration_ms))
        self.anim_elapsed_ms = 0
        self.anim_timer.start()
        self.update()

    def _animation_tick(self):
        self.anim_elapsed_ms += self.anim_timer.interval()
        t = min(1.0, self.anim_elapsed_ms / float(self.anim_duration_ms))
        # Smoothstep easing: gentle start and finish, without feeling sluggish.
        self.anim_progress = t*t*(3.0-2.0*t)
        self.update()
        if t >= 1.0:
            self.anim_timer.stop()
            cb = self.anim_callback
            move = self.anim_move
            self.anim_move = None
            self.anim_piece = None
            self.anim_callback = None
            self.update()
            if cb:
                cb(move)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x0, y0, side, sq = self.geometry_data()

        light = QColor("#dfe5e8")
        dark = QColor("#71879a")
        select = QColor(246, 246, 105, 180)
        last = QColor(205, 210, 106, 145)

        last_move = self.app.board.peek() if self.app.board.move_stack else None
        for row in range(8):
            for col in range(8):
                square = self.display_to_square(col, row)
                color = light if (col+row) % 2 == 0 else dark
                p.fillRect(int(x0+col*sq), int(y0+row*sq), int(sq+1), int(sq+1), color)
                if last_move and square in (last_move.from_square, last_move.to_square):
                    p.fillRect(int(x0+col*sq), int(y0+row*sq), int(sq+1), int(sq+1), last)
                if square == self.selected:
                    p.fillRect(int(x0+col*sq), int(y0+row*sq), int(sq+1), int(sq+1), select)

        # legal move dots
        p.setBrush(QColor(40, 40, 40, 90))
        p.setPen(Qt.NoPen)
        for square in self.legal_targets:
            col, row = self.square_to_display(square)
            cx, cy = x0+(col+.5)*sq, y0+(row+.5)*sq
            rad = max(5, sq*0.10)
            p.drawEllipse(int(cx-rad), int(cy-rad), int(rad*2), int(rad*2))

        # selectable chess-piece presentation
        style = self.app.piece_style
        if style == "Classic":
            family, scale, dy = "Segoe UI Symbol", 0.68, -0.02
        elif style == "Bold":
            family, scale, dy = "DejaVu Sans", 0.70, -0.02
        elif style == "Outline":
            family, scale, dy = "Segoe UI Symbol", 0.64, -0.01
        else:  # Compact
            family, scale, dy = "Segoe UI Symbol", 0.57, 0.00

        font = QFont(family)
        font.setStyleStrategy(QFont.PreferAntialias)
        font.setPointSizeF(max(22, sq * scale))
        if style == "Bold":
            font.setBold(True)
        p.setFont(font)

        for square, piece in self.app.board.piece_map().items():
            if self.anim_move is not None and square == self.anim_move.from_square:
                continue
            col, row = self.square_to_display(square)
            from PySide6.QtCore import QRect
            rect = QRect(int(x0+col*sq), int(y0+row*sq+dy*sq), int(sq), int(sq))
            glyph = PIECES[piece.symbol()]

            if style == "Outline":
                # Repeated one-pixel offsets give a more strongly outlined set.
                edge = QColor("#161616") if piece.color == chess.WHITE else QColor("#f5f5f5")
                p.setPen(edge)
                for ox,oy in ((-1,0),(1,0),(0,-1),(0,1)):
                    p.drawText(rect.translated(ox,oy), Qt.AlignCenter, glyph)
                p.setPen(QColor("#ffffff") if piece.color == chess.WHITE else QColor("#111111"))
                p.drawText(rect, Qt.AlignCenter, glyph)
            else:
                if piece.color == chess.WHITE:
                    p.setPen(QColor("#252525"))
                    p.drawText(rect.translated(1,1), Qt.AlignCenter, glyph)
                    p.setPen(QColor("#ffffff"))
                else:
                    p.setPen(QColor("#eeeeee"))
                    p.drawText(rect.translated(1,1), Qt.AlignCenter, glyph)
                    p.setPen(QColor("#111111"))
                p.drawText(rect, Qt.AlignCenter, glyph)

        # Animated server piece, drawn above the board while the real board
        # remains unchanged until the animation finishes.
        if self.anim_move is not None and self.anim_piece is not None:
            fc, fr = self.square_to_display(self.anim_move.from_square)
            tc, tr = self.square_to_display(self.anim_move.to_square)
            t = self.anim_progress
            col = fc + (tc-fc)*t
            row = fr + (tr-fr)*t
            from PySide6.QtCore import QRect
            rect = QRect(int(x0+col*sq), int(y0+row*sq-0.02*sq), int(sq), int(sq))
            glyph = PIECES[self.anim_piece.symbol()]
            # Use the current piece style for the moving piece as well.
            style = self.app.piece_style
            if style == "Classic":
                family, scale = "Segoe UI Symbol", 0.68
            elif style == "Bold":
                family, scale = "DejaVu Sans", 0.70
            elif style == "Outline":
                family, scale = "Segoe UI Symbol", 0.64
            else:
                family, scale = "Segoe UI Symbol", 0.57
            afont=QFont(family)
            afont.setStyleStrategy(QFont.PreferAntialias)
            afont.setPointSizeF(max(22, sq*scale))
            if style == "Bold": afont.setBold(True)
            p.setFont(afont)
            if self.anim_piece.color == chess.WHITE:
                p.setPen(QColor("#252525")); p.drawText(rect.translated(1,1), Qt.AlignCenter, glyph)
                p.setPen(QColor("#ffffff"))
            else:
                p.setPen(QColor("#eeeeee")); p.drawText(rect.translated(1,1), Qt.AlignCenter, glyph)
                p.setPen(QColor("#111111"))
            p.drawText(rect, Qt.AlignCenter, glyph)

        # Game-review played-move arrow.
        # This is deliberately distinct from the blue Stockfish-best arrow.
        if self.review_played_arrow:
            try:
                a=chess.parse_square(self.review_played_arrow[:2]); b=chess.parse_square(self.review_played_arrow[2:4])
                ac,ar=self.square_to_display(a); bc,br=self.square_to_display(b)
                ax,ay=x0+(ac+.5)*sq,y0+(ar+.5)*sq
                bx,by=x0+(bc+.5)*sq,y0+(br+.5)*sq
                cls=self.review_classification or ""
                col=QColor(220,55,55,220) if cls=="Blunder" else QColor(235,125,45,220)
                pen=QPen(col,max(5,sq*0.09))
                pen.setStyle(Qt.DashLine)
                p.setPen(pen); p.setBrush(col)
                p.drawLine(int(ax),int(ay),int(bx),int(by))
                import math
                ang=math.atan2(by-ay,bx-ax); head=sq*.22
                leftp=(bx-head*math.cos(ang-.55),by-head*math.sin(ang-.55))
                rightp=(bx-head*math.cos(ang+.55),by-head*math.sin(ang+.55))
                from PySide6.QtCore import QPointF
                p.drawPolygon(QPolygonF([QPointF(bx,by),QPointF(*leftp),QPointF(*rightp)]))
                # Clear label near the played move's destination.
                label="PLAYED"
                p.setPen(QColor("#ffffff"))
                p.setFont(QFont("Segoe UI",max(8,int(sq*.13)),QFont.Bold))
                tag=QRectF(bx-sq*.43,by-sq*.46,sq*.86,sq*.24)
                p.fillRect(tag,QColor(25,25,25,210))
                p.drawText(tag,Qt.AlignCenter,label)
            except Exception:
                pass

        # Candidate move arrows from MultiPV analysis: #2 and #3 are thinner/lighter.
        for idx, uci in enumerate(self.candidate_arrows[:2], start=2):
            try:
                a=chess.parse_square(uci[:2]); b=chess.parse_square(uci[2:4])
                ac,ar=self.square_to_display(a); bc,br=self.square_to_display(b)
                ax,ay=x0+(ac+.5)*sq,y0+(ar+.5)*sq; bx,by=x0+(bc+.5)*sq,y0+(br+.5)*sq
                alpha=135 if idx==2 else 90
                col=QColor(90,155,225,alpha)
                p.setPen(QPen(col,max(2,sq*(0.055 if idx==2 else 0.04))))
                p.setBrush(col); p.drawLine(int(ax),int(ay),int(bx),int(by))
                import math
                ang=math.atan2(by-ay,bx-ax); head=sq*(.16 if idx==2 else .13)
                from PySide6.QtCore import QPointF
                p.drawPolygon(QPolygonF([QPointF(bx,by), QPointF(bx-head*math.cos(ang-.55),by-head*math.sin(ang-.55)), QPointF(bx-head*math.cos(ang+.55),by-head*math.sin(ang+.55))]))
                p.setPen(QColor(255,255,255,190)); p.setFont(QFont("Segoe UI",max(7,int(sq*.11)),QFont.Bold))
                p.drawText(QRectF(bx-sq*.12,by-sq*.12,sq*.24,sq*.24),Qt.AlignCenter,str(idx))
            except Exception:
                pass

        # best-line arrow
        if self.arrow:
            try:
                a = chess.parse_square(self.arrow[:2]); b = chess.parse_square(self.arrow[2:4])
                ac, ar = self.square_to_display(a); bc, br = self.square_to_display(b)
                ax, ay = x0+(ac+.5)*sq, y0+(ar+.5)*sq
                bx, by = x0+(bc+.5)*sq, y0+(br+.5)*sq
                pen = QPen(QColor(64, 110, 180, 190), max(4, sq*0.08))
                p.setPen(pen); p.setBrush(QColor(64, 110, 180, 190))
                p.drawLine(int(ax), int(ay), int(bx), int(by))
                import math
                ang = math.atan2(by-ay, bx-ax)
                head = sq*.20
                leftp = (bx-head*math.cos(ang-.55), by-head*math.sin(ang-.55))
                rightp = (bx-head*math.cos(ang+.55), by-head*math.sin(ang+.55))
                from PySide6.QtCore import QPointF
                p.drawPolygon(QPolygonF([QPointF(bx,by), QPointF(*leftp), QPointF(*rightp)]))
            except Exception:
                pass

        # coordinates
        small = QFont("Segoe UI", max(7, int(sq*.12)))
        p.setFont(small); p.setPen(QColor("#444"))
        for i in range(8):
            file_label = "abcdefgh"[7-i if self.app.flipped else i]
            rank_label = str(i+1 if self.app.flipped else 8-i)
            p.drawText(int(x0+i*sq+4), int(y0+side-4), file_label)
            p.drawText(int(x0+3), int(y0+i*sq+14), rank_label)


        self.draw_check_reaction(p)
    def draw_check_reaction(self, painter):
        text=getattr(self.parent_window,"check_reaction_text","") if hasattr(self,"parent_window") else ""
        until=getattr(self.parent_window,"check_reaction_until",0.0) if hasattr(self,"parent_window") else 0.0
        if not text or time.monotonic() >= until:
            return
        rect=self.rect()
        box=QRectF(float(rect.center().x()-155), float(rect.center().y()-50), 310.0, 100.0)
        painter.save()
        try:
            painter.setBrush(QColor(20,20,20,210))
            painter.setPen(QPen(QColor("#e53935"),4))
            painter.drawRoundedRect(box,16,16)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI",28,QFont.Bold))
            painter.drawText(box,Qt.AlignCenter,text)
        finally:
            painter.restore()


class EvaluationBar(QWidget):
    """Vertical White/Black evaluation bar, score from White's point of view."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cp = 0
        self.label = "0.00"
        self.setMinimumWidth(54)
        self.setMaximumWidth(62)

    def set_eval(self, cp, label=None):
        self.cp = max(-1500, min(1500, int(cp)))
        self.label = label if label is not None else f"{self.cp/100:+.2f}"
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(7, 8, -7, -8)
        if r.height() <= 0:
            return

        # Smooth bounded mapping: +/- 600cp already looks decisive,
        # while extreme scores never make either side completely disappear.
        import math
        white_share = 0.5 + 0.46 * math.tanh(self.cp / 500.0)
        white_h = int(r.height() * white_share)
        split_y = r.bottom() - white_h + 1

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#171a1f"))
        p.drawRoundedRect(r, 8, 8)

        white_rect = QRect(r.left(), split_y, r.width(), max(0, r.bottom()-split_y+1))
        p.setBrush(QColor("#f2f3f5"))
        p.drawRect(white_rect)

        p.setPen(QPen(QColor("#50545b"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)

        # Score shown on the side currently ahead.
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        p.setFont(font)
        if self.cp >= 0:
            p.setPen(QColor("#15171a"))
            text_rect = QRect(r.left(), r.bottom()-42, r.width(), 34)
        else:
            p.setPen(QColor("#f7f7f7"))
            text_rect = QRect(r.left(), r.top()+8, r.width(), 34)
        p.drawText(text_rect, Qt.AlignCenter, self.label.replace("+",""))

class EvalGraph(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setMinimumHeight(150)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 40, 12, 14, 28
        gw, gh = max(10,w-left-right), max(10,h-top-bottom)
        mid = top + gh/2
        p.setPen(QPen(QColor("#aaa"), 1, Qt.DashLine))
        p.drawLine(left, int(mid), left+gw, int(mid))
        rows = self.app.review_rows
        pts = [(0,0)]
        for r in rows:
            if r.score_after is not None:
                pts.append((r.ply, max(-800,min(800,r.score_after))))
        if len(pts) < 2:
            p.setPen(QColor("#666"))
            p.drawText(self.rect(), Qt.AlignCenter, "Run Review Game to build the evaluation graph")
            return
        maxx=max(x for x,_ in pts) or 1
        scale=gh/2/800
        from PySide6.QtCore import QPointF
        q=[QPointF(left+(x/maxx)*gw, mid-y*scale) for x,y in pts]
        p.setPen(QPen(QColor("#555"),2))
        for a,b in zip(q,q[1:]): p.drawLine(a,b)
        p.setBrush(QColor("#555")); p.setPen(Qt.NoPen)
        for pt in q: p.drawEllipse(pt,3,3)
        p.setPen(QColor("#666"))
        p.drawText(4, int(top+10), "White +")
        p.drawText(4, int(top+gh), "Black +")

def white_pov_cp(score):
    if score is None: return None
    s = score.pov(chess.WHITE)
    if s.is_mate():
        m=s.mate()
        return 100000 if m and m>0 else -100000
    return s.score()

def score_text(score):
    if score is None: return "?"
    s=score.pov(chess.WHITE)
    if s.is_mate():
        m=s.mate()
        return f"M{abs(m)} {'White' if m and m>0 else 'Black'}"
    cp=s.score()
    return "?" if cp is None else f"{cp/100:+.2f}"

def classify(loss):
    if loss is None: return ""
    if loss < 25: return "Best/Good"
    if loss < 60: return "Inaccuracy"
    if loss < 150: return "Mistake"
    return "Blunder"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stockfish Pi Chess — Training Suite")

        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #20242b;
                color: #e8eaed;
                font-family: "Segoe UI";
                font-size: 10pt;
            }
            QLabel#AppTitle {
                font-size: 20pt;
                font-weight: 700;
                color: #ffffff;
                letter-spacing: 1px;
            }
            QLabel#ReviewDetail {
                background: #171a20;
                border: 2px solid #4d78cc;
                border-radius: 8px;
                padding: 10px;
                font-size: 11pt;
            }
            QListWidget#ReviewList::item {
                padding: 7px 6px;
            }
            QListWidget#ReviewList::item:selected {
                background: #345a9c;
                color: white;
            }
            QLabel#AppSubtitle {
                color: #9ea7b3;
                font-size: 10pt;
            }
            QPushButton {
                background: #343a43;
                border: 1px solid #4b535f;
                border-radius: 7px;
                padding: 7px 11px;
                min-height: 22px;
            }
            QPushButton:hover { background: #414955; border-color: #687384; }
            QPushButton:pressed { background: #2a2f36; }
            QPushButton:disabled { color: #737b86; background: #292d33; }
            QPushButton#PlayServerButton {
                background: #315f4a;
                border-color: #4b8a6d;
                font-weight: 700;
                padding-left: 16px;
                padding-right: 16px;
            }
            QPushButton#PlayServerButton:hover { background: #3b7259; }
            QLabel#PlayStatus { color: #aeb8c4; font-style: italic; }
            QGroupBox {
                border: 1px solid #454c56;
                border-radius: 8px;
                margin-top: 9px;
                padding-top: 10px;
                font-weight: 600;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLineEdit, QComboBox, QSpinBox {
                background: #171a1f;
                border: 1px solid #454c56;
                border-radius: 6px;
                padding: 5px 7px;
                selection-background-color: #4d78a8;
            }
            QTabWidget::pane {
                border: 1px solid #3d444d;
                border-radius: 8px;
                background: #252a31;
                top: -1px;
            }
            QTabBar::tab {
                background: #2b3037;
                color: #b9c0c9;
                padding: 9px 16px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background: #3a424d;
                color: #ffffff;
            }
            QListWidget, QTextEdit {
                background: #171a1f;
                border: 1px solid #3f4650;
                border-radius: 7px;
                padding: 5px;
                alternate-background-color: #20252c;
            }
            QListWidget::item { padding: 5px; border-radius: 4px; }
            QListWidget::item:selected { background: #476d96; color: white; }
            QProgressBar {
                background: #171a1f;
                border: 1px solid #3f4650;
                border-radius: 6px;
                text-align: center;
                min-height: 18px;
            }
            QProgressBar::chunk { background: #5f86ad; border-radius: 5px; }
            QStatusBar { background: #171a1f; color: #aeb6c1; }
        """)

        self.resize(1250, 780)
        self.board = chess.Board()
        self.game_start_fen = chess.STARTING_FEN
        self.game_moves = []
        self.loaded_headers = chess.pgn.Headers()
        self.flipped = False
        self.piece_style = "Classic"
        self.visual_eval_cp = 0
        self.visual_eval_text = "0.00"
        self.play_server_mode = False
        self.human_color = chess.WHITE
        self.engine_thinking = False
        self.remote = RemoteStockfish()
        self.sound_enabled = True
        self.sound_volume = 0.55
        self.sound_effects = {}
        self.setup_sounds()
        self.check_reaction_text = ""
        self.check_reaction_until = 0.0
        self.last_reaction_fen = None
        self.bridge = Bridge()
        self.review_rows = []
        self.review_cancel = False
        self.retry_mode=False
        self.retry_row=None
        self.retry_attempts=0
        self.syzygy_path=""
        self.syzygy=None
        self.build_ui()
        self.bridge.position_done.connect(self.on_position_done)
        self.bridge.review_progress.connect(self.on_review_progress)
        self.bridge.review_done.connect(self.on_review_done)
        self.bridge.failed.connect(self.on_engine_error)
        self.statusBar().showMessage("Ready — connect to Stockfish on the Raspberry Pi")

    def build_ui(self):
        root=QWidget(); self.setCentralWidget(root)
        outer=QVBoxLayout(root)

        header=QHBoxLayout()
        title=QLabel("Stockfish Pi Chess")
        title.setObjectName("AppTitle")
        subtitle=QLabel("Raspberry Pi analysis workstation")
        subtitle.setObjectName("AppSubtitle")
        header.addWidget(title)
        header.addSpacing(12)
        header.addWidget(subtitle)
        header.addStretch()
        outer.addLayout(header)

        top=QHBoxLayout()
        self.command=QLineEdit("ssh -T pi@raspberrypi.local /usr/games/stockfish")
        self.command.setPlaceholderText("e.g. ssh -T user@pi-ip /usr/games/stockfish")
        connect=QPushButton("Connect Stockfish"); connect.clicked.connect(self.connect_engine)
        top.addWidget(QLabel("Engine command:")); top.addWidget(self.command,1); top.addWidget(connect)
        outer.addLayout(top)

        engine_opts=QHBoxLayout()
        engine_opts.addWidget(QLabel("Stockfish Threads:"))
        self.threads_spin=QSpinBox()
        self.threads_spin.setRange(1, 32)
        self.threads_spin.setValue(4)
        self.threads_spin.setToolTip("Number of Stockfish search threads on the Raspberry Pi")
        engine_opts.addWidget(self.threads_spin)

        engine_opts.addWidget(QLabel("Hash (MB):"))
        self.hash_combo=QComboBox()
        self.hash_combo.addItems(["128", "256", "512", "1024"])
        self.hash_combo.setCurrentText("512")
        self.hash_combo.setToolTip("Stockfish transposition-table memory on the Raspberry Pi")
        engine_opts.addWidget(self.hash_combo)

        apply_engine=QPushButton("Apply Engine Settings")
        apply_engine.clicked.connect(self.apply_engine_settings)
        engine_opts.addWidget(apply_engine)
        engine_opts.addStretch()
        outer.addLayout(engine_opts)

        split=QSplitter(Qt.Horizontal)
        left=QWidget(); ll=QVBoxLayout(left)
        self.board_widget=BoardWidget(self); self.board_widget.move_requested.connect(self.play_move)
        boardrow=QHBoxLayout()
        self.eval_bar=EvaluationBar()
        boardrow.addWidget(self.eval_bar)
        boardrow.addWidget(self.board_widget,1)
        ll.addLayout(boardrow,1)
        boardbuttons=QHBoxLayout()
        for label, fn in [("New Game",self.new_game),("Undo",self.undo),("Flip Board",self.flip),("Load PGN",self.load_pgn),("Save PGN",self.save_pgn)]:
            b=QPushButton(label); b.clicked.connect(fn); boardbuttons.addWidget(b)
        boardbuttons.addWidget(QLabel("Pieces:"))
        self.piece_combo=QComboBox()
        self.piece_combo.addItems(["Classic", "Bold", "Outline", "Compact"])
        self.piece_combo.currentTextChanged.connect(self.change_piece_style)
        boardbuttons.addWidget(self.piece_combo)
        self.sound_btn=QPushButton("🔊 Sound On")
        self.sound_btn.setCheckable(True)
        self.sound_btn.setChecked(True)
        self.sound_btn.clicked.connect(self.toggle_sound)
        boardbuttons.addWidget(self.sound_btn)
        ll.addLayout(boardbuttons)
        split.addWidget(left)

        right=QWidget(); rr=QVBoxLayout(right)
        self.tabs=QTabWidget(); rr.addWidget(self.tabs)

        playtab=QWidget(); pl=QVBoxLayout(playtab)

        serverbox=QGroupBox("Play the Raspberry Pi")
        serverrow=QHBoxLayout(serverbox)
        serverrow.addWidget(QLabel("Level:"))
        self.play_level=QComboBox()
        self.play_level.addItems(["Easy","Medium","Hard"])
        self.play_level.setCurrentText("Medium")
        serverrow.addWidget(self.play_level)
        serverrow.addWidget(QLabel("Move speed:"))
        self.move_speed=QComboBox()
        self.move_speed.addItems(["Normal","Slow","Very Slow"])
        self.move_speed.setCurrentText("Slow")
        self.move_speed.setToolTip("Controls how quickly the server pieces move across the board")
        serverrow.addWidget(self.move_speed)
        serverrow.addWidget(QLabel("You play:"))
        self.play_side=QComboBox()
        self.play_side.addItems(["White","Black"])
        serverrow.addWidget(self.play_side)
        self.play_server_btn=QPushButton("▶ Play Server")
        self.play_server_btn.setObjectName("PlayServerButton")
        self.play_server_btn.clicked.connect(self.toggle_play_server)
        serverrow.addWidget(self.play_server_btn)
        pl.addWidget(serverbox)

        self.play_status=QLabel("Server play is off")
        self.play_status.setObjectName("PlayStatus")
        pl.addWidget(self.play_status)

        self.turn_label=QLabel("White to move"); pl.addWidget(self.turn_label)
        self.moves_list=QListWidget(); pl.addWidget(self.moves_list,1)
        row=QHBoxLayout()
        self.hint_btn=QPushButton("Hint / Best Move"); self.hint_btn.clicked.connect(self.analyse_position)
        self.play_best_btn=QPushButton("Play Best Move"); self.play_best_btn.clicked.connect(self.play_best); self.play_best_btn.setEnabled(False)
        row.addWidget(self.hint_btn); row.addWidget(self.play_best_btn); pl.addLayout(row)
        self.tabs.addTab(playtab,"Game")

        atab=QWidget(); al=QVBoxLayout(atab)
        opts=QHBoxLayout()
        self.analysis_time=QComboBox(); self.analysis_time.addItems(["0.5","1","2","5","10"]); self.analysis_time.setCurrentText("2")
        self.multipv=QSpinBox(); self.multipv.setRange(1,5); self.multipv.setValue(3)
        opts.addWidget(QLabel("Seconds:")); opts.addWidget(self.analysis_time)
        opts.addWidget(QLabel("Top lines:")); opts.addWidget(self.multipv); opts.addStretch()
        al.addLayout(opts)
        self.eval_label=QLabel("Evaluation: —"); self.eval_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        al.addWidget(self.eval_label)
        self.analysis_text=QPlainTextEdit(); self.analysis_text.setReadOnly(True); al.addWidget(self.analysis_text,1)
        ab=QPushButton("Analyse Current Position"); ab.clicked.connect(self.analyse_position); al.addWidget(ab)
        self.tabs.addTab(atab,"Analysis")

        rtab=QWidget(); rl=QVBoxLayout(rtab)
        review_opts=QHBoxLayout()
        self.review_time=QComboBox(); self.review_time.addItems(["0.25","0.5","1","2","5"]); self.review_time.setCurrentText("1")
        review_opts.addWidget(QLabel("Seconds / position:")); review_opts.addWidget(self.review_time)
        self.review_btn=QPushButton("Review Entire Game"); self.review_btn.clicked.connect(self.review_game)
        self.cancel_btn=QPushButton("Cancel"); self.cancel_btn.clicked.connect(self.cancel_review); self.cancel_btn.setEnabled(False)
        review_opts.addWidget(self.review_btn); review_opts.addWidget(self.cancel_btn); review_opts.addStretch()
        rl.addLayout(review_opts)
        self.progress=QProgressBar(); self.progress.setValue(0); rl.addWidget(self.progress)

        self.review_detail=QLabel("Select a reviewed move to see what was played and Stockfish's best move.")
        self.review_detail.setWordWrap(True)
        self.review_detail.setObjectName("ReviewDetail")
        self.review_detail.setMinimumHeight(94)
        self.review_detail.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        rl.addWidget(self.review_detail)

        self.review_list=QListWidget(); self.review_list.setObjectName("ReviewList"); self.review_list.itemClicked.connect(self.review_item_clicked); rl.addWidget(self.review_list,1)
        nav=QHBoxLayout()
        prev=QPushButton("◀ Previous mistake"); prev.clicked.connect(lambda:self.jump_mistake(-1))
        nxt=QPushButton("Next mistake ▶"); nxt.clicked.connect(lambda:self.jump_mistake(1))
        nav.addWidget(prev); nav.addWidget(nxt)
        self.retry_btn=QPushButton("🎯 Retry Selected Mistake"); self.retry_btn.clicked.connect(self.retry_selected_mistake)
        nav.addWidget(self.retry_btn); rl.addLayout(nav)
        self.retry_status=QLabel("Training: select a mistake, then press Retry Selected Mistake.")
        self.retry_status.setWordWrap(True); rl.addWidget(self.retry_status)
        self.graph=EvalGraph(self); rl.addWidget(self.graph)
        self.tabs.addTab(rtab,"Game Review")

        otab=QWidget(); ol=QVBoxLayout(otab)
        self.opening_label=QLabel("Opening: Starting position"); self.opening_label.setWordWrap(True)
        self.opening_label.setStyleSheet("font-size: 15px; font-weight: 600;"); ol.addWidget(self.opening_label)
        self.opening_text=QPlainTextEdit(); self.opening_text.setReadOnly(True); ol.addWidget(self.opening_text,1)
        ob=QPushButton("Refresh Opening Explorer"); ob.clicked.connect(self.update_opening_explorer); ol.addWidget(ob)
        ol.addWidget(QLabel("Syzygy tablebases (optional local folder):"))
        syzrow=QHBoxLayout(); self.syzygy_edit=QLineEdit(); self.syzygy_edit.setPlaceholderText("Choose a folder containing .rtbw/.rtbz files")
        syzbtn=QPushButton("Choose Folder"); syzbtn.clicked.connect(self.choose_syzygy_folder)
        probe=QPushButton("Probe Current Position"); probe.clicked.connect(self.probe_syzygy)
        syzrow.addWidget(self.syzygy_edit,1); syzrow.addWidget(syzbtn); syzrow.addWidget(probe); ol.addLayout(syzrow)
        self.syzygy_result=QLabel("Syzygy: not configured"); self.syzygy_result.setWordWrap(True); ol.addWidget(self.syzygy_result)
        self.tabs.addTab(otab,"Opening / Endgame")

        split.addWidget(right); split.setSizes([720,500])
        outer.addWidget(split,1)

    def connect_engine(self):
        cmd=self.command.text().strip()
        if not cmd: return
        self.statusBar().showMessage("Connecting…")
        threads=self.threads_spin.value()
        hash_mb=int(self.hash_combo.currentText())
        def work():
            try:
                name=self.remote.connect(cmd)
                applied=self.remote.configure(threads, hash_mb)
                self.bridge.position_done.emit(("connected",name,applied))
            except Exception as e: self.bridge.failed.emit(str(e))
        threading.Thread(target=work,daemon=True).start()

    def apply_engine_settings(self):
        if not self.remote.engine:
            QMessageBox.warning(self,"Stockfish","Connect to Stockfish first.")
            return
        threads=self.threads_spin.value()
        hash_mb=int(self.hash_combo.currentText())
        self.statusBar().showMessage("Applying Stockfish settings…")
        def work():
            try:
                applied=self.remote.configure(threads, hash_mb)
                self.bridge.position_done.emit(("configured",applied))
            except Exception as e:
                self.bridge.failed.emit(str(e))
        threading.Thread(target=work,daemon=True).start()

    def update_eval_bar(self, score):
        """Update the visual evaluation bar from a python-chess PovScore/Score or numeric cp."""
        try:
            if isinstance(score, (int, float)):
                cp=int(score)
                label=f"{cp/100:+.2f}"
            else:
                white=score.white() if hasattr(score, "white") else score
                mate=white.mate() if hasattr(white, "mate") else None
                if mate is not None:
                    cp=1500 if mate > 0 else -1500
                    label=f"M{abs(mate)}" if mate > 0 else f"-M{abs(mate)}"
                else:
                    cp=white.score(mate_score=100000) if hasattr(white, "score") else 0
                    cp=0 if cp is None else int(cp)
                    label=f"{cp/100:+.2f}"
            self.visual_eval_cp=cp
            self.visual_eval_text=label
            if hasattr(self, "eval_bar"):
                self.eval_bar.set_eval(cp,label)
        except Exception:
            pass

    def new_game(self):
        self.play_server_mode=False
        self.engine_thinking=False
        if hasattr(self,"play_server_btn"):
            self.play_server_btn.setText("▶ Play Server")
            self.play_side.setEnabled(True)
            self.play_level.setEnabled(True)
            self.play_status.setText("Server play is off")
        self.board=chess.Board(); self.game_start_fen=chess.STARTING_FEN; self.game_moves=[]
        self.loaded_headers=chess.pgn.Headers(); self.review_rows=[]; self.board_widget.arrow=None
        self.board_widget.review_played_arrow=None
        self.board_widget.review_classification=None
        if hasattr(self,"eval_bar"): self.eval_bar.set_eval(0,"0.00")
        self.retry_mode=False; self.retry_row=None
        self.refresh()

    def refresh(self):
        # Detect check/checkmate only after the new board position is committed.
        current_fen=self.board.fen()
        if current_fen != self.last_reaction_fen:
            self.last_reaction_fen=current_fen
            if self.board.is_checkmate():
                self._show_check_reaction("CHECKMATE",1.8)
                if self.sound_enabled:
                    self._reaction_sound("checkmate")
            elif self.board.is_check():
                self._show_check_reaction("CHECK",1.1)
                if self.sound_enabled:
                    self._reaction_sound("check")
        self.board_widget.selected=None; self.board_widget.legal_targets.clear(); self.board_widget.update()
        self.moves_list.clear()
        b=chess.Board(self.game_start_fen)
        sans=[]
        for i,m in enumerate(self.game_moves):
            try: san=b.san(m)
            except Exception: san=m.uci()
            sans.append(san); b.push(m)
        for i in range(0,len(sans),2):
            text=f"{i//2+1}. {sans[i]}"
            if i+1<len(sans): text += f"   {sans[i+1]}"
            self.moves_list.addItem(text)
        self.moves_list.scrollToBottom()
        self.turn_label.setText(("White" if self.board.turn else "Black")+" to move" + (" — CHECK" if self.board.is_check() else ""))
        if self.board.is_game_over():
            self.turn_label.setText(f"Game over: {self.board.outcome()}")
        self.graph.update()
        self.update_opening_explorer()

    def play_move(self, move):
        # Retry-Mistake trainer intercepts board moves without altering the saved game.
        if self.retry_mode and self.retry_row is not None:
            if move not in self.board.legal_moves:
                return
            self.retry_attempts += 1
            best=self.retry_row.bestmove or ""
            if move.uci()==best:
                try: san=self.board.san(move)
                except Exception: san=move.uci()
                self.retry_status.setText(f"✓ Correct — {san} is Stockfish's best move. Attempts: {self.retry_attempts}")
                self.board_widget.arrow=best
                self.board_widget.review_played_arrow=None
                self.retry_mode=False
                self.sound_for_completed_move(False)
                self.board_widget.update()
            else:
                try: san=self.board.san(move)
                except Exception: san=move.uci()
                self.retry_status.setText(f"Not quite — {san} is not the best move. Try again. Attempt {self.retry_attempts}.")
                self.board_widget.arrow=None
                self.board_widget.update()
            return

        # Board clicks are human moves. During server play, animate the human
        # move too, using the same Move Speed selector as Stockfish.
        if self.board_widget.anim_timer.isActive():
            return
        if self.play_server_mode:
            if self.engine_thinking or self.board.turn != self.human_color:
                return
        if move not in self.board.legal_moves:
            return

        if self.play_server_mode:
            speed_ms={"Normal":300, "Slow":600, "Very Slow":950}.get(
                self.move_speed.currentText(),600
            )
            try:
                san=self.board.san(move)
            except Exception:
                san=move.uci()
            self.play_status.setText(f"You play {san}…")

            def finish_human_move(animated_move):
                if not self.play_server_mode:
                    return
                if animated_move not in self.board.legal_moves:
                    return
                was_capture=self.board.is_capture(animated_move)
                self.board.push(animated_move)
                self.game_moves.append(animated_move)
                self.board_widget.arrow=None
                self.board_widget.review_played_arrow=None
                self.board_widget.review_classification=None
                self.play_best_btn.setEnabled(False)
                self.refresh()
                self.sound_for_completed_move(was_capture)
                self.auto_update_evaluation()
                if self.board.is_game_over():
                    self.play_status.setText(f"Game over — {self.board.outcome()}")
                else:
                    self.request_server_move()

            self.board_widget.animate_move(move, finish_human_move, speed_ms)
            return

        # Normal analysis/free-play mode remains immediate.
        was_capture=self.board.is_capture(move)
        self.board.push(move)
        self.game_moves.append(move)
        self.board_widget.arrow=None
        self.board_widget.review_played_arrow=None
        self.board_widget.review_classification=None
        self.play_best_btn.setEnabled(False)
        self.refresh()
        self.sound_for_completed_move(was_capture)
        self.auto_update_evaluation()

    def setup_sounds(self):
        # Exact sound mechanism used by the uploaded Pikafish v26.1 GUI.
        self.sound_q=queue.Queue()
        self.sound_path=self._prepare_move_sound()
        self.check_sound_path=self._prepare_reaction_sound("check")
        self.checkmate_sound_path=self._prepare_reaction_sound("checkmate")
        threading.Thread(target=self._sound_worker, daemon=True).start()

    def _prepare_move_sound(self):
        """Create the move sound once and return its path.

        A short silent pre-roll is included before the click.  On some Windows
        audio devices the first few milliseconds are lost while the output
        device wakes up; the pre-roll absorbs that delay so the first move is
        audible too.
        """
        try:
            # Use a new filename so an older cached WAV is not reused.
            path = os.path.join(tempfile.gettempdir(), "pikafish_move_v7.wav")
            if not os.path.exists(path):
                rate = 22050
                pre_roll = 0.090      # lets a sleeping Windows audio endpoint wake up
                click_duration = 0.075
                tail = 0.015
                pre_n = int(rate * pre_roll)
                click_n = int(rate * click_duration)
                tail_n = int(rate * tail)
                samples = [0] * pre_n
                for i in range(click_n):
                    t = i / rate
                    env = math.exp(-42 * t)
                    val = (math.sin(2*math.pi*620*t) + 0.45*math.sin(2*math.pi*930*t)) * env
                    samples.append(max(-32767, min(32767, int(val * 12500))))
                samples.extend([0] * tail_n)
                with wave.open(path, "wb") as wf:
                    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate)
                    wf.writeframes(b"".join(struct.pack("<h", x) for x in samples))
            return path
        except Exception:
            return None

    def _prepare_reaction_sound(self, kind):
        """Create check/checkmate WAVs for the same proven winsound path."""
        try:
            path=os.path.join(tempfile.gettempdir(),f"stockfish_{kind}_v14.wav")
            if not os.path.exists(path):
                rate=22050
                pre_roll=0.090
                tail=0.030
                if kind=="checkmate":
                    notes=[(820,0.10),(610,0.12),(390,0.18)]
                else:
                    notes=[(880,0.09),(1120,0.12)]
                samples=[0]*int(rate*pre_roll)
                for freq,duration in notes:
                    n=int(rate*duration)
                    for i in range(n):
                        t=i/rate
                        env=math.exp(-14*t)
                        val=(math.sin(2*math.pi*freq*t)+0.25*math.sin(2*math.pi*(freq*1.5)*t))*env
                        samples.append(max(-32767,min(32767,int(val*11000))))
                    samples.extend([0]*int(rate*0.025))
                samples.extend([0]*int(rate*tail))
                with wave.open(path,"wb") as wf:
                    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate)
                    wf.writeframes(b"".join(struct.pack("<h",x) for x in samples))
            return path
        except Exception:
            return None

    def _sound_worker(self):
        """Play queued WAV files one at a time using the proven Pikafish method."""
        while True:
            sound_path=self.sound_q.get()
            try:
                if os.name == "nt" and sound_path:
                    import winsound
                    winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_SYNC | winsound.SND_NODEFAULT)
                else:
                    QApplication.beep()
            except Exception:
                pass
            finally:
                self.sound_q.task_done()

    def play_move_sound(self):
        """Queue the exact Pikafish move click."""
        if self.sound_path:
            self.sound_q.put_nowait(self.sound_path)

    def toggle_sound(self, checked):
        self.sound_enabled=bool(checked)
        self.sound_btn.setText("🔊 Sound On" if self.sound_enabled else "🔇 Sound Off")
        if self.sound_enabled:
            self.play_move_sound()

    def play_chess_sound(self, kind="move"):
        if self.sound_enabled:
            self.play_move_sound()

    def _reaction_sound(self, kind):
        path=self.checkmate_sound_path if kind=="checkmate" else self.check_sound_path
        if path:
            self.sound_q.put_nowait(path)

    def _show_check_reaction(self,text,seconds):
        self.check_reaction_text=text
        self.check_reaction_until=time.monotonic()+seconds
        self.board_widget.update()
        QTimer.singleShot(int(seconds*1000)+50,self.board_widget.update)

    def sound_for_completed_move(self, was_capture=False):
        if self.sound_enabled:
            self.play_move_sound()

    def auto_update_evaluation(self):
        """Refresh the left evaluation bar after a completed move."""
        if not self.remote.engine or self.board.is_game_over():
            return
        board=self.board.copy()
        # Keep this deliberately short so server play remains responsive.
        def work():
            try:
                infos=self.remote.analyse(board,0.20,1)
                if isinstance(infos,list):
                    info=infos[0] if infos else {}
                else:
                    info=infos
                score=info.get("score") if isinstance(info,dict) else None
                self.bridge.position_done.emit(("auto_eval",board.fen(),score))
            except Exception as e:
                # Auto-evaluation is optional; do not interrupt a game if it fails.
                pass
        threading.Thread(target=work,daemon=True).start()

    def toggle_play_server(self):
        if self.play_server_mode:
            self.play_server_mode=False
            self.engine_thinking=False
            self.play_server_btn.setText("▶ Play Server")
            self.play_status.setText("Server play is off")
            self.play_side.setEnabled(True)
            self.play_level.setEnabled(True)
            self.statusBar().showMessage("Server play stopped")
            return

        if not self.remote.engine:
            QMessageBox.warning(self,"Stockfish","Connect to Stockfish first.")
            return

        # Starting Play Server begins a fresh game so the human/engine sides
        # are always unambiguous.
        self.new_game()
        self.play_server_mode=True
        self.human_color = chess.WHITE if self.play_side.currentText()=="White" else chess.BLACK
        self.play_server_btn.setText("■ Stop Server Game")
        self.play_side.setEnabled(False)
        self.play_level.setEnabled(False)
        level=self.play_level.currentText()
        side="White" if self.human_color==chess.WHITE else "Black"
        self.play_status.setText(f"Playing Stockfish — {level} — You are {side}")
        self.statusBar().showMessage(f"Server game started: {level}, you play {side}")
        self.refresh()

        # If the human chose Black, Stockfish makes the first move.
        if self.human_color == chess.BLACK:
            self.request_server_move()

    def request_server_move(self):
        if not self.play_server_mode or self.board.is_game_over():
            return
        if self.board.turn == self.human_color:
            return
        if self.engine_thinking:
            return
        if not self.remote.engine:
            self.play_server_mode=False
            self.play_server_btn.setText("▶ Play Server")
            self.play_status.setText("Server disconnected")
            return

        board=self.board.copy()
        level=self.play_level.currentText()
        self.engine_thinking=True
        self.play_status.setText(f"Stockfish is thinking… ({level})")
        self.statusBar().showMessage(f"Stockfish is thinking — {level}")
        def work():
            try:
                move=self.remote.play(board,level)
                self.bridge.position_done.emit(("server_move",board.fen(),move,level))
            except Exception as e:
                self.bridge.failed.emit(str(e))
        threading.Thread(target=work,daemon=True).start()

    def apply_server_move(self, move, level):
        self.engine_thinking=False
        if not self.play_server_mode:
            return
        if move not in self.board.legal_moves:
            self.play_status.setText("Server returned an invalid/stale move")
            return
        try:
            san=self.board.san(move)
        except Exception:
            san=move.uci()

        speed_ms={"Normal":300, "Slow":600, "Very Slow":950}.get(self.move_speed.currentText(),600)
        self.play_status.setText(f"Stockfish plays {san}…")

        def finish_server_move(animated_move):
            if not self.play_server_mode:
                return
            if animated_move not in self.board.legal_moves:
                return
            was_capture=self.board.is_capture(animated_move)
            self.board.push(animated_move)
            self.game_moves.append(animated_move)
            self.board_widget.arrow=None
            self.board_widget.review_played_arrow=None
            self.board_widget.review_classification=None
            self.refresh()
            self.sound_for_completed_move(was_capture)
            self.auto_update_evaluation()
            side="White" if self.human_color==chess.WHITE else "Black"
            if self.board.is_game_over():
                self.play_status.setText(f"Game over — {self.board.outcome()}")
            else:
                self.play_status.setText(f"Your move — {side} — Stockfish {level}")
            self.statusBar().showMessage(f"Stockfish played {san}")

        self.board_widget.animate_move(move, finish_server_move, speed_ms)

    def undo(self):
        if self.board.move_stack:
            self.board.pop()
            if self.game_moves: self.game_moves.pop()
            self.board_widget.arrow=None; self.board_widget.review_played_arrow=None; self.board_widget.review_classification=None; self.refresh()

    def change_piece_style(self, style):
        self.piece_style = style
        self.board_widget.update()

    def flip(self):
        self.flipped=not self.flipped; self.board_widget.update()

    def analyse_position(self):
        if not self.remote.engine:
            QMessageBox.warning(self,"Stockfish","Connect to Stockfish first."); return
        board=self.board.copy()
        seconds=float(self.analysis_time.currentText()); mpv=self.multipv.value()
        self.analysis_text.setPlainText("Analysing…"); self.play_best_btn.setEnabled(False)
        def work():
            try:
                infos=self.remote.analyse(board,seconds,mpv)
                self.bridge.position_done.emit(("analysis",board,infos))
            except Exception as e: self.bridge.failed.emit(str(e))
        threading.Thread(target=work,daemon=True).start()

    def on_position_done(self, payload):
        if payload[0]=="connected":
            applied=payload[2] if len(payload)>2 else {}
            detail=", ".join(f"{k}={v}" for k,v in applied.items())
            self.statusBar().showMessage(f"Connected: {payload[1]}" + (f" — {detail}" if detail else ""))
            return
        if payload[0]=="configured":
            applied=payload[1]
            detail=", ".join(f"{k}={v}" for k,v in applied.items())
            self.statusBar().showMessage("Stockfish settings applied" + (f": {detail}" if detail else ""))
            return
        if payload[0]=="server_move":
            _,fen,move,level=payload
            # Ignore a result if the board changed while Stockfish was thinking.
            if self.board.fen()==fen:
                self.apply_server_move(move,level)
            else:
                self.engine_thinking=False
            return
        if payload[0]=="auto_eval":
            _,fen,score=payload
            # Only display the result if it still belongs to the current position.
            if self.board.fen()==fen and score is not None:
                self.update_eval_bar(score)
            return
        _,board,infos=payload
        if isinstance(infos,dict): infos=[infos]
        lines=[]; best=None
        for n,info in enumerate(infos,1):
            sc=info.get("score"); pv=info.get("pv",[])
            san=[]
            tb=board.copy()
            for mv in pv[:10]:
                try: san.append(tb.san(mv)); tb.push(mv)
                except Exception: break
            if n==1 and pv: best=pv[0]
            lines.append(f"{n}. {score_text(sc)}   {' '.join(san)}")
        self.eval_label.setText("Evaluation: "+(score_text(infos[0].get("score")) if infos else "—"))
        if infos and infos[0].get("score") is not None:
            self.update_eval_bar(infos[0].get("score"))
        self.analysis_text.setPlainText("\n\n".join(lines))
        self.best_move=best
        candidates=[]
        for info in infos[1:3]:
            pv=info.get("pv",[])
            if pv: candidates.append(pv[0].uci())
        self.board_widget.candidate_arrows=candidates
        if best:
            self.board_widget.arrow=best.uci(); self.board_widget.update(); self.play_best_btn.setEnabled(True)
        self.tabs.setCurrentIndex(1)

    def play_best(self):
        if getattr(self,"best_move",None) in self.board.legal_moves:
            self.play_move(self.best_move)

    def load_pgn(self):
        fn,_=QFileDialog.getOpenFileName(self,"Load PGN","","PGN files (*.pgn);;All files (*.*)")
        if not fn: return
        try:
            with open(fn,encoding="utf-8-sig") as f: game=chess.pgn.read_game(f)
            if not game: raise ValueError("No game found in PGN.")
            self.loaded_headers=game.headers
            self.board=game.board(); self.game_start_fen=self.board.fen(); self.game_moves=[]
            for mv in game.mainline_moves():
                self.board.push(mv); self.game_moves.append(mv)
            self.review_rows=[]; self.review_list.clear(); self.board_widget.arrow=None; self.board_widget.review_played_arrow=None; self.board_widget.review_classification=None; self.refresh()
            self.statusBar().showMessage(f"Loaded {Path(fn).name} — {len(self.game_moves)} plies")
        except Exception as e: QMessageBox.critical(self,"Load PGN",str(e))

    def save_pgn(self):
        fn,_=QFileDialog.getSaveFileName(self,"Save PGN","game.pgn","PGN files (*.pgn)")
        if not fn:return
        if not fn.lower().endswith(".pgn"): fn+=".pgn"
        try:
            game=chess.pgn.Game()
            for k,v in self.loaded_headers.items(): game.headers[k]=v
            if self.game_start_fen != chess.STARTING_FEN:
                game.setup(chess.Board(self.game_start_fen))
            node=game
            review_by_ply={r.ply:r for r in self.review_rows}
            b=chess.Board(self.game_start_fen)
            for ply,mv in enumerate(self.game_moves,1):
                node=node.add_variation(mv)
                r=review_by_ply.get(ply)
                if r:
                    node.comment=f"{r.classification}; eval {r.score_after/100:+.2f}" if r.score_after is not None and abs(r.score_after)<99999 else r.classification
                    if r.bestmove: node.comment += f"; best {r.bestmove}"
                    if r.pv: node.comment += f"; PV {r.pv}"
                b.push(mv)
            game.headers["Result"]=self.board.result(claim_draw=True) if self.board.is_game_over(claim_draw=True) else "*"
            with open(fn,"w",encoding="utf8") as f: print(game,file=f,end="\n\n")
            self.statusBar().showMessage("PGN saved"+(" with Stockfish review comments" if self.review_rows else ""))
        except Exception as e: QMessageBox.critical(self,"Save PGN",str(e))

    def review_game(self):
        if not self.remote.engine:
            QMessageBox.warning(self,"Stockfish","Connect to Stockfish first."); return
        if not self.game_moves:
            QMessageBox.information(self,"Review","There are no moves to review."); return
        self.review_cancel=False; self.review_rows=[]; self.review_list.clear(); self.review_detail.setText("Reviewing game…")
        self.review_btn.setEnabled(False); self.cancel_btn.setEnabled(True)
        self.progress.setMaximum(len(self.game_moves)); self.progress.setValue(0)
        moves=list(self.game_moves); start=self.game_start_fen; sec=float(self.review_time.currentText())
        def work():
            try:
                b=chess.Board(start); rows=[]
                for ply,mv in enumerate(moves,1):
                    if self.review_cancel: break
                    mover=b.turn
                    before=self.remote.analyse(b,sec,1)
                    if isinstance(before,list): before=before[0]
                    sb=white_pov_cp(before.get("score"))
                    pv=before.get("pv",[])
                    best=pv[0].uci() if pv else ""
                    san=b.san(mv)
                    pv_san=[]; tb=b.copy()
                    for x in pv[:8]:
                        try: pv_san.append(tb.san(x)); tb.push(x)
                        except Exception: break
                    b.push(mv)
                    after=self.remote.analyse(b,sec,1)
                    if isinstance(after,list): after=after[0]
                    sa=white_pov_cp(after.get("score"))
                    loss=None
                    if sb is not None and sa is not None:
                        # Loss from the mover's perspective.
                        loss=(sb-sa) if mover==chess.WHITE else (sa-sb)
                        loss=max(0,loss)
                    row=ReviewRow(ply,san,mv.uci(),mover,sb,sa,loss,classify(loss),best," ".join(pv_san),b.fen())
                    rows.append(row)
                    self.bridge.review_progress.emit(ply,len(moves),f"{ply}. {san} — {row.classification}")
                self.bridge.review_done.emit(rows)
            except Exception as e: self.bridge.failed.emit(str(e))
        threading.Thread(target=work,daemon=True).start()

    def cancel_review(self):
        self.review_cancel=True; self.statusBar().showMessage("Cancelling review after current position…")

    def on_review_progress(self,n,total,text):
        self.progress.setMaximum(total); self.progress.setValue(n); self.statusBar().showMessage(f"Analysing {n}/{total}: {text}")

    def on_review_done(self,rows):
        self.review_rows=rows; self.review_list.clear()
        for r in rows:
            ev="?" if r.score_after is None else ("Mate" if abs(r.score_after)>=99999 else f"{r.score_after/100:+.2f}")
            move_no=(r.ply+1)//2
            side="White" if r.ply%2 else "Black"
            marker={"Blunder":"✖","Mistake":"!","Inaccuracy":"?!","Best/Good":"✓"}.get(r.classification,"•")
            item=QListWidgetItem(f"{marker}  {move_no}.{' ' if side=='White' else '..'} {side:<5}  PLAYED: {r.san:<8}   Eval {ev:>6}   {r.classification}")
            item.setData(Qt.UserRole,r.ply)
            self.review_list.addItem(item)
        self.review_btn.setEnabled(True); self.cancel_btn.setEnabled(False); self.graph.update()
        self.statusBar().showMessage(("Review cancelled" if self.review_cancel else "Game review complete"))
        self.tabs.setCurrentIndex(2)

    def review_item_clicked(self,item):
        ply=item.data(Qt.UserRole)
        row=next((r for r in self.review_rows if r.ply==ply),None)
        if not row:return

        # Show the position BEFORE the reviewed move. This makes the blue arrow
        # unambiguously mean "Stockfish recommends this move now".
        b=chess.Board(self.game_start_fen)
        for mv in self.game_moves[:max(0,ply-1)]:
            b.push(mv)
        self.board=b

        actual_move=self.game_moves[ply-1] if 0 < ply <= len(self.game_moves) else None
        best_uci=row.bestmove or ""
        best_move=None
        try:
            if len(best_uci)>=4:
                best_move=chess.Move.from_uci(best_uci)
        except Exception:
            best_move=None

        self.board_widget.arrow=best_uci if len(best_uci)>=4 else None
        self.board_widget.candidate_arrows=[]
        # For anything that wasn't Best/Good, show the move actually played as a
        # dashed warm-colour arrow alongside the solid blue BEST arrow.
        if row.classification in ("Inaccuracy","Mistake","Blunder") and actual_move is not None:
            self.board_widget.review_played_arrow=actual_move.uci()
            self.board_widget.review_classification=row.classification
        else:
            self.board_widget.review_played_arrow=None
            self.board_widget.review_classification=None

        move_no=(ply+1)//2
        side="White" if ply%2 else "Black"
        best_san=best_uci or "?"
        if best_move is not None:
            try:
                best_san=b.san(best_move)
            except Exception:
                pass

        played_san=row.san
        same = bool(actual_move is not None and best_move is not None and actual_move == best_move)
        if same:
            verdict="✓ PLAYED MOVE = BEST MOVE"
        elif row.classification=="Blunder":
            verdict="RED DASHED = PLAYED BLUNDER   |   BLUE = BEST MOVE"
        elif row.classification in ("Mistake","Inaccuracy"):
            verdict="ORANGE DASHED = PLAYED MOVE   |   BLUE = BEST MOVE"
        else:
            verdict="BLUE = STOCKFISH BEST MOVE"

        self.review_detail.setText(
            f"Move {move_no} — {side} — {row.classification}\n"
            f"PLAYED:  {played_san}    ({row.uci})\n"
            f"BEST:    {best_san}    ({best_uci or '?'})\n"
            f"{verdict}"
        )

        self.eval_label.setText(
            "Evaluation after played move: "+
            ("?" if row.score_after is None else
             (f"{row.score_after/100:+.2f}" if abs(row.score_after)<99999 else "Mate"))
        )
        self.analysis_text.setPlainText(
            f"REVIEW — Move {move_no} ({side})\n"
            f"Move played: {played_san} ({row.uci})\n"
            f"Stockfish best: {best_san} ({best_uci or '?'})\n"
            f"Classification: {row.classification}\n"
            f"Centipawn loss: {row.loss if row.loss is not None else '?'}\n"
            f"Suggested line: {row.pv or '?'}\n\n"
            f"Board position shown is BEFORE the move.\n"
            f"The BLUE ARROW clearly marks Stockfish's best move."
        )
        self.board_widget.update()

    def retry_selected_mistake(self):
        item=self.review_list.currentItem()
        if not item:
            QMessageBox.information(self,"Retry Mistake","Select a reviewed mistake first."); return
        ply=item.data(Qt.UserRole)
        row=next((r for r in self.review_rows if r.ply==ply),None)
        if not row or row.classification not in ("Inaccuracy","Mistake","Blunder"):
            QMessageBox.information(self,"Retry Mistake","Select an Inaccuracy, Mistake or Blunder."); return
        b=chess.Board(self.game_start_fen)
        for mv in self.game_moves[:max(0,ply-1)]: b.push(mv)
        self.board=b; self.retry_mode=True; self.retry_row=row; self.retry_attempts=0
        self.board_widget.arrow=None; self.board_widget.review_played_arrow=None; self.board_widget.candidate_arrows=[]
        self.board_widget.review_classification=None
        move_no=(ply+1)//2; side="White" if ply%2 else "Black"
        self.retry_status.setText(f"🎯 Retry Move {move_no} ({side}) — find a better move. The answer is hidden.")
        self.refresh(); self.tabs.setCurrentIndex(0)

    def update_opening_explorer(self):
        if not hasattr(self,"opening_label"): return
        # Compact built-in explorer: common named openings and continuations.
        book={
          "":("Starting position",["e4","d4","Nf3","c4"]),
          "e4":("King's Pawn Opening",["e5","c5","e6","c6"]),
          "e4 e5":("Open Game",["Nf3","Nc3","Bc4"]),
          "e4 e5 Nf3 Nc6 Bb5":("Ruy Lopez",["a6","Nf6"]),
          "e4 e5 Nf3 Nc6 Bc4":("Italian Game",["Bc5","Nf6"]),
          "e4 c5":("Sicilian Defence",["Nf3","Nc3","c3"]),
          "e4 e6":("French Defence",["d4","Nc3","Nd2"]),
          "e4 c6":("Caro-Kann Defence",["d4","Nc3"]),
          "d4 d5 c4":("Queen's Gambit",["e6","c6","dxc4"]),
          "d4 Nf6 c4 g6":("King's Indian Defence",["Nc3","Nf3"]),
          "d4 Nf6 c4 e6 Nc3 Bb4":("Nimzo-Indian Defence",["e3","Qc2"]),
          "c4":("English Opening",["e5","Nf6","c5"]),
          "Nf3":("Réti Opening",["d5","Nf6","c5"]),
        }
        b=chess.Board(self.game_start_fen); sans=[]
        for mv in self.game_moves:
            try: sans.append(b.san(mv)); b.push(mv)
            except Exception: break
        # If reviewing/training a historical position, derive its line from its move stack where possible.
        seq=" ".join(sans)
        best_key=""
        for k in book:
            if k and (seq==k or seq.startswith(k+" ")) and len(k)>len(best_key): best_key=k
        name,nexts=book.get(best_key,book[""])
        self.opening_label.setText(f"Opening: {name}")
        played=seq if seq else "(no moves yet)"
        self.opening_text.setPlainText(f"Moves: {played}\n\nTypical continuations from this opening family:\n  " + "   ".join(nexts) + "\n\nThis built-in explorer is a quick reference, not an online statistics database.")

    def choose_syzygy_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"Choose Syzygy tablebase folder",self.syzygy_path or "")
        if not folder:return
        try:
            if self.syzygy: self.syzygy.close()
        except Exception: pass
        try:
            self.syzygy=chess.syzygy.open_tablebase(folder); self.syzygy_path=folder; self.syzygy_edit.setText(folder)
            self.syzygy_result.setText("Syzygy loaded. Positions covered depend on the tablebase files in this folder.")
        except Exception as e:
            self.syzygy=None; QMessageBox.warning(self,"Syzygy",str(e))

    def probe_syzygy(self):
        if not self.syzygy:
            QMessageBox.information(self,"Syzygy","Choose a Syzygy tablebase folder first."); return
        pieces=len(self.board.piece_map())
        try:
            wdl=self.syzygy.probe_wdl(self.board)
            meanings={2:"Win",1:"Cursed win",0:"Draw",-1:"Blessed loss",-2:"Loss"}
            text=f"Syzygy exact result: {meanings.get(wdl,str(wdl))} for side to move — {pieces} pieces."
            try:
                dtz=self.syzygy.probe_dtz(self.board); text+=f"  DTZ: {dtz}."
            except Exception: pass
            self.syzygy_result.setText(text)
        except Exception as e:
            self.syzygy_result.setText(f"No tablebase result for this position ({pieces} pieces): {e}")

    def jump_mistake(self,direction):
        bad=[i for i,r in enumerate(self.review_rows) if r.classification in ("Mistake","Blunder")]
        if not bad:return
        current=self.review_list.currentRow()
        target = next((i for i in bad if i>current),bad[0]) if direction>0 else next((i for i in reversed(bad) if i<current),bad[-1])
        self.review_list.setCurrentRow(target)
        self.review_item_clicked(self.review_list.item(target))

    def on_engine_error(self,msg):
        self.review_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self.statusBar().showMessage("Engine error")
        QMessageBox.critical(self,"Stockfish / SSH",msg)

    def closeEvent(self,event):
        self.review_cancel=True
        self.remote.close()
        event.accept()

def main():
    app=QApplication(sys.argv)
    app.setApplicationName("Stockfish Chess GUI")
    w=MainWindow(); w.show()
    sys.exit(app.exec())

if __name__=="__main__":
    main()
