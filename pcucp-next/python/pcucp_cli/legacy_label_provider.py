"""Read-only acquisition for the original managed find-label coordinator."""
import time
from .legacy_diagnostic_provider import option, timestamp
from .legacy_host_protocol import Authority, exact, require


class LabelReadProvider:
    def __init__(self, runtime, rest, *, brief=False):
        require(type(rest) is list and all(type(value) is str for value in rest), 'Label argv must be strings.')
        self.runtime, self.rest, self.brief = runtime, list(rest), brief
        self.match = option(rest, '--match') or option(rest, '--window') or ''
        self.started = None
        self.parent_deadline = runtime._deadline

    def startup(self):
        return dict(schema='cucp.interaction-start/v1', operation='find-label', rest=self.rest,
                    brief=self.brief, cache_seconds=self.runtime.cache_seconds,
                    vision_available=bool(self.runtime.context['cli_path']), culture=self.runtime.culture,
                    double=False, right_click=False)

    def validate_startup(self, family, startup, authority):
        require(family == 'interaction' and startup == self.startup() and authority == Authority(),
                'Read-only label startup or authority changed.')

    def validate(self, effect):
        require(not effect.argv and not any((effect.live, effect.quiet, effect.brief, effect.confirm_sensitive)),
                'Read-only label provider cannot acquire input authority.')
        if effect.kind == 'Clock':
            require(effect.name in {'start', 'stop', 'elapsed'} and effect.data == 'find-label', 'Invalid label clock.')
        elif effect.kind == 'Timestamp':
            require(effect.name == 'o' and effect.data is None, 'Invalid label timestamp.')
        elif effect.kind == 'Win32Windows':
            exact(effect.data, ('match',))
            require(effect.name == '' and effect.data['match'] == self.match and
                    any(value.casefold() == '--fast' for value in self.rest), 'Label window query changed its requested match.')
        elif effect.kind == 'Appshot':
            require(effect.name == '' and effect.data == {'match': self.match, 'semantic': True, 'no_cache': False},
                    'Label appshot changed its original acquisition.')
        else:
            require(False, 'Effect is outside the read-only label provider: ' + effect.kind)

    def dispatch(self, effect):
        self.runtime._remaining()
        if effect.kind == 'Clock':
            if effect.name == 'start':
                self.started = time.monotonic()
                return 0
            require(self.started is not None, 'Label clock has not started.')
            return round((time.monotonic() - self.started) * 1000)
        if effect.kind == 'Timestamp':
            return timestamp()
        if effect.kind == 'Win32Windows':
            return self.runtime._windows(self.match)
        if effect.kind == 'Appshot':
            return self.runtime._appshot({**effect.data, 'cache_max_seconds': None})
        require(False, 'Unknown read-only label effect.')

    def validate_completion(self, result):
        require(type(result['payload']) is dict and result['exit'] in (0, 1, 2), 'Invalid read-only label completion.')
