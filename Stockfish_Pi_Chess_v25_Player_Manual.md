# Stockfish Pi Chess v25 — Player Manual

*A practical guide for Windows players*

## 1. What the program does

Stockfish Pi Chess is a desktop chess program for playing against Stockfish and learning from your games. The chessboard appears on the left, and four tabs on the right organise play, analysis, review and opening/endgame tools.

**Important:** This edition normally runs the Stockfish engine on a separate Raspberry Pi or Linux computer through SSH. The Windows application is the graphical interface. Stockfish is not bundled in the download.

## 2. Installation on Windows

1. Install Python 3 on Windows 10 or 11. Make sure the Python launcher (`py`) is available.
2. Download the GitHub ZIP, extract it to a folder, and open that folder.
3. Double-click **`run_windows.cmd`**.
4. On the first launch, the script creates a `.venv` virtual environment and installs the packages listed in `requirements.txt`. Internet access is needed for the initial installation.
5. Wait for the chess window to appear. Keep the extracted files together.

### Prepare your Stockfish computer

On the Raspberry Pi or other Linux computer, install Stockfish and enable SSH. On Debian/Ubuntu-based systems:

```bash
sudo apt update
sudo apt install stockfish openssh-server
```

Check the engine path with `which stockfish`. A common path is `/usr/games/stockfish`.

The default example in the Windows GUI is:

```text
ssh -T pi@raspberrypi.local /usr/games/stockfish
```

Replace `pi`, `raspberrypi.local` and the engine path with your own details. Test the command in Windows Terminal first. SSH key authentication is recommended so the application can connect without interactive password prompts.

## 3. Getting to know the screen

**Above the board:** Engine command, **Connect Stockfish**, **Stockfish Threads**, **Hash (MB)** and **Apply Engine Settings**.

**Left side:** Chessboard, **Captured Pieces** panel, board controls and appearance/sound controls.

**Right side:** Four tabs:

- **Game** — play against Stockfish and see the move list.
- **Analysis** — examine the current board position.
- **Game Review** — analyse an entire game and practise missed moves.
- **Opening / Endgame** — opening information and optional Syzygy tablebases.

The status bar also displays connection and analysis messages.

## 4. Connect to the engine

1. Enter the correct SSH engine command.
2. Press **Connect Stockfish** and wait for a successful connection.
3. Set **Stockfish Threads** using the separate ▲ and ▼ buttons, or type a number. This determines how many CPU threads the *remote* engine uses.
4. Choose **Hash (MB)**, which controls engine search memory.
5. If you change Threads or Hash after connecting, press **Apply Engine Settings**.

If the connection fails, check that the Pi is on, the network address is correct, SSH works in Windows Terminal, and Stockfish is installed at the specified path.

## 5. Play a chess game

1. Open the **Game** tab.
2. Under **Play the Raspberry Pi**, select **Level**: Easy, Medium or Hard.
3. Choose **Move speed**: Normal, Slow or Very Slow. This changes how quickly the engine's moves are displayed, not the strength setting.
4. Under **You play**, select White or Black.
5. Press **▶ Play Server** to begin playing against the engine.
6. Make moves by selecting a piece on the board and choosing its destination.

The **Game** tab shows whose turn it is and the move list.

**New Game** starts again. **Undo** takes back a move. **Flip Board** changes the viewing direction.

**Hint / Best Move** asks Stockfish to analyse the current position. **Play Best Move** can play the suggested move once one has been calculated.

## 6. Captured Pieces — new in v25

Immediately below the board is a **Captured Pieces** area:

- **Captured by White** shows Black's pieces missing from the current position.
- **Captured by Black** shows White's pieces missing from the current position.

The display updates as you play and when you move through game review positions. A dash means there are no captured pieces to display.

This is a visual record of missing pieces, not a material-score calculation. In unusual positions (for example, after pawn promotion), the display may not represent the complete capture history.

## 7. Board appearance and sound

Below the board:

- **Pieces** lets you choose Classic, Bold, Outline or Compact.
- **🔊 Sound On** toggles game sounds.
- **Flip Board** rotates the board view without changing the position.

## 8. Analyse a position

1. Set up a position by playing moves or loading a PGN.
2. Open **Analysis**.
3. Choose **Seconds** (how long to analyse).
4. Choose **Top lines** (how many candidate continuations to show, up to five).
5. Press **Analyse Current Position**.

The panel shows an engine evaluation and suggested lines. Arrows on the board can help illustrate recommended moves.

