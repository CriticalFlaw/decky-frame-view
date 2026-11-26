import os
import decky
import asyncio

import remote

# The plugin's own SSH key and list of trusted headsets (~/homebrew/settings/frame-view)
KEY = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "id_ed25519")
KNOWN_HOSTS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "known_hosts")
SSH_ENV = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}

class Plugin:
    # A normal method. It can be called from the TypeScript side using @decky/api.
    async def add(self, left: int, right: int) -> int:
        return left + right

    async def long_running(self):
        await asyncio.sleep(15)
        # Passing through a bunch of random data, just as an example
        await decky.emit("timer_event", "Hello from the backend!", True, 2)

    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded
    async def _main(self):
        self.loop = asyncio.get_event_loop()
        decky.logger.info(f"Frame View running as {decky.USER}")

    # Function called first during the unload process, utilize this to handle your plugin being stopped, but not
    # completely removed
    async def _unload(self):
        decky.logger.info("Frame View unloading")
        pass

    # Function called after `_unload` during uninstall, utilize this to clean up processes and other remnants of your
    # plugin that may remain on the system
    async def _uninstall(self):
        decky.logger.info("Frame View uninstalling")
        pass

    async def test_connection(self, host: str) -> dict:
        try:
            argv = remote.ssh_command(KEY, KNOWN_HOSTS, host.strip(), "hostname; ls /dev/video99")
        except ValueError as e:
            return {"ok": False, "message": str(e)}

        # Run ssh without blocking Decky while it waits for the Frame.
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=SSH_ENV
        )
        out, err = await proc.communicate()
        out, err = out.decode().strip(), err.decode().strip()

        # Code 255 is returned when we couldn't connect or log into the Frame.
        if proc.returncode == 255:
            decky.logger.info(f"ssh failed: {err}")
            return {"ok": False, "message": err.splitlines()[-1] if err else "ssh failed"}

        # Otherwise it passes on the exit code of the command: ls fails if the device is missing.
        name = out.splitlines()[0] if out else host
        if proc.returncode == 0:
            return {"ok": True, "message": f"Connected to {name}. Ready to view."}
        return {"ok": True, "message": f"Connected to {name}. Start SteamVR on the Frame to see its view."}

    # Migrations that should be performed before entering `_main()`.
    async def _migration(self):
        decky.logger.info("Migrating")
        # Here's a migration example for logs:
        # - `~/.config/decky-template/template.log` will be migrated to `decky.decky_LOG_DIR/template.log`
        decky.migrate_logs(os.path.join(decky.DECKY_USER_HOME,
                                               ".config", "decky-template", "template.log"))
        # Here's a migration example for settings:
        # - `~/homebrew/settings/template.json` is migrated to `decky.decky_SETTINGS_DIR/template.json`
        # - `~/.config/decky-template/` all files and directories under this root are migrated to `decky.decky_SETTINGS_DIR/`
        decky.migrate_settings(
            os.path.join(decky.DECKY_HOME, "settings", "template.json"),
            os.path.join(decky.DECKY_USER_HOME, ".config", "decky-template"))
        # Here's a migration example for runtime data:
        # - `~/homebrew/template/` all files and directories under this root are migrated to `decky.decky_RUNTIME_DIR/`
        # - `~/.local/share/decky-template/` all files and directories under this root are migrated to `decky.decky_RUNTIME_DIR/`
        decky.migrate_runtime(
            os.path.join(decky.DECKY_HOME, "template"),
            os.path.join(decky.DECKY_USER_HOME, ".local", "share", "decky-template"))
