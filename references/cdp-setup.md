# Optional CDP

Start a browser/Electron debug endpoint only when explicitly authorized by the user. CUCP uses an existing numeric loopback endpoint selected at startup with `--cdp-endpoint http://127.0.0.1:9222`; it never scans ports or starts a browser.

Use cdp-detect, cdp-observe and declared DOM query tools. Sensitive nodes are guarded. Inputs/JavaScript evaluation require startup live permission and current DOM observations. Debug ports may expose private data and should remain local. See [host setup](../docs/host-neutral-setup.md).
