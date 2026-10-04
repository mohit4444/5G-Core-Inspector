# 5G Core Inspector

**Open5GS & OpenAirInterface log analysis. Understand why a UE registration failed.**

[![Project checks](https://github.com/mohit4444/5G-Core-Inspector/actions/workflows/checks.yml/badge.svg)](https://github.com/mohit4444/5G-Core-Inspector/actions/workflows/checks.yml)
[![Docker](https://img.shields.io/badge/run_with-Docker-2496ED?logo=docker&logoColor=white)](#quick-start)

When a UE failed to register on my 5G network, I had to scroll through core logs
to work out what happened. I built this lightweight tool to bring each attempt,
its timeline and the relevant evidence into one screen.

It reads **Open5GS** and **OpenAirInterface (OAI) 5G Core** logs, detects the core
automatically, and opens a troubleshooting dashboard in your browser.

![5G Core Inspector dashboard with a searchable UE list and Open5GS registration statuses](.github/assets/dashboard.png)
*Dashboard preview using synthetic example data.*

[Quick start](#quick-start) · [Connect your core](#connect-your-core) · [Project structure](#project-structure)

## What you can do

- **Find a UE:** search for a phone, modem or simulated device.
- **Follow each attempt:** select a registration and inspect its timeline.
- **Investigate failures:** see the observed failure, possible causes and suggested checks.
- **Read the evidence:** expand original log messages and inspect PDU session details.

<details>
<summary>See a failure diagnosis</summary>

![Open5GS registration failure showing the observed cause, suggested checks and expandable raw log evidence](.github/assets/failure.png)
*Synthetic example data.*

</details>

## Quick start

You need Git and [Docker with Compose](https://docs.docker.com/get-started/get-docker/).

```bash
git clone https://github.com/mohit4444/5G-Core-Inspector.git
cd 5G-Core-Inspector
docker compose build
```

Then choose your connection below. No Python or Node.js installation is needed.

<details>
<summary>Try it without a 5G core</summary>

```bash
docker compose up
```

Open http://127.0.0.1:8000 to explore a synthetic Open5GS example.
**Disconnected** is expected when the file finishes; the results stay visible.
Before connecting a live core, press **Ctrl+C** and run `docker compose down`.

</details>

## Connect your core

Your core must already be running. Run one of these commands from the Inspector
folder on the same computer. The Inspector runs in Docker in every case.

### Open5GS running in Docker

Find your core's container name with `docker ps`. Replace
`YOUR_AMF_CONTAINER` with the container that provides AMF registration logs:

```bash
docker logs --follow --since 0s YOUR_AMF_CONTAINER 2>&1 \
  | docker compose run --rm --service-ports -T inspector --stdin
```

### Open5GS running without Docker

Read new messages from the AMF log file:

```bash
sudo tail -n 0 -F /var/log/open5gs/amf.log \
  | docker compose run --rm --service-ports -T inspector --stdin
```

Change the path if your installation stores logs elsewhere. For data-session
details, add `/var/log/open5gs/smf.log` after the AMF file path.

### OAI 5G Core

Enable **debug** logging on the OAI AMF. For a Docker Compose deployment, read
AMF and SMF logs together:

```bash
docker compose -f /path/to/oai/compose.yaml \
  logs --follow --since 0s --no-color oai-amf oai-smf 2>&1 \
  | docker compose run --rm --service-ports -T inspector --stdin
```

Replace the file path and service names with yours. If you started OAI with
`-p`, `--env-file` or extra `-f` files, use those same options on the left side.
Keep the service prefixes in the logs. The same command works for separate
Open5GS AMF/SMF services with their Compose file and service names.

Open **http://127.0.0.1:8000**, then connect a UE. Select it to see its timeline.
Start the Inspector before connecting the UE; these commands read new logs only.

If Docker needs `sudo`, add it before each `docker` command.
If port 8000 is busy, create `.env` with `INSPECTOR_PORT=8002` and use
http://127.0.0.1:8002.

## Stop and restart

Press **Ctrl+C** to stop. Run the same connection command to restart or choose
another core. Results stay in memory and are cleared when the Inspector stops.
If live logs disconnect, check the source and restart the Inspector.

## Project structure

```text
backend/          Python server and command-line entry point
  core/           Shared registration and PDU analysis
  adapters/       Open5GS and OAI log parsers
frontend/src/     React interface, components and hooks
tests/backend/    Backend tests
frontend/tests/   Browser tests
examples/         Synthetic logs for demos and tests
scripts/          Docker verification
static/           Built interface, generated from frontend/src
```

Docker and GitHub Actions build and check the complete application. `app.py`
remains a compatibility launcher; new source runs use `python -m backend`.
