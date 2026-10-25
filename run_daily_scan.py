"""Execute a fresh copy of Shoryuken notebook sections 1 through 6b."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sys
import time


def prepare(notebook, project):
    """Select by headings; retain every code cell through 6b, including diagnostics."""
    cells = notebook['cells']
    starts = [i for i, c in enumerate(cells) if c['cell_type'] == 'markdown'
              and re.search(r'^##\s+1\.\s', ''.join(c.get('source', [])), re.M)]
    ends = [i for i, c in enumerate(cells) if c['cell_type'] == 'markdown'
            and re.search(r'^##\s+6b\.\s', ''.join(c.get('source', [])), re.M)]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError('Expected unique section 1 and section 6b headings')
    stop = next((i for i in range(ends[0]+1, len(cells))
                 if cells[i]['cell_type'] == 'markdown'
                 and re.search(r'^##\s+', ''.join(cells[i].get('source', [])), re.M)), len(cells))
    selected = json.loads(json.dumps(cells[starts[0]:stop]))
    mapped = 0
    found_export = False
    for cell in selected:
        if cell['cell_type'] != 'code':
            continue
        source = ''.join(cell.get('source', []))
        source, count = re.subn(r'^PROJECT_DIR\s*=.*$',
                               lambda _: 'PROJECT_DIR = Path(' + repr(str(project)) + ')',
                               source, flags=re.M)
        mapped += count
        found_export |= 'html_path = export_scan_board(' in source
        cell['source'] = source.splitlines(keepends=True)
        cell['outputs'] = []
        cell['execution_count'] = None
    if mapped != 1 or not found_export:
        raise ValueError('Notebook setup/export changed; review section selection before scheduling')
    prelude = dict(cell_type='code', metadata={}, execution_count=None, outputs=[],
                   source=['import webbrowser\n',
                           'webbrowser.open = lambda *args, **kwargs: False\n'])
    final = dict(cell_type='code', metadata={}, execution_count=None, outputs=[], source=[
        'from pathlib import Path\n',
        'assert "html_path" in globals() and Path(html_path).is_file(), "HTML export missing"\n',
        'print("AUTOMATION_HTML:", Path(html_path).resolve())\n',
        'print("AUTOMATION_DATA_DATE:", method_results.attrs.get("asof"))\n'])
    result = dict(notebook, cells=[prelude] + selected + [final])
    # JSON notebooks may store source as arrays of lines. NotebookClient and
    # our logging hooks require the in-memory source to be one text string.
    for cell in result['cells']:
        source = cell.get('source', '')
        cell['source'] = ''.join(source) if isinstance(source, list) else source
    return result


@contextmanager
def exclusive_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--dry-run', action='store_true', help='Validate selection; no cells executed')
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    project = Path(config['project']).resolve()
    notebook_path = Path(config['notebook']).resolve()
    if not project.is_dir():
        raise FileNotFoundError(project)
    source = json.loads(notebook_path.read_text(encoding='utf-8-sig'))
    prepared = prepare(source, project)
    if args.dry_run:
        print('Notebook:', notebook_path)
        print('Working directory:', project)
        print('Selected section 1 through 6b; code cells:',
              sum(c['cell_type'] == 'code' for c in prepared['cells']) - 2)
        print('Section 1 pip install and all diagnostic cells included. Browser disabled.')
        print('No notebook cells executed; no project outputs modified.')
        return 0
    output = project / 'logs' / 'scheduled'
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    log_path = output / (stamp + '.log')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.FileHandler(log_path, encoding='utf-8'), logging.StreamHandler()])
    try:
        with exclusive_lock(output / 'daily_scan.lock'):
            return execute(prepared, config, project, output, stamp)
    except (BlockingIOError, PermissionError) as error:
        logging.error('Cannot acquire/use run lock or access files: %s', error)
        return 2
    except Exception:
        logging.exception('Daily scan failed')
        return 1


def execute(prepared, config, project, output, stamp):
    import nbformat
    from nbclient import NotebookClient

    class LoggedClient(NotebookClient):
        async def async_execute_cell(self, cell, cell_index, *args, **kwargs):
            if cell.cell_type == 'code':
                logging.info('Cell %d start: %s', cell_index,
                             cell.source.splitlines()[0] if cell.source else '(empty)')
            try:
                return await super().async_execute_cell(cell, cell_index, *args, **kwargs)
            finally:
                for item in cell.get('outputs', []):
                    if item.output_type == 'stream':
                        logging.info('%s', item.text.rstrip())
                    elif item.output_type == 'error':
                        logging.error('%s: %s', item.get('ename'), item.get('evalue'))

    # Read through nbformat's deserializer, which also normalizes multiline
    # fields; from_dict alone wraps dictionaries without doing that conversion.
    nb = nbformat.reads(json.dumps(prepared), as_version=4)
    nb_path = output / (stamp + '.ipynb')
    status = dict(started_utc=datetime.now(timezone.utc).isoformat(), status='running',
                  source_notebook=config['notebook'], python=sys.executable,
                  executed_notebook=str(nb_path))
    logging.info('Starting sections 1–6b; Python %s; cwd %s', sys.executable, project)
    started = time.perf_counter()
    try:
        client = LoggedClient(nb, kernel_name=config['kernel'], timeout=7200,
                              startup_timeout=180, allow_errors=False,
                              resources={'metadata': {'path': str(project)}})
        client.execute()
        status['status'] = 'success'
        return 0
    except Exception:
        status['status'] = 'failed'
        logging.exception('Notebook execution stopped; later cells were not run')
        return 1
    finally:
        nbformat.write(nb, nb_path)
        status['finished_utc'] = datetime.now(timezone.utc).isoformat()
        status['elapsed_seconds'] = round(time.perf_counter()-started, 2)
        (output / (stamp + '.json')).write_text(json.dumps(status, indent=2), encoding='utf-8')
        logging.info('Run %s; executed copy %s', status['status'], nb_path)


if __name__ == '__main__':
    raise SystemExit(main())
