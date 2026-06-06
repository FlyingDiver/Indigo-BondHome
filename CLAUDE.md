# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an [Indigo](https://www.indigodomo.com/) home automation plugin that integrates Bond Home smart devices (ceiling fans, fireplaces, motorized shades, lights, bidets) via the Bond Local HTTP REST API v2 and UDP push notifications (BPUP).

All plugin source lives under `BondHome.indigoPlugin/Contents/Server Plugin/`.

## Architecture

The plugin has two core files:

**`plugin.py`** — Main plugin class inheriting from `indigo.PluginBase`. Manages the full Indigo lifecycle: device startup/shutdown, Zeroconf bridge discovery, action dispatching, and real-time state callbacks from BPUP. Key data structures:
- `self.bond_bridges` — dict of active `BondHome` objects keyed by BondID
- `self.bond_devices` — maps Bond device IDs to Indigo device IDs
- `self.known_devices` — nested dict of device metadata per bridge
- `self.known_scenes` — nested dict of scene metadata per bridge
- `self.deferred_start` — Bond devices waiting for their bridge to initialize

**`bondhome.py`** — Bond Local API client. Wraps HTTP REST calls (base URL `http://{address}/v2/{endpoint}`, auth via `BOND-Token` header) and manages the BPUP UDP socket (port 30007). Sends keepalive pings every 60 seconds; parses JSON state messages on topic format `devices/{device_id}/state` and calls back into `plugin.py`.

**XML configuration files** define the Indigo UI:
- `Devices.xml` — two device types: `bondBridge` (dimmer) and `bondDevice` (relay)
- `Actions.xml` — four actions: Send Device Command, Set Command Repeats, Execute Scene, Update State Belief
- `PluginConfig.xml` — log level preference only
- `MenuItems.xml` — Write Device Info to Log, Execute Scene

## Device Type Codes

Bond device types used throughout the code: `CF` (Ceiling Fan), `FP` (Fireplace), `MS` (Motorized Shades), `LT` (Light), `BD` (Bidet), `GX` (Generic), `UN` (Unknown).

## Device Hierarchy

Bond bridges (`bondBridge`) are parent Indigo devices. Bond controllable devices (`bondDevice`) are children that reference a specific bridge. Devices in `self.deferred_start` are queued until their bridge finishes initializing.

## Parameter Substitution

`bondDevice` action parameters support Indigo variable/device state substitution using `%%v:ID%%` and `%%d:ID:state%%` syntax, handled in `plugin.py` before passing to the API.

## Dependencies

Only one external dependency: `zeroconf==0.130.0` (see `requirements.txt`). Indigo provides `requests` and all standard library modules. Python 3.10–3.13 supported.

## Development & Testing

There is no automated test suite. Testing requires a live Bond bridge on the local network and Indigo running with the plugin installed. The plugin is deployed by placing the `.indigoPlugin` bundle into Indigo's plugin folder.

To install dependencies for local development:
```sh
pip install -r "BondHome.indigoPlugin/Contents/Server Plugin/requirements.txt"
```

Logging verbosity is controlled by the `logLevel` plugin preference (default INFO/20). Set to DEBUG (10) for detailed API and UDP traffic logging during development.
