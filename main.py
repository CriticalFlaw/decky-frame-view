import logging
import os
import sys

import decky

# Decky puts py_modules on sys.path; make sure it's there when run by hand too.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "py_modules"))

from frameview import remote  # noqa: E402
from frameview.core import Core  # noqa: E402

# Route the package's log lines into the plugin's Decky log.
_pkg_log = logging.getLogger("frameview")
_pkg_log.parent = decky.logger
_pkg_log.setLevel(logging.INFO)


class Plugin:
    core: Core = None

    async def _main(self):
        Plugin.core = Core(
            settings_dir=decky.DECKY_PLUGIN_SETTINGS_DIR,
            runtime_dir=decky.DECKY_PLUGIN_RUNTIME_DIR,
            home=decky.DECKY_USER_HOME,
        )
        await Plugin.core.server.start()
        decky.logger.info("Frame View ready")

    async def _unload(self):
        if Plugin.core:
            await Plugin.core.close()
        decky.logger.info("Frame View unloaded")

    async def _uninstall(self):
        pass

    # ---- callables used by the frontend ------------------------------------

    async def get_settings(self) -> dict:
        return Plugin.core.public_settings()

    async def set_settings(self, changes: dict) -> dict:
        try:
            return {"ok": True, "settings": Plugin.core.update_settings(changes)}
        except (remote.RemoteError, ValueError) as e:
            return {"ok": False, "message": str(e), "settings": Plugin.core.public_settings()}

    async def pair(self, password: str) -> dict:
        return await Plugin.core.pair(password)

    async def test_connection(self) -> dict:
        return await Plugin.core.test_connection()

    async def forget_host_key(self) -> dict:
        return Plugin.core.forget_host_key()

    async def stream_info(self) -> dict:
        return await Plugin.core.stream_info()

    async def stop_stream(self) -> bool:
        return await Plugin.core.stop_stream()
