"""Framework adapters for the VoiceLink SDK.

Each adapter lives in its own submodule and is imported only on demand, so the core SDK
never depends on any framework. Install the matching extra to use one:

    pip install voicelink[livekit]
    pip install voicelink[pipecat]

Importing an adapter without its extra raises a clear ImportError telling you which
package to install.
"""
