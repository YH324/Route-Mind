"""
Compatibility wrapper for the local data provider.

New code should import from ``local_data_provider``. This module remains so
older imports keep working.
"""

from local_data_provider import (  # noqa: F401
    DataProviderNetworkError,
    DataProviderQuotaError,
    LocalCorpusClient,
    LocalDataApiClient,
    LocalDataNetworkError,
    LocalDataQuotaError,
)
