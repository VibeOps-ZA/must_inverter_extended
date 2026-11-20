# Changelog

All notable changes to **Must Inverter Extended** are listed here.
Versions before 1.0.0 are the original [ha-must-inverter](https://github.com/mukaschultze/ha-must-inverter)
releases by @mukaschultze - see its [releases page](https://github.com/mukaschultze/ha-must-inverter/releases).

## [1.1.0] - unreleased

Reliability and safety release after a full code review. **No entity is renamed or removed and
every existing entity id and unique id stays exactly as it was.** One entity is added (*Connected*).
Needs **Home Assistant 2025.9 or newer**. One Home Assistant restart is needed after updating.

### Added
- **Connected** binary sensor (diagnostic). On while the inverter answers; off after 5 polls in a
  row without any answer (75 seconds at the default 15-second scan interval), on again with the
  first answer. It is always available, so it is the entity to build an "inverter offline" alert
  on. Attribute `missed_polls` counts from 0 to 5.
- **Raw value on state sensors.** *Charging state*, *MPPT state*, *Charger work state* and *Work
  state* carry the number the inverter sent in the attribute `raw_value`. Values without a
  documented meaning (charging state 3, 5 and 8 on a PV18-4024PREM) show as *unknown* - no label
  is guessed - but the number is no longer lost.
- **Allow calibration writes (expert)** option, off by default (Configure > PyModbus advanced
  settings).
- Automated tests (`tests/`, about 290 checks) that need neither Home Assistant nor an inverter:
  number formats and scaling against a recorded poll of a PV18-4024PREM, both fault registers, the
  poll loop and every entity against a scripted fake inverter (blank answers, late replies, outages,
  refused writes), and a list of the entity keys of a real installation that must never change.
  They run on every pull request.

### Changed
- **Values are no longer shown for ever when the inverter stops answering.** Before, every entity
  kept its last value for as long as the inverter was off, unplugged or not answering - state of
  charge, power and voltages looked current, and "Integral" helpers kept adding energy from a
  frozen power value. Now a value is shown only while the register block it comes from has been
  read in one of the last 5 polls; after that the entity is *unavailable* until the inverter
  answers again. One or two missed polls change nothing.
  **Check your automations and templates:** a numeric condition on an unavailable entity is false,
  and templates should use a default, e.g. `states('sensor.x') | float(0)`.
- **Charging state 3 is no longer shown as "Equalization charge".** For these inverters only 0
  (stop), 1 (absorb charge) and 2 (float charge) are defined - in the Must protocol document and,
  as reported from the vendor's SolarPowerMonitor 2.2.81, in its table for this inverter family;
  "EQ charge" for 3 exists only in its table for PC1800 solar charge controllers. On a
  PV18-4024PREM, 3 appears with the MPPT off near full charge, not during equalization. It now
  shows as *unknown*, like 5 and 8, with the number in `raw_value`. Nothing else changes: the
  entity and its id are the same, the sensor has no long-term statistics, and history recorded
  earlier still reads "Equalization charge". **If an automation waits for the state
  `equalization_charge`, it will no longer trigger** - use the attribute instead, e.g.
  `state_attr('sensor.your_inverter_charging_state', 'raw_value') == 3`.
- **Calibration values are write-protected.** The eight calibration numbers (disabled by default)
  change how the inverter measures its own voltages and currents. Changing one is now refused with
  an explanation unless the new expert option is on.
- **Entity categories.** Settings (numbers, selects, switches, buttons, time entities) are in the
  *Configuration* block of the device page; model, serial number, versions, ratings, parallel
  values and read-only settings are in the *Diagnostic* block. Measurements, energy counters,
  states and the fault and warning messages are unchanged. Categorised entities are not offered to
  voice assistants or put on automatically generated dashboards by default; what you have already
  exposed or placed on a dashboard is not touched, and the entity ids are the same.
- **Minimum Home Assistant version is 2025.9** (was stated as 2025.1). The integration needs the
  Modbus library version that first shipped with 2025.9.

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
- **Battery state of charge / health frozen after an outage.** When the inverter did not answer for
  3 polls (45 seconds), the integration concluded that there was no BMS and stopped reading
  registers 113-114 until Home Assistant was restarted - the last percentage stayed on screen.
  Failed reads now only count while the rest of the inverter answers.

### Known limitation
- The charger error text "PV voltage is too low" (register 15213, bit 5) comes from the table for
  PC1800 solar charge controllers and is not confirmed for these inverters. It is shown as before.

### Removed
- The unused register monitor (`utils/register_monitor.py`, never started) and the `aiofiles`
  requirement that only it needed.

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
