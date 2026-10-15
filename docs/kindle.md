# Setting up the Kindle

**English** · [Português (Brasil)](pt-BR/kindle.md)

inkdoor runs on jailbroken Kindles. The Kindle side is small: two scriptlets that turn off the
Kindle interface and show the image rendered by your computer.

## 1. Jailbreak

Follow the up-to-date guide at [Kindle Modding](https://kindlemodding.org/jailbreaking/). The
method depends on your model and firmware version (Settings → Device Options → Device Info).
Recent jailbreaks install support for **scriptlets**: `.sh` files in the `documents` folder
that show up in the library and run when you tap them.

Before you start, put the Kindle in **airplane mode** so it does not update its firmware.

## 2. Install

With the Kindle connected over USB:

```
Kindle/
├── documents/
│   ├── inkdoor-start.sh       ← from kindle/documents/
│   └── inkdoor-test.sh        ← from kindle/documents/
└── inkdoor/                   ← the whole kindle/inkdoor/ folder
    ├── common.sh
    ├── config.sh
    └── loop.sh
```

Edit `inkdoor/config.sh`:

```sh
URL="http://192.168.0.10:3667/kindle.png"   # IP of the computer running "inkdoor serve"
INTERVAL=300                                # seconds between updates
FULL_REFRESH_EVERY=6                        # every N updates, a full refresh (flashes, clears ghosting)
LANGUAGE="en-US"                            # messages on the Kindle: en-US or pt-BR
```

You can edit it on Windows: line endings are fixed automatically.

## 3. Use

Eject the Kindle. The library now shows:

- **inkdoor - test connection**: turns on Wi-Fi, downloads the image once and reports the
  result. Changes nothing on the Kindle.
- **inkdoor - start display**: turns off the Kindle interface and starts showing your day.

**To get the normal Kindle back, restart it** (hold the power button). The display does not
start by itself after a restart.

## Tips

- **Power**: the display keeps Wi-Fi on and does not use deep sleep, so keep the Kindle on a
  charger. A thin USB cable fits through most door frames.
- **Fixed IP**: reserve an IP for your computer on the router; otherwise the address changes
  and the display stops updating. A home server avoids this and never sleeps
  ([docs/server.md](server.md)).
- **Single instance**: tapping "start display" twice does not start two loops.
- **No connection**: after 3 failures in a row, "cannot reach the computer" appears in the
  corner of the screen. The history is in `inkdoor/log.txt`, and
  [Troubleshooting](troubleshooting.md#on-the-kindle) explains every message.
