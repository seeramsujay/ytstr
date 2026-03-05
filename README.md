# ytstr - YouTube Streamer

`ytstr` is a command-line tool that allows you to stream YouTube playlists directly in your terminal using `yt-dlp` and `mpv`. It features intelligent caching to `/dev/shm` (RAM) for smooth playback and pre-loading of upcoming tracks.

## Features

- Stream YouTube playlists directly from the terminal.
- Default playlist shuffling (can be disabled).
- Caching of audio files to RAM (`/dev/shm`) for fast access.
- Pre-loads next and previous songs for seamless transitions.
- Simple command-line interface for navigation (`>`, `<`, `q`).

## Prerequisites

Before you can use `ytstr`, you need to have the following installed:

- **Python 3.x**: The script is written in Python.
- **yt-dlp**: A YouTube downloader. You can install it via pip:
  ```bash
  pip install yt-dlp
  ```
  Or refer to its official documentation for other installation methods.
- **mpv**: A free, open-source, and cross-platform media player.
  - On Debian/Ubuntu: `sudo apt install mpv`
  - On Fedora: `sudo dnf install mpv`
  - On Arch Linux: `sudo pacman -S mpv`
  - For other operating systems, refer to the [mpv installation guide](https://mpv.io/installation/).

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/seeramsujay/ytstr.git
   cd ytstr
   ```
2. Ensure `yt-dlp` and `mpv` are installed as per the prerequisites.

## Making `ytstr` Executable and Available in Your Environment

To use `ytstr` seamlessly from any directory, you can make the `ytstr` script executable and add it to your system's PATH.

1.  **Make the script executable:**
    ```bash
    chmod +x ytstr
    ```

2.  **Move the script to a directory in your PATH:**
    You can move it to `/usr/local/bin` (for system-wide access) or `~/.local/bin` (for user-specific access). If `~/.local/bin` is not in your PATH, you'll need to add it.

    For system-wide access (requires sudo):
    ```bash
    sudo mv ytstr /usr/local/bin/
    ```

    For user-specific access:
    ```bash
    mkdir -p ~/.local/bin
    mv ytstr ~/.local/bin/
    ```
    If `~/.local/bin` is not already in your PATH, add the following line to your shell's configuration file (e.g., `~/.bashrc`, `~/.zshrc`, or `~/.profile`):
    ```bash
    export PATH="$HOME/.local/bin:$PATH"
    ```
    After adding, apply the changes by running `source ~/.bashrc` (or your respective config file).

## Usage

To play a YouTube playlist, simply run `ytstr` with the playlist URL as an argument:

```bash
ytstr "YOUR_YOUTUBE_PLAYLIST_URL"
```

By default, the playlist will be shuffled.

### Options

- `--no-shuffle`: Disable playlist shuffling.
  ```bash
  python ytstr.py "YOUR_YOUTUBE_PLAYLIST_URL" --no-shuffle
  ```

### Controls

While the playlist is playing, you can use the following keys:

- `>`: Play the next song in the playlist.
- `<`: Play the previous song in the playlist. If pressed within the first 5 seconds of a song, it goes to the previous song; otherwise, it restarts the current song.
- `q`: Quit the player.

## Caching

`ytstr` uses `/dev/shm` (shared memory, typically RAM) for caching downloaded audio files. This provides very fast access to tracks. The cache is automatically managed:
- The current song, one previous song, and two upcoming songs are kept in the cache.
- Outdated cached files are automatically removed.
- The cache is cleared when the player exits.

## Logging

The script uses Python's `logging` module to provide informational messages and debug output. You can adjust the logging level in the script if needed.

## Contributing

Feel free to fork the repository, make improvements, and submit pull requests.

## License

This project is open-source and available under the [MIT License](LICENSE).
