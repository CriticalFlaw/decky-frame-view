def ssh_command(key: str, known_hosts: str, host: str, command: str) -> list:
    # A "host" starting with "-" could be read by ssh as an option, so refuse it.
    if not host or host.startswith("-"):
        raise ValueError("Enter the Frame's hostname or IP address.")
    
    return [
        "ssh",
        "-i", key,                                  # log in with the plugin's own ssh key
        "-o", "BatchMode=yes",                      # fail instead of asking for a password
        "-o", f"UserKnownHostsFile={known_hosts}",  # plugin's own list of trusted headsets
        "-o", "StrictHostKeyChecking=accept-new",   # trust the Frame the first time we connect
        "-o", "ConnectTimeout=8",                   # give up on a Frame that doesn't answer
        f"steamos@{host}",
        command,
    ]