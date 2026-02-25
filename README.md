# trackid

Identify tracks inside DJ sets — SoundCloud, Mixcloud, YouTube, or local files.
Built with a focus on techno, but works across all genres.

## How it works

1. **Downloads** the set audio via `yt-dlp` (or reads a local file).
2. **Slices** the audio into short overlapping samples (default: 12 s every 30 s).
3. **Fingerprints** each sample against a recognition API (AudD or ACRCloud).
4. **Deduplicates** consecutive hits of the same track and builds a timestamped tracklist.

## Installation

```bash
pip install .
# For development (includes test deps)
pip install -e ".[dev]"
```

You also need [FFmpeg](https://ffmpeg.org) installed for audio processing:

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
apt install ffmpeg
```

## Quick start

```bash
# Identify a SoundCloud mix (free AudD sandbox, no key needed)
trackid identify https://soundcloud.com/dj/mix-title

# Higher rate-limits: use your AudD token
trackid identify https://soundcloud.com/dj/mix-title --audd-token YOUR_TOKEN

# ACRCloud backend (better DJ-mix detection, needs credentials)
trackid identify https://soundcloud.com/dj/mix-title \
  --backend acrcloud \
  --acr-key YOUR_KEY \
  --acr-secret YOUR_SECRET

# Local WAV / MP3 / FLAC file
trackid identify /path/to/set.wav

# Save tracklist to a file
trackid identify https://... -o tracklist.txt

# Sample more frequently (every 15 s) for better recall
trackid identify https://... --step 15
```

### Environment variables

Instead of passing flags every time, export:

```bash
export AUDD_TOKEN=your_token
export ACR_KEY=your_key
export ACR_SECRET=your_secret
```

## Options

```
Usage: trackid identify [OPTIONS] SOURCE

  Identify all tracks in SOURCE (URL or local file path).

Options:
  --backend [audd|acrcloud]  Audio recognition backend.  [default: audd]
  --audd-token TEXT          AudD API token.
  --acr-key TEXT             ACRCloud access key.
  --acr-secret TEXT          ACRCloud access secret.
  --acr-host TEXT            ACRCloud region host.
  --step INTEGER             Seconds between consecutive samples.  [default: 30]
  --chunk INTEGER            Length of each audio sample (seconds).  [default: 12]
  --min-hits INTEGER         Minimum API hits to include a track.  [default: 1]
  --delay FLOAT              Seconds to wait between API requests.  [default: 0.5]
  -o, --output PATH          Save tracklist to this file (plain text).
  --help                     Show this message and exit.
```

## API backends

| Backend   | Free tier                  | Best for                        | Credentials needed   |
|-----------|----------------------------|---------------------------------|----------------------|
| **audd**  | 300 req/month (no key)     | Quick tests, short sets         | Optional             |
| **acrcloud** | 1 000 req/day           | Long sets, high accuracy        | Key + secret         |

Sign up at [audd.io](https://audd.io) or [acrcloud.com](https://acrcloud.com).

## Tips for techno sets

- **`--step 20`** — Sample every 20 s; catches tracks with long intros.
- **`--min-hits 2`** — Require at least 2 detections; reduces false positives.
- **ACRCloud** has broader coverage of underground labels and catalog depth,
  making it the preferred backend for techno, industrial, and EBM.

## Running tests

```bash
pytest
```
