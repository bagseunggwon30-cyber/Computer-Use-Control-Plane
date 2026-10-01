"""Read-only installation diagnostics; never opens or manipulates a desktop."""
import sys

from . import __version__
from .native_host import _native_argv, run_native
from .protocol import version_payload


def diagnose() -> dict:
    errors = []
    argv, error = _native_argv()
    native = None
    if argv is None:
        errors.append({"code": "native_unavailable", "message": error})
    else:
        code, payload, error = run_native("version")
        if code or payload is None or payload.get("status") != "ok":
            errors.append({"code": "native_unavailable", "message": error or str(payload)})
        else:
            native = payload.get("data", {})
            if native.get("parent_lifetime_guard") != "inherited-parent-handle/v1":
                errors.append({"code": "native_feature_mismatch", "message": "Publish the matching native source: this engine requires the parent-liveness guard; older 0.4.0 binaries are not compatible."})
            if native.get("version") != __version__:
                errors.append({"code": "version_mismatch", "message": "Engine and native worker must come from the same bundle."})
    if sys.platform != "win32":
        errors.append({"code": "unsupported_platform", "message": "Desktop control requires Windows."})
    return {"schema": "cucp.doctor/v1", "status": "error" if errors else "ok",
            "engine": version_payload(), "native_command": argv, "native": native,
            "desktop_verified": False, "errors": errors,
            "note": "Checks runtime startup only. Interactive desktop, capture, input and elevation require separate checks."}
