# Video Transcriber

A polished local video/audio transcription GUI powered by FastAPI and faster-whisper. It runs locally on Fedora/Linux, uses no paid APIs, and lets you choose a media file, transcribe it, preview the transcript, and download generated text/subtitle files from the browser.

## Fedora Setup

```bash
sudo dnf install ffmpeg python3-pip -y
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

## Run The GUI

Start the local app:

```bash
source .venv/bin/activate
./run.sh
```

Then open the browser GUI at:

```text
http://127.0.0.1:8000
```

The first transcription with a selected Whisper model downloads that model from Hugging Face. After that, transcription runs locally using the cached model files.

## Supported Files

- `.mp4`
- `.mkv`
- `.mov`
- `.webm`
- `.mp3`

## How It Works

1. Open `http://127.0.0.1:8000`.
2. Click `Choose Video` or drag-and-drop a supported media file.
3. Select a Whisper model, language, and output preview format.
4. Start transcription.
5. Watch the progress bar, elapsed time, estimated remaining time, and processed timestamp.
6. Preview the transcript in the browser.
7. Use the GUI buttons to download:
   - `Download transcript`
   - `Download timestamped text`
   - `Download subtitles`

You do not need to manually open files from `outputs/`; the GUI exposes the generated files directly after transcription.

## Progress

The browser polls the local backend once per second while a transcription job is running. Progress is estimated from the latest processed Whisper segment timestamp divided by the probed media duration from `ffprobe`.

The progress panel shows:

- Current stage: preparing file, loading model, transcribing, writing files, complete, or error.
- Percentage complete.
- Elapsed time.
- Estimated remaining time once timestamp progress is available.
- Processed media timestamp, such as `00:13:50 / 00:32:30`.

## Generated Files

Transcript files are saved in the local `outputs/` folder and are also downloadable from the GUI.

Output filenames are based on the uploaded media filename. For example:

Input:

```text
my lecture video.mp4
```

Outputs:

```text
outputs/my-lecture-video-transcript.txt
outputs/my-lecture-video-timestamped.txt
outputs/my-lecture-video.srt
```

If a filename already exists, the app adds a numeric suffix so older transcripts are not overwritten.

Uploaded media files are temporarily saved in `uploads/` during processing and removed after transcription finishes.

## Fedora Notes

- `ffmpeg` and `ffprobe` must be available on your `PATH`.
- If Fedora cannot find `ffmpeg`, enable RPM Fusion or install the package from your configured multimedia repositories.
- Larger Whisper models need more memory and will take longer on CPU. Start with `small`, then increase model size if you need better accuracy.
- The backend uses CUDA with `float16` when the CUDA runtime libraries are usable. If CUDA is unavailable or required libraries such as `libcublas.so.12` are missing, it falls back to CPU with `int8`.
- Python 3.14 package resolution was checked for the listed dependencies in this environment.

## API

- `GET /` serves the frontend.
- `GET /api/health` reports server, ffmpeg, ffprobe, CUDA, device, and compute type status.
- `POST /api/transcribe` accepts a multipart file upload and settings, starts a local transcription job, and returns a `job_id`.
- `GET /api/progress/{job_id}` returns current stage, percentage, elapsed time, ETA, and processed timestamp.
- `GET /api/result/{job_id}` returns the finished transcript, generated filenames, and download URLs.
- `GET /api/download/{filename}` downloads generated transcript files from `outputs/`.
