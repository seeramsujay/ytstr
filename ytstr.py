import shutil
import subprocess
import os
import sys
import threading
import queue
import time
import json # Added for JSON parsing
import logging # Added for logging
import rich # Color coding

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class YouTubePlayer:
    def __init__(self):
        self.playlist_info = [] # Stores dicts of {'url': url, 'title': title}
        self.current_index = -1
        self.player_process = None
        self.cache = {} # Stores paths to downloaded audio files
        self.temp_dir = "/dev/shm/ytstr_cache" # Using RAM for caching
        self.stop_event = threading.Event()
        self.user_input_queue = queue.Queue() # For handling user input in a separate thread

        os.makedirs(self.temp_dir, exist_ok=True)

    def fetch_playlist_urls(self, playlist_url):
        logging.debug(f"Fetching playlist URLs and titles from {playlist_url}...") # Changed to debug
        try:
            command = [
                "yt-dlp",
                "--flat-playlist",
                "--dump-json",
                playlist_url
            ]
            logging.debug(f"Executing yt-dlp command: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True, check=False) # Changed check=True to check=False to capture stderr even on error
            logging.debug(f"yt-dlp stdout: {result.stdout}")
            logging.debug(f"yt-dlp stderr: {result.stderr}") # Explicitly print stderr
            
            if result.returncode != 0:
                logging.error(f"yt-dlp command failed with exit code {result.returncode}. Stderr: {result.stderr}")
                return False

            video_entries = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    try:
                        entry = json.loads(line)
                        video_entries.append(entry)
                        logging.debug(f"Parsed JSON entry: {entry}")
                    except json.JSONDecodeError as json_err:
                        logging.error(f"Error decoding JSON line: '{line}'. Error: {json_err}")
                        continue # Skip this line and try to process others

            # Extract playlist ID for better default titles if needed
            playlist_id = None
            if video_entries and 'playlist_id' in video_entries[0]:
                playlist_id = video_entries[0]['playlist_id']

            self.playlist_info = []
            for i, entry in enumerate(video_entries):
                url = entry.get('url')
                title = entry.get('title')
                
                if url is None:
                    logging.warning(f"Skipping entry {i} due to missing 'url': {entry}")
                    continue

                if not title: # Fallback title if not provided by yt-dlp
                    title = f"Untitled Song {i+1}"
                    if playlist_id:
                        title = f"Playlist {playlist_id} - {title}"
                
                self.playlist_info.append({'url': url, 'title': title})
            
            self.playlist_urls = [item['url'] for item in self.playlist_info] # Keep this for existing logic
            
            logging.info(f"Found {len(self.playlist_info)} videos in the playlist.")
            if not self.playlist_info:
                logging.warning("No videos found in the playlist.")
                return False
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Error fetching playlist URLs: {e}")
            logging.error(f"Stderr: {e.stderr}")
            return False
        except Exception as e:
            logging.error(f"An unexpected error occurred during playlist fetching: {e}", exc_info=True)
            return False

    def download_audio(self, url, cache_key, title=""):
        logging.info(f"download_audio called with url: {url}, cache_key: {cache_key}, title: {title}")
        if cache_key in self.cache and os.path.exists(self.cache[cache_key]):
            logging.info(f"Audio for '{title}' already in cache.")
            return self.cache[cache_key]

        download_temp_dir = "/dev/shm/ytstr_download"
        os.makedirs(download_temp_dir, exist_ok=True)
        
        logging.info(f"[cyan]Downloading audio for '{title}' to temporary directory {download_temp_dir}...[/cyan]")
        try:
            # Use yt-dlp to download audio only, without forcing mp3 format
            # yt-dlp will name the file, we will read its name later
            output_path_template = os.path.join(download_temp_dir, "%(title)s.%(ext)s")
            
            command = [
                "yt-dlp",
                "-x", # Extract audio
                "--audio-format", "best", # Use best audio format
                "-o", output_path_template,
                url
            ]
            logging.debug(f"Executing yt-dlp command for download: {' '.join(command)}")
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            logging.debug(f"yt-dlp stdout: {result.stdout}")
            logging.debug(f"yt-dlp stderr: {result.stderr}")

            downloaded_file = None
            # Find the actual downloaded file path in the temporary directory
            # yt-dlp prints the filename to stdout, so we can parse it
            for line in result.stdout.splitlines():
                if "[ExtractAudio]" in line and "Destination" in line:
                    # Example: [ExtractAudio] Destination: /dev/shm/ytstr_download/Song Title.opus
                    parts = line.split("Destination:")
                    if len(parts) > 1:
                        downloaded_file = parts[1].strip()
                        break
            
            if not downloaded_file:
                # Fallback: search the directory for the newest file
                files_in_temp = [os.path.join(download_temp_dir, f) for f in os.listdir(download_temp_dir)]
                if files_in_temp:
                    downloaded_file = max(files_in_temp, key=os.path.getctime)
                    logging.warning(f"Could not parse filename from yt-dlp stdout. Falling back to newest file: {downloaded_file}")

            if downloaded_file and os.path.exists(downloaded_file):
                # Extract title from the downloaded filename
                base_name = os.path.basename(downloaded_file)
                # Remove extension and potentially the ID if yt-dlp adds it (e.g., "Song Title [ID].ext")
                extracted_title = os.path.splitext(base_name)[0]
                # Remove common yt-dlp ID patterns like " [ID]"
                if extracted_title.endswith("]"):
                    id_start = extracted_title.rfind(" [")
                    if id_start != -1:
                        extracted_title = extracted_title[:id_start]
                
                # Update the playlist_info with the actual title
                # Find the index of the current song based on its URL
                current_song_index = -1
                for i, item in enumerate(self.playlist_info):
                    if item['url'] == url:
                        current_song_index = i
                        break
                
                if current_song_index != -1:
                    self.playlist_info[current_song_index]['title'] = extracted_title
                    logging.info(f"Updated title for song {current_song_index + 1} to: '{extracted_title}'")
                    # Update the 'title' variable for the rest of this function's scope
                    title = extracted_title
                else:
                    logging.warning(f"Could not find song URL {url} in playlist_info to update title.")

                # Move the file to the permanent cache directory
                final_cache_path = os.path.join(self.temp_dir, base_name)
                shutil.move(downloaded_file, final_cache_path)
                
                self.cache[cache_key] = final_cache_path
                logging.info(f"Downloaded and moved: '{title}' to {final_cache_path}")
                return final_cache_path
            else:
                logging.error(f"Error: Could not find downloaded file for '{title}' ({url}) in {download_temp_dir}")
                return None
            if downloaded_file:
                self.cache[cache_key] = downloaded_file
                print(f"Downloaded: '{title}' to {downloaded_file}")
                return downloaded_file
            else:
                print(f"Error: Could not find downloaded file for '{title}' ({url})")
                return None
        except subprocess.CalledProcessError as e:
            print(f"Error downloading audio for '{title}' ({url}): {e}")
            print(f"Stderr: {e.stderr}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred during download for '{title}' ({url}): {e}")
            return None

    def play_audio(self, audio_path):
        if self.player_process and self.player_process.poll() is None:
            self.player_process.terminate()
            self.player_process.wait() # Wait for the previous mpv process to terminate

        print(f"[bright_green]Playing: {audio_path} [/bright_green]")
        try:
            self.player_process = subprocess.Popen(
                ["mpv", "--no-video", "--really-quiet", audio_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            print("Error: mpv not found. Please install mpv to play audio.")
            sys.exit(1)
        except Exception as e:
            print(f"An error occurred while trying to play audio: {e}")

    def load_next_prev_cache(self):
        # Determine the range of songs to cache: 1 previous, current, 2 next
        indices_to_cache = set()
        if self.current_index - 1 >= 0:
            indices_to_cache.add(self.current_index - 1)
        indices_to_cache.add(self.current_index) # Current song is always cached
        if self.current_index + 1 < len(self.playlist_info):
            indices_to_cache.add(self.current_index + 1)
        if self.current_index + 2 < len(self.playlist_info):
            indices_to_cache.add(self.current_index + 2)

        # Start downloading/caching for the required range
        for index in sorted(list(indices_to_cache)):
            current_info = self.playlist_info[index]
            url = current_info['url']
            title = current_info['title'] # Use the existing title, download_audio will update it if needed
            cache_key = f"song_{index}"
            # Only start a new thread if not already in cache or being downloaded
            if cache_key not in self.cache or not os.path.exists(self.cache.get(cache_key, "")):
                threading.Thread(target=self.download_audio, args=(url, cache_key, title), daemon=True).start()

        # Clean up outdated cached files
        keys_to_remove = []
        for key in self.cache:
            try:
                index_from_key = int(key.split('_')[1])
                if index_from_key not in indices_to_cache:
                    file_path = self.cache[key]
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        print(f"Removed outdated cached file: {file_path}")
                    keys_to_remove.append(key)
            except (ValueError, IndexError):
                pass # Ignore malformed keys

        for key in keys_to_remove:
            del self.cache[key]

    def play_current_song(self):
        if not self.playlist_info:
            print("Playlist is empty.")
            return

        if not (0 <= self.current_index < len(self.playlist_info)):
            print("Current index out of bounds. Resetting to 0.")
            self.current_index = 0
            if not self.playlist_info: # Check again if playlist is empty after reset
                return

        current_info = self.playlist_info[self.current_index]
        current_url = current_info['url']
        
        # Fetch the actual title for the current song
        current_title = current_info['title'] # Use the title already in playlist_info (placeholder or from initial dump)
        current_cache_key = f"song_{self.current_index}"

        # Synchronously download the current song to ensure it plays ASAP
        # download_audio will update the title in playlist_info after download
        audio_path = self.download_audio(current_url, current_cache_key, current_title)
        if audio_path:
            # After download_audio, the title in playlist_info might have been updated
            # So, retrieve the potentially updated title for display
            updated_title = self.playlist_info[self.current_index]['title']
            print(f"Playing: '{updated_title}'") # Print the actual title
            self.play_audio(audio_path)
            # Asynchronously load next/prev cache after current starts playing
            threading.Thread(target=self.load_next_prev_cache, daemon=True).start()
        else:
            print(f"Could not play '{current_title}' ({current_url}). Skipping.")
            self.next_song() # Try to play the next song if current fails

    def next_song(self):
        if self.current_index + 1 < len(self.playlist_info):
            self.current_index += 1
            self.play_current_song()
        else:
            print("End of playlist.")

    def _input_listener(self):
        while not self.stop_event.is_set():
            try:
                command = sys.stdin.read(1) # Read one character at a time
                self.user_input_queue.put(command)
            except Exception as e:
                print(f"Error in input listener: {e}")
                self.stop_event.set()

    def run(self, playlist_url):
        if not self.fetch_playlist_urls(playlist_url):
            return

        self.current_index = 0
        self.play_current_song()

        # Start input listener thread
        input_thread = threading.Thread(target=self._input_listener, daemon=True)
        input_thread.start()

        while not self.stop_event.is_set():
            try:
                # Check if mpv process has finished
                if self.player_process and self.player_process.poll() is not None:
                    print("Current song finished, playing next.")
                    self.next_song()

                # Process user input
                command = self.user_input_queue.get(timeout=0.1)
                if command == '>':
                    print("User: Next song (>)")
                    self.next_song()
                elif command == '<':
                    print("User: Previous song (<)")
                    current_time = self._get_mpv_time_pos() # This will always be 0 now
                    if current_time < 5: # If within first 5 seconds
                        self.previous_song()
                    else:
                        # Replay current song (by restarting mpv with current song)
                        self.play_current_song()
                elif command == 'q':
                    print("User: Quit (q)")
                    self.stop_event.set()
                # Add other key bindings here if needed, e.g., for pause/resume
                # For rewind/forward, mpv's default keybindings will work directly in the terminal
            except queue.Empty:
                pass # No input, continue loop
            except Exception as e:
                print(f"Error in main loop: {e}")
                self.stop_event.set()

        self.cleanup()

    def cleanup(self):
        # Clean up all downloaded temporary files
        print("Cleaning up temporary files...")
        self.stop_event.set() # Signal listener thread to stop
        
        # Terminate mpv process if still running
        if self.player_process and self.player_process.poll() is None:
            print("Terminating mpv process in cleanup")
            self.player_process.terminate()
            self.player_process.wait() # Ensure mpv process is terminated
        else:
            print("No mpv process to terminate in cleanup")

        for _, path in self.cache.items():
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir) # Use rmtree to remove non-empty directory

if __name__ == "__main__":
    print("ytstr.py script started.") # Added print statement to confirm execution
    if len(sys.argv) != 2:
        logging.error("Usage: python ytstr.py <youtube_playlist_url>")
        sys.exit(1)

    playlist_url = sys.argv[1]
    player = YouTubePlayer()
    try:
        player.run(playlist_url)
    except KeyboardInterrupt:
        print("\nExiting player due to user interruption.")
    finally:
        player.cleanup()