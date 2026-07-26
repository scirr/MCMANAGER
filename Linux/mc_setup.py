import sys
from mc_lang import T

def verify_and_install():
    import mc_core
    ok, _ = mc_core.check_java()
    if not ok:
        print(f"\033[91m[{T['icon_warn']}]\033[0m {T['java_required']}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['java_download']}\033[0m")
        print(f"\033[91m[{T['icon_err']}]\033[0m {T['java_missing']}")
        sys.exit(1)
