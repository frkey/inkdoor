# Running inkdoor on a home server

**English** · [Português (Brasil)](pt-BR/server.md)

`inkdoor serve` has to run all the time: when it stops, the Kindle stops updating. A laptop
that sleeps at night is a poor host. A home server is a better one, and inkdoor is light: one
small Python process that needs under 100 MB of RAM and about 1 GB of disk, operating system
included.

- **Proxmox VE**: one command creates a container with everything set up. [Jump there](#proxmox-ve).
- **Any Debian or Ubuntu machine** (a VM, a mini PC, a Raspberry Pi with a 64-bit OS):
  [use the installer](#debian-or-ubuntu).

Either way you get the same layout:

| Path | What it is |
|---|---|
| `/etc/inkdoor/config.toml` | your config, readable only by root and the `inkdoor` user |
| `/opt/inkdoor` | the code and its Python environment |
| `/var/lib/inkdoor/kindle.png` | the rendered screen |
| `inkdoor.service` | the systemd service, started at boot and restarted if it fails |
| `/usr/local/bin/inkdoor` | runs inkdoor with that config: `inkdoor check`, `inkdoor render` |

## Proxmox VE

`deploy/proxmox/create-lxc.sh` runs on the Proxmox host. It downloads the newest Debian
template, creates an unprivileged container (1 core, 512 MB of RAM, 4 GB of disk, started at
boot) and installs inkdoor in it.

1. Open a shell on the Proxmox host: in the web UI, select the node and click **Shell**
   (or connect with SSH as root).
2. Download the script and read it if you like:

   ```sh
   curl -fsSLO https://raw.githubusercontent.com/frkey/inkdoor/master/deploy/proxmox/create-lxc.sh
   ```

3. Run it:

   ```sh
   bash create-lxc.sh
   ```

   To bring your existing `config.toml`, copy it to the host first (for example
   `scp config.toml root@<proxmox-ip>:`) and add `--config config.toml`. Add `--lang pt-BR`
   for the screen and the messages in Brazilian Portuguese.

4. At the end the script prints the container's ID and IP.
   - **If you passed `--config`**, the service is already running.
   - **If not**, finish the setup inside the container:

     ```sh
     pct enter <id>
     nano /etc/inkdoor/config.toml   # paste your calendar links (docs/calendar-sources.md)
     inkdoor check                   # test every link
     systemctl start inkdoor
     ```

5. On the Kindle, set `URL="http://<container-ip>:8000/kindle.png"` in `inkdoor/config.sh`
   ([Kindle setup](kindle.md)).

### Options

| Option | Default | |
|---|---|---|
| `--config FILE` | | `config.toml` to copy into the container |
| `--lang en-US\|pt-BR` | `en-US` | screen language of a new config, and the script's messages |
| `--ip dhcp\|CIDR` | `dhcp` | a static address, e.g. `192.168.1.50/24` |
| `--gateway IP` | | your router, required with a static `--ip` |
| `--ctid N` | next free ID | |
| `--hostname NAME` | `inkdoor` | |
| `--bridge NAME` | `vmbr0` | |
| `--storage NAME` | `local-lvm` | where the container's disk goes |
| `--template-storage NAME` | `local` | where the Debian template is stored |
| `--disk GB` | `4` | can be grown later with `pct resize <id> rootfs +1G` |
| `--memory MB` | `512` | |
| `--ref BRANCH_OR_TAG` | `master` | inkdoor version to install |

The Kindle must always find the server at the same address. Use a static `--ip`, or reserve
the container's address on your router (a "DHCP reservation").

### Day to day

| Task | Command on the Proxmox host |
|---|---|
| Update inkdoor | `pct exec <id> -- bash /root/inkdoor-install.sh` |
| Follow the log | `pct exec <id> -- journalctl -u inkdoor -f` |
| Test the calendar links | `pct exec <id> -- inkdoor check` |
| Edit the config | `pct enter <id>`, then `nano /etc/inkdoor/config.toml` |

Config changes are picked up at the next refresh; only a new `port` needs
`systemctl restart inkdoor`.

### Creating the container yourself

If you prefer to make the container in the web UI, keep it **unprivileged** with the
**nesting** feature on (both are the defaults). The service runs in a systemd sandbox, which
fails to start without nesting (status `226/NAMESPACE`). Then follow the next section inside
the container.

## Debian or Ubuntu

`deploy/install.sh` works on Debian 12 or newer and Ubuntu 22.04 or newer, with systemd. As
root:

```sh
curl -fsSLO https://raw.githubusercontent.com/frkey/inkdoor/master/deploy/install.sh
bash install.sh
```

It installs Python and git from apt, downloads inkdoor to `/opt/inkdoor`, creates the
`inkdoor` user and the service. On the first run it creates `/etc/inkdoor/config.toml` from the
example, with the machine's time zone and the `--lang` you gave, and leaves the service
stopped. Fill in the config, run `inkdoor check`, then `systemctl start inkdoor`.

Run the same script again to update: it downloads the new version and restarts the service.
It never overwrites your config.

Options: `--lang en-US|pt-BR`, `--timezone Area/City` (for a new config), `--ref BRANCH_OR_TAG`.

## Security

- **Keep it on your local network.** Never forward the port on your router: the image shows
  your schedule. If the server has a firewall, allow the port only from your LAN or from the
  Kindle's IP.
- The HTTP server answers only `/kindle.png`, and the service runs as an unprivileged user in a
  systemd sandbox that can only write to `/var/lib/inkdoor`.
- `config.toml` holds secret calendar links: anyone who has them can read your calendars.
