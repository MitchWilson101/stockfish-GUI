# Stockfish Pi Chess v25

A Windows chess GUI built around **Play → Review → Understand → Retry**.

Stockfish can run remotely on a Raspberry Pi or other Linux computer over SSH while the graphical interface runs on Windows.

## Features

- Play Stockfish at Easy, Medium or Hard levels
- Remote Stockfish over SSH
- Adjustable Threads and Hash
- Live evaluation bar
- Hint / best move and MultiPV candidate arrows
- PGN load/save and full-game analysis
- Evaluation graph
- Inaccuracy, mistake and blunder review
- BEST vs PLAYED move arrows
- Retry Mistakes training
- Guided Game Replay
- Try Better Move exercises
- Opening recognition/explorer
- Optional local Syzygy endgame tablebases
- Move, check and checkmate sounds
- Multiple piece styles and smooth move animation

## Windows requirements

- Windows 10 or 11
- Python 3
- Network/SSH access to the computer running Stockfish

Double-click `run_windows.cmd`. On first run it creates a local Python virtual environment and installs the packages in `requirements.txt`.

## Stockfish computer / Raspberry Pi

On Debian/Raspberry Pi OS/Ubuntu, Stockfish can usually be installed with:

```bash
sudo apt update
sudo apt install stockfish
```

A common executable path is `/usr/games/stockfish`.

The public GUI starts with this example engine command:

```text
ssh -T pi@raspberrypi.local /usr/games/stockfish
```

Replace the username, hostname/address and Stockfish path with your own. SSH key authentication is recommended. Test the command in Windows Terminal before using it in the GUI.

## Game Review and Guided Replay

Load a PGN and run **Review Entire Game**. Stockfish evaluates each move and records the played move, preferred move, evaluation loss and continuation.

Then use **Play Guided Review** to step through the analysed game with Previous/Next or Auto Play. At positions where a stronger move was available, **Try Better Move** hides the answer and lets you attempt the position yourself without modifying the original PGN.

## Syzygy tablebases

Syzygy is optional. In the Opening / Endgame section, choose a folder containing `.rtbw` and `.rtbz` files. A 3–5 piece collection can provide mathematically solved results for positions containing five pieces or fewer, including both kings.

The rest of the GUI works normally without tablebase files.

## Notes

This is a practical chess playing and training GUI rather than an engine tournament manager. Review classifications are based on engine evaluation changes and are intended as training aids.

## License

MIT — see `LICENSE`.
