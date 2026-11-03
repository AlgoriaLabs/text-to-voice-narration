"""Text-to-speech narration: the work behind the paid services in provider.config.json.

The package knows nothing about payments. The Provider Kit gateway publishes the manifest, takes the USDC payment,
queues jobs and keeps them for recovery, and POSTs only validated input to app.py, which uses this package.
"""
