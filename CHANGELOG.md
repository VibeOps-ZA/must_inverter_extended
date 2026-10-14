# Changelog

All notable changes to **Must Inverter Extended** are listed here.
Versions before 1.0.0 are the original [ha-must-inverter](https://github.com/mukaschultze/ha-must-inverter)
releases by @mukaschultze - see its [releases page](https://github.com/mukaschultze/ha-must-inverter/releases).

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

### Removed
- Dependabot config and the daily scheduled validation run (validation still runs on every push).
