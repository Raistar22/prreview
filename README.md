# PR Review Bot 🤖

AI-powered GitHub Pull Request code reviewer that automatically reviews diffs, detects bugs, security issues, and best-practice violations, and posts inline comments directly on your PRs.

![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/framework-FastAPI-009688)
![CPU Only](https://img.shields.io/badge/GPU-not%20required-green)
![Docker](https://img.shields.io/badge/deploy-Docker-2496ED)

---

## Architecture

```
GitHub PR Event
     │
     ▼
┌──────────────────┐
│  Webhook Server  │ ◄── Signature verification (HMAC-SHA256)
│  (FastAPI)       │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  GitHub Auth     │ ◄── JWT generation + Installation token exchange
│  Layer           │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  PR Analyzer     │ ◄── Fetch files, parse diffs, filter non-code
│                  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  AI Review       │ ◄── Local LLM inference (CPU-only, GGUF)
│  Engine          │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Review          │ ◄── Map comments to files/lines, post to PR
│  Publisher       │
└──────────────────┘
```

## Project Structure

```
prreview/
├── app/
│   ├── main.py              # FastAPI entry point + lifespan
│   ├── config.py            # Pydantic settings (env vars)
│   ├── webhook/
│   │   ├── handler.py       # Webhook endpoint + review pipeline
│   │   └── security.py      # HMAC-SHA256 signature verification
│   ├── github/
│   │   ├── auth.py          # JWT + installation token management
│   │   ├── client.py        # Async GitHub REST API client
│   │   └── reviews.py       # PR review publishing
│   ├── analyzer/
│   │   ├── diff_parser.py   # Unified diff parser + chunker
│   │   └── filters.py       # File type filters
│   ├── reviewer/
│   │   ├── prompt.py        # System/user prompt templates
│   │   └── engine.py        # LlamaCpp + Mock review engines
│   └── utils/
│       └── logger.py        # Structured JSON logging
├── tests/
│   ├── test_security.py     # Webhook signature tests
│   └── test_diff_parser.py  # Diff parser tests
├── Dockerfile               # Multi-stage, CPU-only build
├── requirements.txt
├── .env.example
└── README.md
```

## Quick Start

### Prerequisites

- Python 3.11+
- A GitHub App ([create one here](https://github.com/settings/apps/new))
- A GGUF model file (e.g., [TinyLlama-1.1B](https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF))

### 1. Create a GitHub App

1. Go to **GitHub Settings → Developer Settings → GitHub Apps → New GitHub App**
2. Configure:
   - **Name**: `PR Review Bot` (or any unique name)
   - **Homepage URL**: `https://github.com/your-username/prreview`
   - **Webhook URL**: Your server URL + `/webhook` (e.g., `https://your-domain.com/webhook`)
   - **Webhook Secret**: Generate a strong secret and save it
3. **Permissions**:
   - **Pull requests**: Read & Write
   - **Contents**: Read-only
4. **Subscribe to events**: `Pull request`
5. Click **Create GitHub App**
6. Note the **App ID** from the app settings page
7. Generate a **Private Key** (.pem file) and download it

### 2. Install the App

1. Go to your App's settings → **Install App**
2. Select the repositories you want to enable

### 3. Set Up Environment

```bash
# Clone the repo
git clone https://github.com/your-username/prreview.git
cd prreview

# Copy environment template
cp .env.example .env
```

Edit `.env` with your values:

```env
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY_PATH=./private-key.pem
GITHUB_WEBHOOK_SECRET=your-secret-here
AI_MODEL_PATH=./models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
USE_MOCK_ENGINE=false
LOG_LEVEL=INFO
```

### 4. Download a Model

```bash
mkdir -p models
# Download TinyLlama (recommended for 4-8 GB RAM)
wget -O models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf \
  https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
```

### 5. Run Locally

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Local Testing with ngrok

To test with real GitHub webhooks locally:

```bash
# Install ngrok (https://ngrok.com/download)
ngrok http 8000

# Copy the HTTPS URL (e.g., https://abc123.ngrok.io)
# Update your GitHub App's Webhook URL to: https://abc123.ngrok.io/webhook
```

Then open a PR on a repository where the app is installed — the bot will automatically review it.

### 7. Test with Mock Engine

For quick testing without downloading a model:

```env
USE_MOCK_ENGINE=true
```

The mock engine returns sample review comments for every file.

---

## Docker Deployment

### Build

```bash
docker build -t pr-review-bot .
```

### Run

```bash
docker run -d \
  --name pr-review-bot \
  -p 8000:8000 \
  -v $(pwd)/private-key.pem:/app/private-key.pem:ro \
  -v $(pwd)/models:/app/models:ro \
  --env-file .env \
  --memory=4g \
  --restart unless-stopped \
  pr-review-bot
```

### Docker Compose (Optional)

```yaml
version: "3.8"
services:
  pr-review-bot:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./private-key.pem:/app/private-key.pem:ro
      - ./models:/app/models:ro
    env_file:
      - .env
    deploy:
      resources:
        limits:
          memory: 4G
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"]
      interval: 30s
      timeout: 5s
      retries: 3
```

---

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_APP_ID` | ✅ | — | GitHub App ID |
| `GITHUB_PRIVATE_KEY_PATH` | ✅ | — | Path to `.pem` file |
| `GITHUB_WEBHOOK_SECRET` | ✅ | — | Webhook secret |
| `AI_MODEL_PATH` | ❌ | `/app/models/model.gguf` | Path to GGUF model |
| `AI_MAX_TOKENS` | ❌ | `1024` | Max generation tokens |
| `AI_CONTEXT_SIZE` | ❌ | `2048` | Model context window |
| `AI_THREADS` | ❌ | `0` (auto) | CPU threads for inference |
| `USE_MOCK_ENGINE` | ❌ | `false` | Use mock engine (testing) |
| `MAX_DIFF_CHUNK_SIZE` | ❌ | `3000` | Max diff chunk size (chars) |
| `LOG_LEVEL` | ❌ | `INFO` | Logging level |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook` | GitHub webhook receiver |
| `GET` | `/health` | Health check |
| `GET` | `/` | API info |
| `GET` | `/docs` | OpenAPI documentation |

---

## Swapping the AI Model

The review engine is pluggable. To use a different model:

1. **Different GGUF model**: Just change `AI_MODEL_PATH` to point to any GGUF-format model. Recommended models:
   - **TinyLlama 1.1B** (Q4_K_M) — ~700 MB, fast, good for 4 GB RAM
   - **Phi-2** (Q4_K_M) — ~1.7 GB, better quality, needs 6+ GB RAM
   - **CodeLlama 7B** (Q4_K_M) — ~4 GB, best quality, needs 8+ GB RAM

2. **Custom engine**: Subclass `ReviewEngine` in `app/reviewer/engine.py` and implement `review_diff()`, `startup()`, and `shutdown()`.

---

## Troubleshooting

### Webhook signature verification fails
- Ensure `GITHUB_WEBHOOK_SECRET` exactly matches the secret in your GitHub App settings
- Check that no proxy is modifying the request body

### Model fails to load
- Verify the GGUF file path is correct and the file is not corrupted
- Check available RAM: the model + overhead should fit in your memory limit
- Try a smaller quantization (Q4_K_S instead of Q4_K_M)

### Rate limiting
- The client automatically retries on 403/rate-limit responses
- For high-volume usage, consider caching or queuing reviews

### Docker build fails on llama-cpp-python
- Ensure Docker has at least 4 GB of memory allocated for the build
- The build requires `cmake` and `gcc` (included in the builder stage)

---

## License

MIT