**Understanding evaluations:** A positive evaluation generally favours White and a negative evaluation favours Black. A value near zero suggests approximate balance. A displayed mate score means the engine has found a forced mate sequence under its search assumptions. Longer analysis can change the result.

## 9. Load and save PGN games

**PGN** (Portable Game Notation) is a standard text format for chess games.

- Press **Load PGN** to open a saved chess game.
- Press **Save PGN** to save the current game.

Loading a PGN is the easiest way to review a game played elsewhere. Keep the original PGN file if you want an untouched backup.

## 10. Review an entire game

1. Load a PGN or play a game.
2. Open **Game Review**.
3. Choose **Seconds / position**. A longer time can improve analysis but makes the review take longer.
4. Press **Review Entire Game**.
5. Watch the progress bar. Use **Cancel** if necessary.
6. Select a move in the review list to inspect what happened.

The review compares played moves with Stockfish's suggestions. It can identify **Best/Good**, **Inaccuracy**, **Mistake** and **Blunder** categories, and display evaluation changes and a graph.

These are approximate training labels based on the engine's evaluation. They are not official chess ratings, and a move's classification may change with longer analysis.

### Understanding the arrows

The interface distinguishes the move actually played from the engine's recommended move. The principal best-move arrow and other candidate arrows can be displayed alongside the played-move arrow. Look at the accompanying text to confirm which is which.

## 11. Guided Game Replay

After a completed game review:

1. Press **▶ Play Guided Review**.
2. Use **◀ Previous** and **Next ▶** to move through the game.
3. Use **Auto Play** to advance automatically.
4. Read the explanation panel for the move under review.

This is useful for understanding *where* a game changed rather than merely seeing a final score.

### Try Better Move

At a position under review, press **🎯 Try Better Move**. The program lets you attempt an improved move on the board. The training check is based on Stockfish's selected best move; another reasonable move may not be accepted as the exact answer. Your original PGN is not rewritten by this exercise.

## 12. Retry mistakes

In **Game Review**, choose a move classified as a mistake or blunder, then press **🎯 Retry Selected Mistake**. Try to find the better move without simply copying the engine suggestion.

Use **◀ Previous mistake** and **Next mistake ▶** to navigate between mistakes. This is particularly helpful for turning mistakes in your own games into practice positions.

## 13. Opening / Endgame tab

### Opening explorer

The **Opening / Endgame** tab shows opening information for the current position. Press **Refresh Opening Explorer** to update it.

### Syzygy endgame tablebases (optional)

Syzygy files contain exact solutions for supported chess endgames. They are **not included** with the program.

1. Obtain a compatible Syzygy collection of `.rtbw` and `.rtbz` files from a reputable source.
2. Open **Opening / Endgame**.
3. Press **Choose Folder** and select the folder containing those files.
4. Navigate to an endgame position on the board.
5. Press **Probe Current Position**.

For example, a complete 3–5-piece collection covers supported positions with **five or fewer pieces on the board, counting both kings**. If too many pieces remain or the needed files are missing, an exact tablebase result will not be available. The normal Stockfish engine can still analyse the position.

## 14. Troubleshooting

**Nothing happens when connecting:** Check the SSH command in Windows Terminal. Confirm that the remote machine is reachable and Stockfish starts correctly.

**A password prompt or SSH error appears:** Set up SSH key authentication and accept the host key in a normal terminal session before launching the GUI.

**The application does not start:** Run `run_windows.cmd` from the extracted folder and read the error shown in the command window. Check Python 3 and internet access for package installation.

**Analysis seems slow:** Lower Seconds / Seconds per position, reduce Top lines, or check the remote Pi's CPU use and temperature.

**Threads buttons seem to have no effect:** They change the selected value; press **Apply Engine Settings** to send the new setting to a connected engine.

**Syzygy gives no result:** Check the chosen folder, file coverage and total number of pieces.

**Captured pieces seem wrong after promotion:** The panel shows pieces missing relative to the game's starting position; it is not a full capture-event log.

## 15. Suggested first session

Start with a short game on **Easy** or **Medium**. Save the PGN. Then open **Game Review**, choose **1 second / position**, and press **Review Entire Game**. Read the mistakes, use **Play Guided Review** to step through the game, and try **Retry Selected Mistake** on one or two positions.

That gives you the complete learning cycle: **play → analyse → understand → practise**.

---

*Manual for Stockfish Pi Chess v25 (Windows GitHub edition). Some controls require a working remote Stockfish connection. Feature descriptions are based on the v25 source and release files; actual performance depends on your computer, network and Stockfish installation.*
