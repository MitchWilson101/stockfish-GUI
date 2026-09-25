# Stockfish Pi Chess

A clean Python/PySide6 chess GUI that uses a Raspberry Pi as a dedicated
Stockfish server, with an emphasis on playing, reviewing and learning from
your own games.

## Highlights

- Play Stockfish remotely over SSH
- Easy / Medium / Hard play
- Adjustable Threads and Hash
- Smooth move animation
- Live evaluation and evaluation bar
- Evaluation graph
- MultiPV and top candidate arrows
- Whole-game Stockfish review
- Inaccuracy / Mistake / Blunder classification
- Clear PLAYED vs BEST arrows
- Retry Mistakes training mode
- Previous / next mistake navigation
- PGN load/save
- Lightweight offline opening recognition
- Local Syzygy tablebase probing
- Move, check and checkmate sounds/reactions

## Raspberry Pi setup

On Raspberry Pi OS / Debian:

```bash
sudo apt update
sudo apt install stockfish openssh-server
```

Check the Stockfish path:

```bash
which stockfish
```

A common location is `/usr/games/stockfish`.

## SSH connection

The public version uses this example command:

```text
ssh -T pi@raspberrypi.local /usr/games/stockfish
```

Change the username and hostname/IP to match your Raspberry Pi.

SSH keys are recommended so the GUI can connect without an interactive
password prompt.

Test the command from Windows before using the GUI.

## Windows installation

Install Python 3, then either double-click:

```text
run_windows.cmd
```

or run:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python stockfish_pi_chess.py
```

## Game Review

After playing or loading a PGN, run Game Review and select a move.

- Solid blue arrow = Stockfish best move
- Orange dashed arrow = played Inaccuracy/Mistake
- Red dashed arrow = played Blunder

The position shown is the position before the selected move, making the
played move and Stockfish recommendation directly comparable.

## Retry Mistakes

Select an Inaccuracy, Mistake or Blunder and press **Retry Selected Mistake**.
The answer is hidden and the original position is restored so you can try to
find Stockfish's best move yourself.

## Opening explorer

The included opening explorer is intentionally lightweight and offline. It
recognises a selection of major opening families and shows typical
continuations. It is not a live statistical opening database.

## Syzygy

In the Opening / Endgame tab, choose a local folder containing Syzygy
`.rtbw` / `.rtbz` files. Supported positions can then be probed for exact WDL
and, where available, DTZ results.

## Privacy

This release contains no developer IP address, email address, Windows user
path or SSH password. The Raspberry Pi connection is an example only.

## Project philosophy

Keep the interface focused:

**Play -> Review -> Understand -> Retry**

## Licence

MIT. See `LICENSE`.
