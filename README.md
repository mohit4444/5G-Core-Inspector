# 5G Core Inspector

When a UE failed to register on my 5G network, I had to scroll through core logs
to work out what happened. I built this lightweight tool to bring each attempt,
its timeline and the relevant evidence into one screen.

It reads **Open5GS** and **OAI 5G Core** logs and detects the core automatically. Will add more open source core support soon

## What you can do

- Search for a UE — a phone, modem or simulated device.
- Open its timeline and choose a registration attempt.
- See the observed failure, possible causes and suggested checks.
- Expand events to read the original log messages.
- See data-session details and assigned IP addresses when the logs provide them.

## Get started

You need Git and [Docker with Compose](https://docs.docker.com/get-started/get-docker/).
Run these commands on the computer running your core.

### 1. Clone

```bash
git clone https://github.com/mohit4444/5G-Core-Inspector.git
cd 5G-Core-Inspector
```

### 2. Build

```bash
docker compose build
```

### 3. Connect your core

Your core must already be running. Choose one option below and run it from the
Inspector folder. The Inspector runs in Docker in every case.

#### Open5GS running in Docker

Find your core's container name with `docker ps`. Replace
`YOUR_AMF_CONTAINER` with the container that provides AMF registration logs:

```bash
docker logs --follow --since 0s YOUR_AMF_CONTAINER 2>&1 \
  | docker compose run --rm --service-ports -T inspector --stdin
```

#### Open5GS running without Docker

Read new messages from the AMF log file:

```bash
sudo tail -n 0 -F /var/log/open5gs/amf.log \
  | docker compose run --rm --service-ports -T inspector --stdin
```

Change the path if your installation stores logs elsewhere. For data-session
details, add `/var/log/open5gs/smf.log` after the AMF file path.

#### OAI 5G Core

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

### 4. Open the dashboard

Open **http://127.0.0.1:8000**, then connect a UE. Select it to see its timeline.
Only new logs are read, so start the Inspector before connecting the UE.

If Docker needs `sudo`, add it before each `docker` command.
If port 8000 is busy, create `.env` in the Inspector folder with
`INSPECTOR_PORT=8002`, then use http://127.0.0.1:8002.

To try an example without a core, run `docker compose up` after building.
**Disconnected** is expected when the example finishes. Before connecting a
live core, press **Ctrl+C** and run `docker compose down`.

## Stop and restart

Press **Ctrl+C** to stop. Run the same connection command to restart or choose
another core. Results stay in memory and are cleared when the Inspector stops.
If live logs disconnect, check the source and restart the Inspector.

## Current coverage

Tested in a local Linux lab with Open5GS and OAI v2.2.2. OAI testing used one UE.
Use one network per Inspector.

- OAI requires text logs; JSON logs and data-session release are not supported.
- Logs without clear UE identifiers can leave timelines incomplete, especially
  with multiple OAI UEs. The Inspector does not guess which UE a message belongs to.
- Possible causes are suggestions. An assigned IP does not prove data traffic works.
