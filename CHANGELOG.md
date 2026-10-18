# Changelog

All notable changes to **Must Inverter Extended** are listed here.
Versions before 1.0.0 are the original [ha-must-inverter](https://github.com/mukaschultze/ha-must-inverter)
releases by @mukaschultze - see its [releases page](https://github.com/mukaschultze/ha-must-inverter/releases).

## [1.0.2] - 2026-10-18

### Fixed
- **`AttributeError: module 'custom_components.must_inverter.time' has no attribute 'monotonic'`**
  logged when a register mismatch was seen. Home Assistant sets the package's `time` attribute to the
  integration's own `time.py` platform once that platform loads, which shadowed the standard-library
  `time` module used by the mismatch tracker. The standard library module is now imported under an
  alias, so mismatch tracking (and the repair logic from 1.0.1) works after start-up.

## [1.0.1] - 2026-10-14

### Fixed
- **"Mismatched Modbus Registers" repair raised by harmless one-off reads.** On a single
  inverter with nothing else on the serial port, every mismatch seen in a week happened within
  about a minute of a Home Assistant restart (a late reply from a timed-out request read as the
  answer to the next one). The repair is now raised only after **3 mismatches within 10 minutes**,
  ignoring the first 2 minutes after start, and **clears itself after 10 good reads**. A stale
  repair from before a restart is removed at setup.
- Serial receive buffer is flushed after (re)connecting and before the next read after an
  error or mismatch, so a late reply can't be taken as the answer to the next request.

### Changed
- Repair text explains the real causes; "Learn more" links to this README.

## [1.0.0] - 2026-10-14

First release of the extended variant, based on upstream **v0.2.5** (commit 9fd3315).

### Added
- Battery **state of charge** and **state of health** for PV1800 inverters with a CAN/RS485 BMS
  (registers 113-114, same as PV1900). Skipped automatically after 3 failed reads in a row, so
  inverters without a BMS link don't log an error every poll (upstream issue #104).
- **SOC back to grid** (20147) and **SOC back to battery** (20148) number entities - already-polled
  registers, no extra reads.
- **Battery charge power** / **Battery discharge power** sensors (>= 0 W) derived from battery
  power, for the Energy dashboard; disabled by default (upstream issue #44).
- Diagnostic **Raw register N** sensors for 26 registers that are already read but not decoded
  (15202-15204, 15218, 20006-20008, 20117, 25204, 25220, 25224, 25227, 25228, 25232, 25236,
  25243, 25244, 25269-25273, 25275, 25276, 25278, 25279); disabled by default for new installs.
- Beginner-friendly README, register findings table, this changelog.

### Changed
- Grid max charger current range 20-30 A -> **20-40 A** (upstream issue #105).
- Integration name "Must Inverter Extended"; documentation / issue links point here.

### Fixed
- Undocumented enum values (e.g. charging state 5 or 8) report *unknown* instead of raising
  `IndexError` every poll and freezing the sensor.
- `serial_number` is passed to the device registry as text - required from **HA 2026.12**
  (upstream issue #119). The device identifier is unchanged, so existing devices keep their ids.
- A cancelled or failed read no longer leaves the integration stuck ("previous read still in
  progress" on every poll until restart).
- The Modbus client is closed when setup fails, so retries don't hit "Could not exclusively lock
  port" (upstream PR #117).
- No `KeyError` when nothing at all could be read (inverter off) - setup retries cleanly
  (upstream PR #117).

- `aiofiles` requirement relaxed from `==24.1.0` to `>=24.1.0` - the exact pin conflicts with
  current Home Assistant (which ships 25.1.0) and fails hassfest validation.
- hassfest: declare `CONFIG_SCHEMA` (config-entry only).
- Bare `except:` in the read loop replaced by `except Exception:` (cancellation is still re-raised).

### Removed
- Dependabot config and the daily scheduled validation run (validation still runs on every push).
