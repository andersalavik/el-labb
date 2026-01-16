# El-labb

A web-based tool for drawing and simulating AC/DC schematics with a component library, multimeter, contactors, motors, timers, and PLC logic.

## Features

- Drag-and-drop components from the library.
- AC 1-phase, AC 3-phase (Y/Delta), and DC sources.
- Contactors (standard and changeover) with configurable pole count.
- Lamps with configurable light color.
- Multimeters that remain in the schematic.
- Server-side simulation (Flask).
- Save and load labs as JSON.
- Wire bend points (add/drag/remove).
- Manual canvas resize (saved in the lab).
- Simulation debug log.
- PLC component with LAD-text and live PLC debug.
- UI language support (Swedish/English).

## Requirements

- Python 3.10+

## Run locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the server:

```bash
python app.py
```

Open:

```
http://127.0.0.1:5000
```

## Usage

- Choose a tool: Select, Wire, Multimeter, Erase.
- Add components from the library by clicking a component, then clicking the canvas.
- Draw wires between terminals.
- Add wire bend points:
  - While drawing: click on empty canvas to add points.
  - After drawing: double-click a wire to create a new bend point.
  - Drag bend points to adjust. In Erase mode they can be removed.
- Start simulation with `Run simulation` and toggle `Sim mode`.
- Multimeter: choose a mode and click components/terminals.
- Save labs in the “Save & load” panel.
- Resize the canvas by dragging the handle in the lower-right corner.

## Timers

There are two timer types:

- **Timer (coil-driven)**: When the coil is energized the timer starts counting down. After the delay it switches its contact (C/NO/NC). You can choose loop or one-shot. If the coil loses power, it resets to its initial state.
- **Timer (clock)**: Uses the computer’s local time. You set a start and stop time (HH:MM) and it opens/closes accordingly.

Tip: In simulation mode, timers update their labels (remaining time or ON/OFF).

## PLC programming (LAD text)

The PLC component can be programmed with a simple LAD-style text format inspired by Siemens.

### Addressing and comments

- Addresses are 1-based: `I1..I64`, `Q1..Q64`, `M1..`, `T1..`, `C1..`.
- Comments can be written with `;` (everything after `;` is ignored).

### Instructions

- `A I1` – AND with input I1
- `AN I2` – AND NOT with input I2
- `U I1` – AND (Siemens alias for A)
- `UN I2` – AND NOT (Siemens alias for AN)
- `O I3` – OR with input I3
- `ON I4` – OR NOT with input I4
- `= Q1` – Assign to output Q1 from current logic result
- `= M1` – Assign to memory bit M1 from current logic result
- `S Q1` / `R Q1` – Set/Reset output
- `S M1` / `R M1` – Set/Reset memory
- `L I1` – Load operand into accumulator
- `T Q1` – Transfer accumulator to Q1/M1
- `MOVE I1 Q1` – Move value from I1 to Q1/M1
- `R_TRIG M1` – Rising edge, writes pulse to M1 or Q1
- `F_TRIG M1` – Falling edge, writes pulse to M1 or Q1
- `CTU C1 PV=5` – Count up, Q becomes true at PV
- `CTD C1 PV=5` – Count down, Q becomes true when CV <= 0
- `R C1` – Reset counter
- `TON T1 2.5` – On-delay (seconds)
- `TOF T1 2.5` – Off-delay (seconds)
- `TP T1 2.5` – Pulse (seconds)

### Examples

```
A I1
AN I2
= Q1
```

Q1 is true when I1 is true and I2 is false.

Timer example:

```
A I1
TON T1 3.0
= Q1
```

Q1 becomes true 3 seconds after I1 goes true.

Memory example:

```
A I1
= M1

A M1
= Q1
```

Counter example:

```
A I1
CTU C1 PV=3
= Q1
```

Q1 becomes true after three pulses on I1.

MOVE example:

```
MOVE I1 Q1
```

### PLC debug

- Use the **PLC debug** button in the properties panel to see how the PLC “thinks”.
- The debug view shows each line, ACC value, and an input/output summary after each scan.

## Multimeter

- **DC**: Voltage, Current, Resistance
- **AC**: Voltage RMS, Current RMS, phase angle, P/Q/S and cos φ

Place the multimeter by selecting a mode and clicking a component or terminal.

## Contactors

- Standard (NO/NC per pole) and changeover contactor.
- Choose pole count (1–6).
- Coil A1/A2 drives the pole switching.

## Structure

- `app.py` – Flask server, simulation and API.
- `templates/index.html` – UI layout.
- `static/js/app.js` – Client logic, canvas rendering.
- `static/css/style.css` – Styling.
- `static/i18n/` – UI translations.
- `saves/` – Saved labs as JSON.

## Notes

- The project is at a very early stage and is heavily vibe-coded.
- The simulation is meant for education and visualization, not real systems.
- AC simulation supports a single frequency at a time.
