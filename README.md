# Must Inverter Extended (Home Assistant)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=VibeOps-ZA&repository=must_inverter_extended&category=integration)

**Must Inverter Extended** is a patched, drop-in variant of the excellent
[**ha-must-inverter**](https://github.com/mukaschultze/ha-must-inverter) integration by
[@mukaschultze](https://github.com/mukaschultze). It lets Home Assistant read and control Must
solar inverters (PV1800 / PV18, PV1900 / PV19, PH1100 / PH11 and compatible models).

> **Why does this exist?** The original project is great but has been mostly idle since its
> v0.2.5 release (April 2026), while some bugs and pending fixes stay unmerged. This variant keeps
> the original code and history, and adds:
>
> - **Extended registers** - battery SoC / SoH from a CAN/RS485 BMS on PV1800 units, the
>   inverter's own SOC switch thresholds, battery charge/discharge power, and diagnostic "raw
>   register" sensors for research.
> - **Stability fixes** - no more endless "previous read still in progress", the serial port is
>   released when setup fails, undocumented values no longer crash sensors.
> - **Home Assistant version fixes** - the serial-number change required by HA 2026.12.
>
> All credit for the original integration goes to **@mukaschultze** and the people credited in
> [Acknowledgments](#acknowledgments). Fixes here are offered back upstream.

It uses the same integration domain (`must_inverter`) as the original, so it **replaces** it:
your existing devices, entities, dashboards and automations keep working unchanged.

---

## Contents

1. [What's different from the original](#whats-different-from-the-original)
2. [What you need](#what-you-need)
3. [Connecting the inverter to Home Assistant](#connecting-the-inverter-to-home-assistant)
4. [Installing](#installing)
5. [Switching from the original integration](#switching-from-the-original-integration)
6. [Setting it up (every option explained)](#setting-it-up-every-option-explained)
7. [What you get (entities)](#what-you-get-entities)
8. [Is the inverter answering?](#is-the-inverter-answering)
9. [Battery in the Energy dashboard](#battery-in-the-energy-dashboard)
10. [Safety - read this before changing settings](#safety---read-this-before-changing-settings)
11. [Register findings (for other models and researchers)](#register-findings-for-other-models-and-researchers)
12. [Troubleshooting](#troubleshooting)
13. [For developers: running the tests](#for-developers-running-the-tests)
14. [Acknowledgments](#acknowledgments), [Repair: Mismatched Modbus Registers](#repair-mismatched-modbus-registers)
    and [License](#license)

---

## What's different from the original

| Area | Original v0.2.5 | Extended |
| --- | --- | --- |
| Undocumented enum values (e.g. Charging state = 5) | `IndexError` every poll, sensor freezes | Sensor shows *unknown*, logged once |
| PV1800 + lithium battery with BMS (CAN/RS485) | No SoC / SoH | **Battery state of charge** and **state of health** (registers 113-114). Auto-skipped after 3 failed reads on inverters without a BMS link |
| SOC switch thresholds (20147 / 20148) | Not exposed | **SOC back to grid** and **SOC back to battery** number entities |
| Grid max charger current | 20-30 A | 20-40 A (tested on a 4 kW PV18-4024PREM) |
| Battery charge / discharge power | Only signed "battery power" | Two extra sensors (>= 0 W) for the Energy dashboard (disabled by default) |
| Undecoded registers already being read | Hidden | "Raw register N" diagnostic sensors (disabled by default) - no extra reads |
| Read stuck after an error | All later polls skipped until restart | Always recovers on the next poll |
| Setup failure | Serial port stays locked until HA restarts | Port is closed, retry works (upstream PR #117) |
| Inverter powered off at start-up | `KeyError` | Clean "no data" retry (upstream PR #117) |
| Home Assistant restart | Polling continues during shutdown: modbus read errors and a read task HA can't cancel | Polling stops when shutdown starts; nothing logged |
| Serial number | Passed as a number - breaks in **HA 2026.12** | Passed as text (upstream issue #119) |
| Inverter faults | Only the first fault register is decoded - over temperature, grid and battery-connection faults show "No errors" | Both fault registers are decoded |
| Inverter answers "all zeroes" (after it shut itself down) | Taken as real: serial number 0, energy totals 0, then counted twice in the Energy dashboard | Ignored - previous values are kept, a warning is logged |
| A setting the inverter refuses | Looks like it worked | The action fails with an error message |
| Diagnostics download | Contains the serial number in the raw registers | Serial number hidden |
| Inverter off, unplugged or not answering | Every entity keeps its last value for ever | Entities turn *unavailable* after 5 missed polls; a **Connected** sensor shows whether the inverter answers |
| Calibration values | Can be changed like any other number once enabled | Write-protected unless an expert option is turned on |
| Charging state without a documented meaning (5, 8) | `IndexError` | *unknown*, with the raw number in the attribute `raw_value` |
| Battery SoC / SoH after an outage of 45 seconds | - | Read again when the inverter is back (was frozen until a restart) |

Full history: [CHANGELOG.md](CHANGELOG.md).

---

## What you need

1. **Home Assistant 2025.9 or newer** (older versions ship a Modbus library that is too old for
   this integration). New to it? Start at
   [home-assistant.io/installation](https://www.home-assistant.io/installation/).
2. **HACS** (the Home Assistant Community Store) to install and update this integration - see
   [hacs.xyz/docs/use](https://hacs.xyz/docs/use/). Manual install also works (below).
3. **A Must inverter** that speaks the Must Modbus protocol (PV1800/PV18, PV1900/PV19,
   PH1100/PH11, and very likely PH1800 / EP1800 series).
4. **A data connection** between the inverter and Home Assistant - see the next section.

---

## Connecting the inverter to Home Assistant

The inverter talks Modbus over its communication port. You have two common options:

- **USB / serial cable (most reliable).** Plug the inverter's USB (or RS232 via a USB adapter)
  port into the machine running Home Assistant. On Home Assistant OS it usually appears as
  `/dev/ttyUSB0`. You can find the exact name under **Settings > System > Hardware > All
  hardware**.
- **Network (TCP or UDP).** Use an RS485/RS232-to-Wi-Fi or Ethernet adapter (Elfin, USR, etc.)
  and point the integration at its IP address and port (usually 502).

Wiring photos, pin-outs and many working setups are collected in the original project's
[connection guide thread (issue #36)](https://github.com/mukaschultze/ha-must-inverter/issues/36).

> **One reader at a time.** If something else (another logger, the vendor's Wi-Fi stick, a second
> integration) polls the same port at the same moment, reads get mixed up and you will see
> "wrong number of registers" warnings. See
> [upstream issue #47](https://github.com/mukaschultze/ha-must-inverter/issues/47).

---

## Installing

### With HACS (recommended)

1. Open **HACS** in Home Assistant.
2. Click the three dots (top right) > **Custom repositories**.
3. Paste `https://github.com/VibeOps-ZA/must_inverter_extended`, choose type **Integration**,
   click **Add**. (Or click the blue "Open in HACS" button at the top of this page.)
4. Find **Must Inverter Extended** in HACS and click **Download**.
5. **Restart Home Assistant** (Settings > System > three dots > Restart).

### Manual

1. Download `must_inverter.zip` from the
   [latest release](https://github.com/VibeOps-ZA/must_inverter_extended/releases/latest).
2. Unzip it into `config/custom_components/must_inverter/` (create the folders if needed), so you
   end up with `config/custom_components/must_inverter/__init__.py` and friends.
3. Restart Home Assistant.

---

## Switching from the original integration

Because both use the domain `must_inverter`, **only one can be installed**. Your configuration and
entities live in Home Assistant, not in the integration files, so nothing is lost.

1. *(Optional but wise)* make a backup: **Settings > System > Backups > Back up now**.
2. In HACS, add this repository as a custom repository (step 2-3 above).
3. Open **Must Inverter Extended** in HACS and click **Download**. It overwrites the files in
   `custom_components/must_inverter`.
4. In HACS, open the original **Must Inverter** entry and stop tracking it (three dots >
   **Remove**) **only if** HACS still shows it as installed *after* step 3 - otherwise HACS may
   later offer an upstream update that overwrites the extended files.
5. Restart Home Assistant. Your device, entity IDs, history, dashboards and automations stay the
   same.

---

## Setting it up (every option explained)

**Settings > Devices & services > Add integration > Must Inverter Extended**
(it may still be listed as "Must Inverter").

### Step 1 - general

| Option | What it means | Typical value |
| --- | --- | --- |
| Name | Optional friendly name for the device. Leave empty to use the model name. | *(empty)* |
| Model | `autodetect` reads the model from the inverter. Pick `pv1800`, `pv1900` or `ph1100` if detection is wrong. | `autodetect` |
| Scan interval | Seconds between reads. Lower = more detail but more load; below ~5 s you may get "previous read still in progress". | `15` |
| Mode | How you connected: `serial` (USB/RS232), `tcp` or `udp` (network adapter). | `serial` |

### Step 2a - serial (USB) connection

| Option | Meaning | Typical value |
| --- | --- | --- |
| Device | Serial port path. Prefer the stable `/dev/serial/by-id/...` path if you have several USB devices. | `/dev/ttyUSB0` |
| Baudrate | Communication speed. | `19200` |
| Parity | `N` (none), `E` (even) or `O` (odd). | `N` |
| Stop bits | | `1` |
| Byte size | Data bits. | `8` |

### Step 2b - TCP / UDP (network adapter)

| Option | Meaning | Typical value |
| --- | --- | --- |
| Host | IP address of the RS485/RS232 network adapter. | e.g. `192.168.1.50` |
| Port | Modbus port configured on the adapter. | `502` |

### Step 3 - Modbus

| Option | Meaning | Typical value |
| --- | --- | --- |
| Timeout | Seconds to wait for each answer. | `2.0` |
| Retries | Retries per request before giving up. | `3` |
| Reconnect delay / max | Seconds before reconnecting after a dropped connection (grows up to "max"). | `0.3` / `1.0` |
| Device ID | Modbus slave address of the inverter. Must inverters use **4**. | `4` |
| Allow calibration writes (expert) | Leave **off**. Only while this is on can the eight *Calibration ...* numbers be changed; they alter how the inverter measures its own voltages and currents (see [Safety](#safety---read-this-before-changing-settings)). | off |

You can change all of these later under the integration's **Configure** button.

---

## What you get (entities)

Entity names depend on your model. Typical groups:

- **Sensors** - PV voltage/current/power, battery voltage/current/power, grid and load values,
  temperatures, work state, charger state, energy counters, rated values.
- **Battery (extended)** - *Battery state of charge* and *state of health* when your inverter has a
  BMS link (CAN/RS485 lithium battery). *Battery charge power* / *Battery discharge power*
  (disabled by default - enable them under the entity's settings).
- **Numbers** (settings) - float/absorption voltages, charger currents, grid charger current,
  switch-to-grid / back-to-battery voltages, **SOC back to grid** / **SOC back to battery**
  (extended), output voltage/frequency, calibration values (disabled by default).
- **Selects / switches / time / buttons** - energy use mode (SBU / SUB / UTI / SOL), charger
  source priority, battery type, buzzer, overload restart, schedules, reset accumulated data.
- **Diagnostic "Raw register N"** (extended, disabled by default) - raw values of registers the
  integration already reads but does not decode yet. Useful for decoding new features; they cause
  **no** extra Modbus traffic.
- **Connected** (extended) - a binary sensor that is on while the inverter answers. See
  [Is the inverter answering?](#is-the-inverter-answering) below.

On the device page the entities are grouped: measurements under **Sensors**, everything you can
change under **Configuration**, and descriptive values (model, serial number, versions, ratings,
*Connected*, raw registers) under **Diagnostic**.

The state sensors *Charging state*, *MPPT state*, *Charger work state* and *Work state* also carry
the number the inverter sent, in the attribute `raw_value` (open the entity and expand
**Attributes**). If the inverter sends a number that has no documented meaning, the sensor shows
*unknown* and the number is still there.

To enable a disabled entity: **Settings > Devices & services > Must Inverter > (your device) >**
"*+N entities not shown*" > pick the entity > **Settings (cog) > Enabled**.

---

## Is the inverter answering?

Home Assistant reads the inverter every *scan interval* (15 seconds by default). Sometimes a read
fails - the cable is unplugged, the inverter is switched off, or Home Assistant is busy.

- **One to four failed reads in a row:** nothing changes. The entities keep their last value.
- **Five failed reads in a row** (75 seconds by default): the values are too old to trust. The
  entities show **unavailable** and the **Connected** binary sensor turns **off**. As soon as the
  inverter answers again, everything comes back by itself.
- If only one group of values stops answering (for example the battery management system), only
  the entities of that group turn unavailable; *Connected* stays on.

To be told when the inverter goes offline, create an automation
([Home Assistant automation basics](https://www.home-assistant.io/docs/automation/basics/)):

1. **Settings > Automations & scenes > Create automation > Create new automation.**
2. **When:** *Entity* > *State*, entity **Connected** of your inverter, **To:** *Disconnected*,
   **For:** 2 minutes.
3. **Then do:** *Notifications* > *Send a notification* to your phone
   ([companion app](https://companion.home-assistant.io/docs/notifications/notifications-basic/)),
   with a message such as "The inverter is not answering".
4. Save.

If you use values of this integration in your own automations or templates, remember that they can
now be *unavailable*: give templates a default, e.g.
`{{ states('sensor.your_inverter_battery_state_of_charge') | float(0) }}`.

---

## Battery in the Energy dashboard

Home Assistant's Energy dashboard wants *energy* (kWh) for battery charge and discharge.

1. Enable **Battery charge power** and **Battery discharge power** (see above).
2. Create two **Integral** helpers - **Settings > Devices & services > Helpers > Create helper >
   Integral sensor** ([docs](https://www.home-assistant.io/integrations/integration/)):
   - Input sensor: *Battery charge power*, method **Left**, metric prefix **k**, time unit
     **hours**. Name it e.g. "Battery energy in".
   - Repeat for *Battery discharge power* ("Battery energy out").
3. **Settings > Dashboards > Energy > Battery systems > Add battery system** and pick the two
   helpers ([Energy dashboard docs](https://www.home-assistant.io/docs/energy/battery/)).

---

## Safety - read this before changing settings

- This integration **does not write anything** to the inverter unless *you* change an entity
  (number, select, switch, time, button).
- Some settings (especially **calibration** values) cannot be easily undone and can upset the
  inverter. They are disabled by default - leave them alone unless you know exactly why.
- The eight **Calibration ...** numbers are also **write-protected**: changing one is refused
  until you turn on *Allow calibration writes (expert)* under the integration's **Configure**
  button. They tell the inverter how to correct its own voltage and current measurements; a wrong
  battery-voltage calibration makes it charge the battery too high or too low. Turn the option off
  again when you are done.
- The two **Remove accumulated data** buttons (disabled by default) erase the inverter's lifetime
  energy counters. This cannot be undone.
- **Battery equalization** is meant for lead-acid batteries. Leave it off for lithium batteries.
- **Note your settings first.** Write down (or screenshot) every number/select value before you
  experiment, so you can restore them. Some inverters reset to factory defaults after certain
  writes.
- The code **never reads** register ranges 10009-10100 or 20017-20100. Reading those can shut a
  Must inverter down until it is fully powered off. Don't add them.
- The inverter enforces its own limits: for example writing 25 % to *SOC back to battery* may be
  stored as 32 %, and 5 % to *SOC back to grid* as 12 %. Check the value after writing.

---

## Register findings (for other models and researchers)

Collected on a **PV18-4024PREM** (fw 2.35.16, 24 V, CAN lithium BMS). Other models may differ -
please open an issue with your results.

| Register | Finding |
| --- | --- |
| 113-114 | Battery SoC / SoH from the BMS (same as PV1900). Not served without a BMS link. |
| 44180 | Reported for PH18 + Pylontech as SoC; returns 0 on PV18. |
| 15104-15119 | PH1100 BMS block - all zeros on PV18. |
| 15202 | MPPT on/off state. |
| 15203 | Charging state. Undocumented values: **5** while MPPT (15202) = 1, **3** while MPPT = 0 near full (charger cycling at the BMS limit), **8** once when SoC reached 100 %. |
| 20117 | Low-battery warning voltage (= switch-to-grid voltage 20118 - 0.3 V). |
| 20145 / 20146 | Probably SOC-mode enable (1) and low-SOC cut-off (10 %). Not exposed. |
| 20147 / 20148 | SOC back to grid / back to battery (%). The inverter switches to grid when SoC <= 20147 and, once latched, stays on grid while SoC < 20148. Lowering 20148 below the current SoC releases back to battery after ~8-9 minutes. |
| 25269-25272 | Copies of the serial number (25269-25270) and of the hardware / software version (25271-25272). |
| 25273 | Battery power in W (negative = charging). |
| 25275 | 24 - likely the battery voltage class (24 V). |
| 25278 | Same value as 20006 (version-like, 10414). |

Other observations:

- **Utility mode alone doesn't transfer to grid**; the inverter needs its "low battery" state.
  Temporarily raising the switch-to-grid voltage (20118) above the battery voltage triggers it,
  and it keeps grid-charging after 20118 is restored.
- The transfer to grid **does not happen while the PV charger is still delivering power**; wait
  until PV is at 0 W (e.g. after sunset).
- Pending upstream ideas worth watching: scaling the grid charger range with the rated current
  ([PR #118](https://github.com/mukaschultze/ha-must-inverter/pull/118)).

---

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Integration won't start, "Unable to connect" | Check the device path / IP, cable, and that nothing else uses the port. |
| "wrong number of registers" warnings | Another device is polling the same port - remove it ([#47](https://github.com/mukaschultze/ha-must-inverter/issues/47)). |
| "previous read still in progress" | Increase the scan interval (15 s is a good start). |
| Battery SoC / SoH unavailable | Your inverter has no BMS link (or uses a different register). The log says so once, after 3 tries. |
| Settings changed by themselves | Some Must firmware resets settings after certain writes - restore from your notes. |
| Log says "ignoring an implausible answer ... every register is 0" | The inverter answered with empty data and the integration kept the last real values. If it does not stop, the inverter has probably shut itself down: switch off PV, grid and battery, wait a minute, and switch it back on. |
| Changing a setting fails with "The inverter refused to write ..." | The inverter did not accept that value (out of its own limits, or not allowed in the current mode). Nothing was changed. |
| All inverter entities are *unavailable* and *Connected* is off | The inverter has not answered for 5 reads in a row. Check that it is on, the cable is plugged in at both ends, and nothing else uses the port. Everything comes back by itself with the first answer. |
| *Charging state* shows *unknown* | The inverter sent a number that the Must documentation does not explain (5 and 8 were seen on a PV18-4024PREM with a lithium BMS). The number is in the sensor's `raw_value` attribute. |
| Changing a *Calibration ...* number fails with "write-protected" | Intended - see [Safety](#safety---read-this-before-changing-settings). |
| More detail needed | Add to `configuration.yaml`: `logger: { logs: { custom_components.must_inverter: debug } }` and restart. |

Bugs and ideas: [open an issue](https://github.com/VibeOps-ZA/must_inverter_extended/issues).

---

## For developers: running the tests

The decoding and safety logic is covered by tests that need neither Home Assistant nor an
inverter - only [Python](https://www.python.org/downloads/) 3.13 or newer and
[pytest](https://docs.pytest.org/en/stable/getting-started.html):

```bash
python3 -m pip install pytest
python3 -m pytest
```

They use one poll recorded from a real PV18-4024PREM (`tests/fixtures/`, serial number replaced)
and a list of the entity keys of a real installation (`tests/golden/`). A change that would rename
or drop an existing entity fails the tests. They also run automatically on every pull request.

---

## Acknowledgments

- [**@mukaschultze**](https://github.com/mukaschultze) - author of the original
  [ha-must-inverter](https://github.com/mukaschultze/ha-must-inverter), on which this is built
  (all original history is preserved in this repository). Consider
  [buying him a coffee](https://www.buymeacoffee.com/mukaschultze).
- Original reverse-engineering work credited upstream:
  [aquarat/must_inverter](https://github.com/aquarat/must_inverter),
  [dylangmiles/docker-must-homeassistant](https://github.com/dylangmiles/docker-must-homeassistant),
  [thelabexpedition67/MustInverterDataHandler](https://github.com/thelabexpedition67/MustInverterDataHandler).
- Upstream contributors whose pending fixes are included: PR #117 (taransergey).

This project is not affiliated with Must Solar. Use at your own risk.

## Repair: Mismatched Modbus Registers

Home Assistant shows this repair when the inverter's replies don't match what the integration
asked for **in at least 3 polls within 10 minutes** (ignored for the first 2 minutes after Home
Assistant starts). It clears itself after 10 good reads in a row.

A single mismatch right after a restart is normal: Home Assistant is busy while starting or
stopping, a request times out, and its late reply arrives while the next request is waiting.
Since 1.0.1 the integration flushes the serial buffer to recover and does not raise the repair
for these.

If the repair keeps coming back, check:
1. **Only one reader on the port.** No second integration, add-on/app (e.g. Solar Assistant), or
   WiFi/RS485 dongle polling the same inverter port at the same time.
2. **Cabling.** Short, good-quality USB/RS485 cable; no loose connectors.
3. **Timeout/retries** in the integration options: raise the timeout if your link is slow.

## License

MIT - see [LICENSE](LICENSE). Original copyright (c) 2024 Samuel Schultze; modifications
(c) 2026 VibeOps-ZA.
