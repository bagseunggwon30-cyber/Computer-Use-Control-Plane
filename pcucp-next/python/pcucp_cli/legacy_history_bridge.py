"""Python file ownership and history reducers; scalar facts come from the caller's JSON dialect."""
from .legacy_diagnostic_provider import option, owned_path, read_regular
from .legacy_history import SmartClickHistory
from .legacy_host import _read_lines
from .legacy_host_protocol import exact, require
from .legacy_values import int32


def _rows(args):
    rows = args['rows']
    require(type(rows) is list and len(rows) <= 20000, 'Invalid captured history rows.')
    for row in rows:
        exact(row, ('matched', 'strategy', 'key', 'strategy_truth', 'success', 'success_truth', 'label', 'match', 'elapsed', 'record'))
        require(all(type(row[k]) is bool for k in ('matched', 'strategy_truth', 'success', 'success_truth')) and
                all(type(row[k]) is str for k in ('strategy', 'label', 'match', 'elapsed')) and
                type(row['key']) is int and 0 <= row['key'] <= 20000, 'Invalid captured history scalar facts.')
    return rows


def handle(request, *, history_file, maximum):
    exact(request, ('action', 'args'))
    require(type(request['action']) is str and type(request['args']) is dict, 'Invalid history request.')
    require(type(maximum) is int and 1 <= maximum <= 2147483647, 'Invalid history retention limit.')
    path = owned_path(history_file)
    store = SmartClickHistory(str(path.parent), maximum, path=str(path))
    action, args = request['action'], request['args']
    if action == 'append':
        exact(args, ('label', 'match', 'strategy', 'success', 'elapsed_ms'))
        require(all(type(args[k]) is str for k in ('label', 'match', 'strategy')) and
                type(args['success']) is bool and type(args['elapsed_ms']) is int and
                -2147483648 <= args['elapsed_ms'] <= 2147483647, 'Invalid history append values.')
        store.append(**args)
        return {'value': None}
    if action == 'read':
        exact(args, ())
        if not path.exists():
            return dict(exists=False, lines=[])
        raw, _ = read_regular(path)
        return dict(exists=True, lines=_read_lines(raw.decode('utf-8-sig', errors='replace')))
    if action == 'pick':
        exact(args, ('rows', 'lookback'))
        require(type(args['lookback']) is int and -2147483648 <= args['lookback'] <= 2147483647, 'Invalid lookback.')
        candidates = [row for row in reversed(_rows(args)) if row['matched']][:max(0, args['lookback'])]
        counts = {}
        for row in candidates:
            if row['success'] and row['strategy_truth']:
                count, spelling = counts.get(row['key'], (0, row['strategy']))
                counts[row['key']] = (count + 1, spelling)
        if not counts:
            return dict(value=None, tie=False, top=[], candidates=[])
        highest = max(count for count, _ in counts.values())
        top = [spelling for count, spelling in counts.values() if count == highest]
        # -contains retains the calling runtime's linguistic comparison. The
        # caller resolves this final scalar comparison over the prepared ties.
        return dict(value=top[0] if len(top) == 1 else None, tie=len(top) > 1, top=top,
                    candidates=[dict(success=row['success'], strategy=row['strategy']) for row in candidates])
    if action == 'stats':
        exact(args, ('rows',))
        rows, groups, success = _rows(args), {}, 0
        for row in rows:
            if row['success']:
                success += 1
                count, spelling = groups.get(row['key'], (0, row['strategy']))
                groups[row['key']] = (count + 1, spelling)
        # Math.Round(Double, 1) scales before midpoint-to-even rounding;
        # Python round(value, 1) instead uses a different decimal conversion.
        rate = round(success / len(rows) * 100 * 10) / 10 if rows else 0.0
        if rate.is_integer():
            rate = int(rate)
        # Empty or reserved strategy names cannot cross ConvertFrom-Json as
        # PSObject property names. Typed pairs restore the original Hashtable.
        return dict(value=dict(total=len(rows), success=success, success_rate=rate, strategies=None),
                    strategy_pairs=[dict(name=spelling, count=count) for count, spelling in groups.values()])
    require(action == 'macro', 'Unknown history operation.')
    exact(args, ('rest', 'brief', 'exists', 'rows'))
    rest, brief = args['rest'], args['brief']
    require(type(rest) is list and all(type(v) is str for v in rest) and
            type(brief) is bool and type(args['exists']) is bool, 'Invalid history macro argv.')
    rows = _rows(args)
    verb = (rest[0] if rest else 'show').lower()
    lines = []
    if verb == 'show':
        label = option(rest, '--label') or ''
        last = int32(option(rest, '--last'))
        if last <= 0:
            last = 20
        if not args['exists']:
            payload = {'status': 'ok', 'records': []}
            lines = ['ok history empty file=none']
        else:
            records = []
            for row in reversed(rows):
                if len(records) >= last:
                    break
                if label and not row['matched']:
                    continue
                record = row['record']
                records.extend(record if isinstance(record, list) else [record])
            payload = dict(status='ok', schema='cucp.history/v1', records=records, count=len(records))
            lines = [f"ok history count={len(records)} label='{label}' last={last}"]
            # Individual array rows are rendered by the caller after its native
            # JSON conversion; no Python approximation of PSObject strings.
        return dict(payload=payload, brief_lines=lines, records=payload['records'],
                    json_depth=5, exit_code=0, verb=verb, missing=not args['exists'])
    if verb == 'stats':
        stats = handle(dict(action='stats', args=dict(rows=rows)), history_file=history_file, maximum=maximum)
        return dict(payload=stats['value'], strategy_pairs=stats['strategy_pairs'], brief_lines=[], records=[], json_depth=4, exit_code=0, verb=verb, missing=False)
    if verb == 'clear':
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return dict(payload=dict(status='ok', cleared=True), brief_lines=['ok history cleared'],
                    records=[], json_depth=5, exit_code=0, verb=verb, missing=False)
    raise ValueError("macro history requires 'show' / 'stats' / 'clear' subcommand")
