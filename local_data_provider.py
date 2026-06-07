"""
Local corpus data provider for RouteMind.

The planning service consumes POI search, rating, business-hour and routing
data through this provider contract. The current provider is backed by curated
local indexes, while the same methods can be implemented by remote map and
review services for broader city coverage.
"""

from mock_api import LocalProviderClient, ProviderNetworkError, ProviderQuotaError


class LocalCorpusClient(LocalProviderClient):
    """Production-facing provider backed by the bundled local corpus."""

    pass


class DataProviderQuotaError(ProviderQuotaError):
    """Quota error raised by a local or remote data provider."""

    pass


class DataProviderNetworkError(ProviderNetworkError):
    """Network/data-access error raised by a local or remote data provider."""

    pass


# Backward-compatible names used by older modules.
LocalDataApiClient = LocalCorpusClient
LocalDataQuotaError = DataProviderQuotaError
LocalDataNetworkError = DataProviderNetworkError
