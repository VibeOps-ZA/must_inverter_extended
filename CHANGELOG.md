# Changelog

All notable changes to **Must Inverter Extended** are listed here.
Versions before 1.0.0 are the original [ha-must-inverter](https://github.com/mukaschultze/ha-must-inverter)
releases by @mukaschultze - see its [releases page](https://github.com/mukaschultze/ha-must-inverter/releases).

## [1.0.4] - unreleased

Reliability fixes found in a code review. No entity is renamed, added or removed: every entity id
and unique id stays exactly as it was.

### Fixed
- **Inverter faults from the second fault register were never shown.** A missing comma joined two
  fault texts, which made the integration decode only register 25261. Faults reported in 25262 -
  radiator over temperature, grid voltage or frequency out of range, bus voltage too low, over
  current protection, battery connection open and others - left the *Error message inverter* sensor
  on "No errors". Both registers are decoded now, and bit 15 of the first one reads "Inverter grid
  over current error" instead of two texts glued together.
- **An inverter that answers "all zeroes" is no longer believed.** A Must inverter that has shut
  itself down answers every register with 0 until it is fully powered off and on. Taken as real
  data, that set the serial number to 0 - Home Assistant starting in that state created a whole new
  set of entities - and dropped the lifetime energy counters to 0, after which Home Assistant
  counted the complete totals a second time in the Energy dashboard. Answers that are all 0 or all
  65535 in a block that always holds fixed values are now ignored (the previous values are kept and
  one warning is logged), and at start-up the integration waits and retries instead.
- **A serial number that changes while Home Assistant is running is ignored** (damaged answer). It
  could raise the "No serial number set" repair by mistake.
- **A write the inverter refuses now fails visibly.** Before, the entity showed the new value until
  the next poll and automations carried on as if the setting had changed. The service call now ends
  with an error naming the register.
- **One late reply no longer spoils the rest of the poll or raises the repair.** A reply arriving
  after its request had been repeated was taken as the answer to the next request, shifting every
  later reply by one; each shifted reply counted as a mismatch, so one event could raise "Mismatched
  Modbus Registers" by itself. The integration now pauses for a second after such a reply (and after
  any answer that needed a retry) so the late reply is thrown away, and counts one mismatch per poll.
- **PV1900:** PV1 current and power (15207-15208) are taken from the 15201-15221 block that is read
  anyway instead of a second read. Both that read and battery SoC/SoH (113-114) were 2 registers
  long, so a late reply to one could be shown as the other.
- **Select entities** (energy use mode, battery type, charger source priority ...) report *unknown*
  for a value without a documented meaning instead of raising `IndexError` on every poll.
- **Number entities missing after an incomplete first read.** If the battery voltage class or rated
  current had not been read when Home Assistant started, all number entities failed to load until
  the integration was reloaded. Home Assistant now retries them by itself.
- **"No serial number set" repair:** the new serial number is written to the inverter first and
  Home Assistant is only updated when that worked; only the serial number at the start of each
  unique id is replaced (with an old serial of 0 every "0" in the id was replaced); the value must
  be between 1 and 4294967294.
- **Diagnostics download no longer contains the serial number** in the raw register list
  (20002-20003 and a copy in 25269-25270; 20001-20003 on PH1100) or in the state of the serial
  number sensor.
- **Scan interval** must be at least 1 second (0 polled without a pause).

### Added
- Automated tests (`tests/`, 224 checks) that need neither Home Assistant nor an inverter: number
  formats and scaling against a recorded poll of a PV18-4024PREM, both fault registers, the poll
  loop against a scripted fake inverter (blank answers, late replies, refused writes), and a list of
  all 156 entity keys of a real installation that must never change. They run on every pull request.

## [1.0.3] - 2026-10-21

### Fixed
- **"error reading modbus data at address ..." and "Task could not be canceled ... MustInverter._async_refresh"
  logged on every Home Assistant restart.** Polling carried on while Home Assistant was shutting down, so
  the last reads failed and one read task could not be cancelled. Polling now stops as soon as Home
  Assistant starts shutting down; a read that is already running finishes quietly (logged at debug level).
  Writes still work during shutdown, so an automation that writes a safe setting when Home Assistant stops
  is not affected.

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
