"""Small concurrent log reader and HTTP server; all runtime state stays in memory."""
import argparse
import asyncio
import copy
import math
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from engine import Inspector

ROOT = Path(__file__).resolve().parent


def create_app(mode='stdin', container=None, replay=None, year=None, timeout=30):
    engine = Inspector(year, timeout)
    source = {'connected': False, 'mode': mode, 'containerName': container, 'error': None}

    async def read_source():
        process = None
        pipe_transport = None
        try:
            if mode == 'replay':
                with open(replay, encoding='utf-8', errors='replace') as stream:
                    source['connected'] = True
                    for line in stream:
                        engine.feed(line)
                        await asyncio.sleep(0)
                return
            if mode == 'docker':
                # -n fails clearly instead of hanging on an invisible password prompt.
                process = await asyncio.create_subprocess_exec(
                    'sudo', '-n', 'docker', 'logs', '--follow', '--since', '0s', container,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    limit=1024 * 1024)
                reader = process.stdout
            else:
                reader = asyncio.StreamReader(limit=1024 * 1024)
                pipe_transport, _ = await asyncio.get_running_loop().connect_read_pipe(
                    lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
            source['connected'] = mode == 'docker'
            diagnostics = []
            while line := await reader.readline():
                decoded = line.decode('utf-8', errors='replace')
                source['connected'] = True
                diagnostics = (diagnostics + [decoded.rstrip()])[-10:]
                engine.feed(decoded)
                if mode == 'stdin' and any(term in decoded.lower() for term in
                    ('permission denied', 'cannot connect to the docker daemon', 'no such container', 'a password is required')):
                    source.update(connected=False, error=decoded.strip())
            if process:
                code = await process.wait()
                if code:
                    raise RuntimeError(f'Docker log reader exited {code}: ' + '\n'.join(diagnostics))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            source['error'] = str(exc)
            print(f'Log source error: {exc}', file=sys.stderr, flush=True)
        finally:
            engine.finish()
            source['connected'] = False
            if pipe_transport:
                pipe_transport.close()
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

    async def watchdog():
        while True:
            await asyncio.sleep(0.25)
            # Replay uses source timestamps only: EOF is not proof of timeout.
            if mode != 'replay':
                engine.expire()

    @asynccontextmanager
    async def lifespan(app):
        tasks = [asyncio.create_task(read_source()), asyncio.create_task(watchdog())]
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title='5G Core Inspector', lifespan=lifespan)
    app.state.inspector = engine
    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'static/index.html')

    @app.get('/api/health')
    async def health():
        detection = engine.detection()
        return {'status': 'error' if source['error'] or detection['status'] == 'mixed' else 'ok',
                'coreDetection': detection,
                'logSource': dict(source), 'linesProcessed': engine.lines,
                'matchedEvents': len(engine.events), 'ueCount': len(engine.ues()),
                'uncorrelatedLines': len(engine.uncorrelated)}

    @app.get('/api/registration')
    async def registration(sessionId: str | None = None):
        if sessionId is None:
            return engine.snapshot()
        for record in engine.attempts:
            if record['sessionId'] == sessionId:
                return copy.deepcopy(record)
        raise HTTPException(status_code=404, detail='Unknown registration session')

    @app.get('/api/registrations')
    async def registrations():
        return copy.deepcopy(engine.attempts)

    @app.get('/api/ues')
    async def ues():
        return engine.ues()

    @app.get('/api/uncorrelated')
    async def uncorrelated():
        return copy.deepcopy(engine.uncorrelated)

    @app.get('/api/events')
    async def events(sessionId: str | None = None):
        return copy.deepcopy([e for e in engine.events if sessionId is None or e['sessionId'] == sessionId])

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--docker-container')
    modes.add_argument('--stdin', action='store_true')
    modes.add_argument('--replay', type=Path)
    parser.add_argument('--year', type=int, default=datetime.now().year)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.year <= 9999 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('year must be 1–9999 and timeout must be finite and positive')
    uvicorn.run(create_app('docker' if args.docker_container else 'replay' if args.replay else 'stdin',
                          args.docker_container, args.replay, args.year, args.timeout),
                host=args.host, port=args.port)
