"""Capture metadata from the same responses consumed by discord.py-self search."""

from copy import copy


class SearchMetadata:
    def __init__(self):
        self.total_results = None
        self.indexing = False
        self.response_seen = False

    def capture_response(self, data):
        # Later SDK pages narrow the snowflake range. Their totals no longer
        # describe the original filters, so retain only the first response.
        if self.response_seen or not isinstance(data, dict):
            return
        self.response_seen = True
        value = data.get("total_results")
        if type(value) is int and value >= 0:
            self.total_results = value
        self.indexing = data.get("doing_deep_historical_index") is True

    def capture_message(self, message):
        # Public Message metadata also supports custom search destinations.
        if self.response_seen:
            return
        value = getattr(message, "total_results", None)
        if type(value) is int and value >= 0:
            self.total_results = value
            self.indexing = getattr(message, "doing_deep_historical_index", False) is True
            self.response_seen = True


class _SearchHTTP:
    def __init__(self, http, metadata):
        self._http = http
        self._metadata = metadata

    def __getattr__(self, name):
        return getattr(self._http, name)

    async def search_guild(self, *args, **kwargs):
        data = await self._http.search_guild(*args, **kwargs)
        self._metadata.capture_response(data)
        return data

    async def search_channel(self, *args, **kwargs):
        data = await self._http.search_channel(*args, **kwargs)
        self._metadata.capture_response(data)
        return data


class _SearchState:
    def __init__(self, state, metadata):
        self._state = state
        self.http = _SearchHTTP(state.http, metadata)

    def __getattr__(self, name):
        return getattr(self._state, name)


def search_with_metadata(target, metadata, **kwargs):
    state = getattr(target, "_state", None)
    if state is None:
        return target.search(**kwargs)
    # Isolate the HTTP observer to this search, including parallel batch
    # searches. The original destination, client and HTTP methods stay intact.
    destination = copy(target)
    destination._state = _SearchState(state, metadata)
    return destination.search(**kwargs)
