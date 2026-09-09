# NexDisNew

> **FFUF + Discord automation for collecting, storing, and viewing results from one place.**

NexDisNew is a Python-based Discord bot that adds a Discord interface around an FFUF-powered data collection workflow. Instead of watching a long terminal session, users can trigger the workflow, inspect results through Discord embeds, browse stored data, and use interactive panels for dashboards and historical analysis.

The project is designed to make an FFUF-based workflow easier to operate from Discord while keeping collected results in local SQLite databases.

---

## ✨ Features

### Discord-first interface
Use Discord commands, embeds, buttons, and select menus to operate and inspect the system.

### FFUF integration
The repository includes an FFUF executable and a shell-based core workflow used to locate matching records and pass them into the Python application.

### SQLite persistence
Collected data is stored locally in SQLite so the application can reuse historical information across runs.

### Deep Scan
`!deepscan` processes an ID range, collects problem metadata, invokes the FFUF-based extraction workflow, and stores the resulting records in the deep-scan database.

### Interactive dashboard
`!dashboard <cid>` displays stored records in a paginated Discord dashboard with summary statistics and submission information.

### Historical analysis
The Discord UI can filter historical data by month, category, and class and display frequently observed problem titles.

### LIVE / OFFLINE mode
The application keeps a persistent system mode and can use the normal database or the deep-scan database depending on the active mode.

### Owner controls
The current codebase also includes owner-only controls for maintenance mode, credential replacement, broadcast messages, and deep scanning.

---

## 🧭 Architecture

```text
Discord
  │
  ▼
main.py
Discord bot + application logic
  │
  ├──────────────► SQLite databases
  │
  └──────────────► nexus_core.sh
                       │
                       ▼
                      FFUF
                       │
                       ▼
                Retrieved records
                       │
                       ▼
                     SQLite
                       │
                       ▼
              Discord dashboard
```

At a high level, `main.py` handles Discord interactions and application logic. The shell layer uses FFUF as part of the extraction workflow, while SQLite provides persistent local storage.

---

## 📦 Project structure

```text
NexDisNew/
├── main.py                    # Main Discord bot and application logic
├── keep_alive.py              # Flask keep-alive endpoint
├── nexus_core.sh              # FFUF-based extraction workflow
├── ffuf                       # Included FFUF executable
├── ffuf_2.1.0_linux_amd64.tar.gz
│                              # FFUF Linux archive
├── nexus_overseer.db          # Main SQLite database
├── deepscan_data.db           # Deep-scan / historical database
├── rescan_data.db             # Additional local SQLite data
├── nexus_mode.txt             # Persistent LIVE / OFFLINE state
├── pyproject.toml             # Python project metadata
└── README.md
```

The SQLite files are intentionally included in the repository as part of the project's current public data state.

---

## 🛠️ Requirements

The current codebase is designed around:

- Python **3.11+**
- Linux environment recommended for the included shell/FFUF workflow
- `bash`
- `curl`
- `jq`
- `seq`
- FFUF
- A Discord bot/application

Python packages imported by the current application include:

```text
discord.py
python-dotenv
requests
aiohttp
psutil
Flask
```

The current `pyproject.toml` declares Python `>=3.11` but does not declare these application dependencies, so install them separately.

---

## 🚀 Installation

### 1. Clone

```bash
git clone https://github.com/JansFrans/NexDisNew.git
cd NexDisNew
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -U pip
pip install discord.py python-dotenv requests aiohttp psutil Flask
```

### 4. Prepare the executable files

```bash
chmod +x nexus_core.sh
chmod +x ffuf
```

### 5. Configure environment variables

Create `.env` in the project directory:

```env
DISCORD_TOKEN=your_discord_bot_token
GEMINI_API_KEY=your_gemini_api_key
```

Keep real credentials private and do not commit them to a public repository.

### 6. Run

```bash
python3 main.py
```

`keep_alive.py` exposes a small Flask service on port `8080` for hosting environments that need a continuously running web endpoint.

---

## 🤖 Discord commands

The current codebase includes commands such as:

```text
!dashboard <cid>
!deepscan [start_id] [end_id]
!maintenance
!broadcast <message>
!set_token api <token>
!set_token gemini <token>
```

### `!dashboard <cid>`

Shows stored data for a specific CID in an interactive paginated dashboard.

```text
!dashboard 12345
```

### `!deepscan [start_id] [end_id]`

Starts the deep-scan workflow over a selected ID range. When no range is supplied, the application uses its saved scan state to determine the next range.

```text
!deepscan 1000 1200
```

### `!maintenance`

Toggles maintenance mode. Owner-only.

### `!broadcast <message>`

Sends an announcement to active channels tracked by the application. Owner-only.

### `!set_token ...`

Updates runtime credentials without editing the source file. Owner-only. Tokens should only be handled privately.

---

## 💾 Data storage

NexDisNew uses SQLite for local persistence. The deep-scan database can contain information such as:

- contest/session metadata
- problem metadata
- submission IDs
- usernames and user IDs
- scores and penalties
- source code captured by the workflow
- submission status
- difficulty labels
- timestamps
- problem IDs

The schema can evolve as the project changes. The application includes initialization and migration logic for the deep-scan database.

---

## 🔎 FFUF integration

NexDisNew does not replace FFUF. FFUF is one component inside the larger Discord + extraction workflow.

`nexus_core.sh` uses FFUF to search a numeric input range, identify matching record IDs, retrieve the matching records, and emit structured data for `main.py`.

Simplified flow:

```text
Input range
    ↓
   FFUF
    ↓
Matching IDs
    ↓
HTTP retrieval
    ↓
Structured records
    ↓
SQLite
    ↓
Discord UI
```

This is the main reason to use NexDisNew instead of running FFUF alone: the scan/extraction layer is connected to persistent storage and a Discord interface.

---

## 🧪 Typical usage flow

1. Start the Discord bot.
2. Trigger the appropriate collection or scan command.
3. Let the FFUF-based workflow process the selected range.
4. Collected records are stored in SQLite.
5. Open the dashboard from Discord to inspect the stored results.
6. Use the historical-analysis UI to explore previously collected sessions.

---

## 🔐 Security notes

This repository is public. Anyone with access to it can inspect committed source files and committed database contents.

Keep credentials in environment variables or your hosting provider's secret store. Do not publish real Discord or AI credentials.

Only use the project against systems and data that you are authorized to access.

---

## 📌 Project status

NexDisNew is an evolving personal project. Its current implementation is closely tied to its existing workflow, data model, and Discord UI, so commands and internal behavior may change over time.

This README documents the project as it currently exists rather than presenting it as a generic FFUF wrapper.

---

## 📄 FFUF / licensing

NexDisNew includes and uses FFUF. Before redistributing the repository or bundled FFUF binaries, review the applicable upstream FFUF license and the licenses of any included components.

Upstream FFUF: https://github.com/ffuf/ffuf

---

## 👤 Author

**JansFrans**

GitHub: https://github.com/JansFrans

Repository: https://github.com/JansFrans/NexDisNew
