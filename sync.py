"""Synchronize originals between two running servers; never sync embeddings."""
import argparse
import hashlib
import os
from pathlib import Path
import portalocker
import requests
from app.core.config import BASE_DIR
from app.services.sync_client import Peer, SyncClient

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-url', default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--remote-url', required=True)
    parser.add_argument('--state-file', type=Path)
    args = parser.parse_args()
    state = args.state_file or BASE_DIR / 'database' / ('sync-' + hashlib.sha256(args.remote_url.encode()).hexdigest()[:12] + '.json')
    state.parent.mkdir(parents=True, exist_ok=True)
    try:
        with portalocker.Lock(str(state) + '.lock', timeout=0):
            client = SyncClient(Peer(args.local_url, os.getenv('POCKET_LOCAL_TOKEN', '')),
                                Peer(args.remote_url, os.getenv('POCKET_REMOTE_TOKEN', '')), state)
            result = client.run()
        print(f"Synchronized {result['transferred']} changes")
        if result['conflicts']:
            print('Conflicting document IDs (preserved on both sides): ' + ', '.join(result['conflicts']))
            raise SystemExit(2)
    except (requests.RequestException, ValueError, OSError, portalocker.exceptions.LockException) as exc:
        parser.exit(1, f'Synchronization failed; checkpoints retained for retry: {exc}\n')
