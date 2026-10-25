"""Patch only ranking weights and enable the existing liquidity filter."""
import argparse
import ast
from datetime import datetime
import os
from pathlib import Path
import tempfile


WEIGHTS = dict(quality=0.25, confidence=0.0, rr=0.10, rs=0.40,
               sector=0.25, liquidity=0.0, regime=0.0)


def revised_config(source):
    tree = ast.parse(source)
    targets = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in (
                        'RANKING_WEIGHTS', 'REQUIRE_MIN_DOLLAR_VOLUME'):
                    if target.id in targets or len(node.targets) != 1:
                        raise ValueError('Ambiguous configuration assignment')
                    targets[target.id] = node
    if set(targets) != {'RANKING_WEIGHTS', 'REQUIRE_MIN_DOLLAR_VOLUME'}:
        raise ValueError('Expected ranking and liquidity settings not found; no file changed')
    if abs(sum(WEIGHTS.values())-1) > 1e-9:
        raise ValueError('Weights must sum to 1')
    newline = '\r\n' if '\r\n' in source else '\n'
    lines = source.splitlines(keepends=True)
    replacements = {
        'RANKING_WEIGHTS': newline.join([
            'RANKING_WEIGHTS = dict(',
            '    quality=0.25,    # setup quality',
            '    confidence=0.0,  # rule coverage: display only',
            '    rr=0.10,         # existing capped planned reward/risk',
            '    rs=0.40,         # stock relative strength',
            '    sector=0.25,     # sector strength',
            '    liquidity=0.0,   # existing liquidity filter, no ranking points',
            '    regime=0.0,      # market-wide context, no ranking points',
            ')',
        ]) + newline,
        'REQUIRE_MIN_DOLLAR_VOLUME': 'REQUIRE_MIN_DOLLAR_VOLUME = True' + newline,
    }
    for name, node in sorted(targets.items(), key=lambda item: item[1].lineno, reverse=True):
        lines[node.lineno-1:node.end_lineno] = [replacements[name]]
    result = ''.join(lines)
    # Verify every other executable configuration statement is unchanged.
    def other_nodes(text):
        return [ast.dump(n, include_attributes=False) for n in ast.parse(text).body
                if not (isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id in targets for t in n.targets))]
    if other_nodes(result) != other_nodes(source):
        raise ValueError('Unexpected configuration change')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    path = args.project.resolve() / 'config.py'
    original = path.read_bytes()
    text = original.decode('utf-8-sig')
    result = revised_config(text)
    encoded = result.encode('utf-8')
    if original.startswith(b'\xef\xbb\xbf'):
        encoded = b'\xef\xbb\xbf' + encoded
    if encoded == original:
        print('Ranking update already installed. Nothing changed.')
        return
    backup = path.with_name('config.py.before_ranking_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.bak')
    with backup.open('xb') as stream:
        stream.write(original)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='config.ranking.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Updated:', path)
    print('Original backup:', backup)
    print('Weights:', WEIGHTS)
    print('Liquidity filter enabled; existing dollar-volume thresholds preserved.')
    print('Restart the Jupyter kernel and regenerate reports. Future scheduled runs load this config.')


if __name__ == '__main__':
    main()
