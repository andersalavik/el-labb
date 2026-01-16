import json
import re
import math
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
SAVES_DIR = Path(app.root_path) / "saves"
SAVES_DIR.mkdir(parents=True, exist_ok=True)
EPSILON_V = 1e-2
FAULT_MIN_V = 0.1
FAULT_TOLERANCE = 0.1
SHUNT_RESISTANCE = 1e9


class Complex:
    def __init__(self, re=0.0, im=0.0):
        self.re = float(re)
        self.im = float(im)

    def __add__(self, other):
        o = to_complex(other)
        return Complex(self.re + o.re, self.im + o.im)

    def __sub__(self, other):
        o = to_complex(other)
        return Complex(self.re - o.re, self.im - o.im)

    def __mul__(self, other):
        o = to_complex(other)
        return Complex(self.re * o.re - self.im * o.im, self.re * o.im + self.im * o.re)

    def __truediv__(self, other):
        o = to_complex(other)
        denom = o.re * o.re + o.im * o.im
        return Complex((self.re * o.re + self.im * o.im) / denom, (self.im * o.re - self.re * o.im) / denom)

    def __abs__(self):
        return math.hypot(self.re, self.im)

    def conjugate(self):
        return Complex(self.re, -self.im)


def to_complex(value):
    if isinstance(value, Complex):
        return value
    return Complex(value, 0.0)


def complex_from_polar(magnitude, degrees):
    angle = math.radians(degrees)
    return Complex(magnitude * math.cos(angle), magnitude * math.sin(angle))


@app.get("/")
def index():
    return render_template("index.html")


def _load_save(path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _safe_name(name):
    return re.sub(r"[^a-zA-Z0-9 _-]", "", name).strip()


def _list_saves():
    saves = []
    for path in SAVES_DIR.glob("*.json"):
        data = _load_save(path)
        if not data:
            continue
        saves.append(
            {
                "id": data.get("id", path.stem),
                "name": data.get("name", path.stem),
                "updatedAt": data.get("updatedAt", 0),
            }
        )
    return sorted(saves, key=lambda item: item["updatedAt"], reverse=True)

def get_terminal_count(component):
    comp_type = component.get("type")
    if comp_type == "contactor":
        props = component.get("props", {})
        poles = props.get("poles") or ["NO"]
        if props.get("contactType", "standard") == "changeover":
            return 2 + 3 * len(poles)
        return 2 + 2 * len(poles)
    if comp_type == "timer":
        return 5
    if comp_type == "time_timer":
        return 3
    if comp_type == "voltage_source":
        props = component.get("props", {})
        supply = props.get("supplyType", "DC")
        if supply == "AC3":
            if props.get("connection", "Y") == "Delta":
                return 3
            return 4
        return 2
    if comp_type == "switch_spdt":
        return 3
    if comp_type == "motor_3ph":
        return 3
    if comp_type == "node":
        return 4
    if comp_type == "ground":
        return 1
    return 2


def _terminal_exists(component, index):
    return index < get_terminal_count(component)


def build_terminal_nodes(components, wires, contactor_states):
    terminal_nodes = {}
    terminals = []
    used_terminals = set()

    comp_lookup = {comp["id"]: comp for comp in components}

    for wire in wires:
        from_comp = comp_lookup.get(wire["from"]["compId"])
        to_comp = comp_lookup.get(wire["to"]["compId"])
        if from_comp and _terminal_exists(from_comp, wire["from"]["index"]):
            used_terminals.add(f"{wire['from']['compId']}:{wire['from']['index']}")
        if to_comp and _terminal_exists(to_comp, wire["to"]["index"]):
            used_terminals.add(f"{wire['to']['compId']}:{wire['to']['index']}")

    for comp in components:
        comp_type = comp.get("type")
        comp_id = comp.get("id")
        if comp_type == "node":
            count = get_terminal_count(comp)
            for idx in range(count):
                used_terminals.add(f"{comp_id}:{idx}")
        elif comp_type == "ground":
            used_terminals.add(f"{comp_id}:0")

    for comp in components:
        count = get_terminal_count(comp)
        for idx in range(count):
            key = f"{comp['id']}:{idx}"
            if key not in used_terminals:
                continue
            terminals.append(key)
            terminal_nodes[key] = key

    parent = {t: t for t in terminals}

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a, b):
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    for wire in wires:
        a = f"{wire['from']['compId']}:{wire['from']['index']}"
        b = f"{wire['to']['compId']}:{wire['to']['index']}"
        if a in parent and b in parent:
            union(a, b)

    ground_root = None
    for comp in components:
        if comp.get("type") == "ground":
            key = f"{comp['id']}:0"
            if key in parent:
                ground_root = find(key)
                break

    source_root = None
    if ground_root is None:
        for comp in components:
            if comp.get("type") != "voltage_source":
                continue
            count = get_terminal_count(comp)
            for idx in range(count):
                key = f"{comp['id']}:{idx}"
                if key in parent:
                    source_root = find(key)
                    break
            if source_root is not None:
                break

    virtual_ground = False
    if ground_root is None and source_root is not None:
        ground_root = source_root
        virtual_ground = True
    elif terminals and ground_root is None:
        ground_root = find(terminals[0])
        virtual_ground = True

    node_map = {}
    node_count = 0
    for key in terminals:
        root = find(key)
        if root == ground_root:
            terminal_nodes[key] = 0
            continue
        if root not in node_map:
            node_count += 1
            node_map[root] = node_count
        terminal_nodes[key] = node_map[root]

    return {"terminal_nodes": terminal_nodes, "node_count": node_count + 1, "virtual_ground": virtual_ground}


def build_model_dc(components, wires, contactor_states, timer_states):
    terminal_data = build_terminal_nodes(components, wires, contactor_states)
    if "error" in terminal_data:
        return terminal_data

    terminal_nodes = terminal_data["terminal_nodes"]
    node_count = terminal_data["node_count"]
    resistors = []
    sources = []

    for comp in components:
        comp_type = comp.get("type")
        props = comp.get("props", {})
        count = get_terminal_count(comp)
        n1 = terminal_nodes.get(f"{comp['id']}:0")
        n2 = terminal_nodes.get(f"{comp['id']}:1") if count > 1 else None

        if comp_type == "resistor":
            if n1 is None or n2 is None:
                continue
            resistors.append({"n1": n1, "n2": n2, "value": props.get("value", 1)})
        elif comp_type == "switch":
            if props.get("closed", False):
                if n1 is None or n2 is None:
                    continue
                resistors.append({"n1": n1, "n2": n2, "value": 0.01})
        elif comp_type == "push_button":
            if props.get("closed", False):
                if n1 is None or n2 is None:
                    continue
                resistors.append({"n1": n1, "n2": n2, "value": 0.01})
        elif comp_type == "switch_spdt":
            if n1 is None:
                continue
            n_up = terminal_nodes.get(f"{comp['id']}:1")
            n_down = terminal_nodes.get(f"{comp['id']}:2")
            position = props.get("position", "up")
            if position == "up" and n_up is not None:
                resistors.append({"n1": n1, "n2": n_up, "value": 0.01})
            elif position != "up" and n_down is not None:
                resistors.append({"n1": n1, "n2": n_down, "value": 0.01})
        elif comp_type == "inductor":
            if n1 is None or n2 is None:
                continue
            resistors.append({"n1": n1, "n2": n2, "value": 0.01})
        elif comp_type == "motor":
            if n1 is None or n2 is None:
                continue
            resistors.append({"n1": n1, "n2": n2, "value": props.get("value", 10)})
        elif comp_type == "motor_3ph":
            continue
        elif comp_type == "lamp":
            if n1 is None or n2 is None:
                continue
            resistors.append({"n1": n1, "n2": n2, "value": props.get("value", 80)})
        elif comp_type == "contactor":
            coil_n1 = terminal_nodes.get(f"{comp['id']}:0")
            coil_n2 = terminal_nodes.get(f"{comp['id']}:1")
            if coil_n1 is not None and coil_n2 is not None:
                resistors.append(
                    {"n1": coil_n1, "n2": coil_n2, "value": props.get("coilResistance", 120)}
                )
            poles = props.get("poles") or ["NO"]
            energized = contactor_states.get(comp["id"], False)
            if props.get("contactType", "standard") == "changeover":
                for idx in range(len(poles)):
                    n_common = terminal_nodes.get(f"{comp['id']}:{2 + idx * 3}")
                    n_no = terminal_nodes.get(f"{comp['id']}:{3 + idx * 3}")
                    n_nc = terminal_nodes.get(f"{comp['id']}:{4 + idx * 3}")
                    target = n_no if energized else n_nc
                    if n_common is None or target is None:
                        continue
                    resistors.append({"n1": n_common, "n2": target, "value": 0.01})
            else:
                for idx, pole in enumerate(poles):
                    closed = pole == "NO" if energized else pole == "NC"
                    if not closed:
                        continue
                    n1_pole = terminal_nodes.get(f"{comp['id']}:{2 + idx * 2}")
                    n2_pole = terminal_nodes.get(f"{comp['id']}:{3 + idx * 2}")
                    if n1_pole is None or n2_pole is None:
                        continue
                    resistors.append({"n1": n1_pole, "n2": n2_pole, "value": 0.01})
        elif comp_type == "timer":
            coil_n1 = terminal_nodes.get(f"{comp['id']}:0")
            coil_n2 = terminal_nodes.get(f"{comp['id']}:1")
            if coil_n1 is not None and coil_n2 is not None:
                resistors.append(
                    {"n1": coil_n1, "n2": coil_n2, "value": props.get("coilResistance", 120)}
                )
            state = timer_states.get(comp["id"], {})
            output_closed = state.get("outputClosed", False)
            n_common = terminal_nodes.get(f"{comp['id']}:2")
            n_no = terminal_nodes.get(f"{comp['id']}:3")
            n_nc = terminal_nodes.get(f"{comp['id']}:4")
            target = n_no if output_closed else n_nc
            if n_common is not None and target is not None:
                resistors.append({"n1": n_common, "n2": target, "value": 0.01})
        elif comp_type == "time_timer":
            state = timer_states.get(comp["id"], {})
            output_closed = state.get("outputClosed", False)
            n_common = terminal_nodes.get(f"{comp['id']}:0")
            n_no = terminal_nodes.get(f"{comp['id']}:1")
            n_nc = terminal_nodes.get(f"{comp['id']}:2")
            target = n_no if output_closed else n_nc
            if n_common is not None and target is not None:
                resistors.append({"n1": n_common, "n2": target, "value": 0.01})
        elif comp_type == "voltage_source":
            if props.get("supplyType", "DC") != "DC":
                continue
            if n1 is None or n2 is None:
                continue
            sources.append(
                {"n1": n1, "n2": n2, "value": props.get("value", 0), "id": comp["id"]}
            )
        elif comp_type == "switch_spdt":
            if n1 is None:
                continue
            n_up = terminal_nodes.get(f"{comp['id']}:1")
            n_down = terminal_nodes.get(f"{comp['id']}:2")
            position = props.get("position", "up")
            if position == "up" and n_up is not None:
                resistors.append({"n1": n1, "n2": n_up, "value": 0.01})
            elif position != "up" and n_down is not None:
                resistors.append({"n1": n1, "n2": n_down, "value": 0.01})

    return {
        "terminal_nodes": terminal_nodes,
        "node_count": node_count,
        "resistors": resistors,
        "sources": sources,
        "virtual_ground": terminal_data.get("virtual_ground", False),
    }


def build_model_ac(components, wires, contactor_states, timer_states, frequency_hz):
    terminal_data = build_terminal_nodes(components, wires, contactor_states)
    if "error" in terminal_data:
        return terminal_data

    terminal_nodes = terminal_data["terminal_nodes"]
    node_count = terminal_data["node_count"]
    impedances = []
    sources = []
    omega = max(2 * math.pi * frequency_hz, 1e-6)

    for comp in components:
        comp_type = comp.get("type")
        props = comp.get("props", {})
        count = get_terminal_count(comp)
        n1 = terminal_nodes.get(f"{comp['id']}:0")
        n2 = terminal_nodes.get(f"{comp['id']}:1") if count > 1 else None

        if comp_type == "resistor":
            if n1 is None or n2 is None:
                continue
            impedances.append({"n1": n1, "n2": n2, "value": Complex(props.get("value", 1), 0)})
        elif comp_type == "switch":
            if props.get("closed", False):
                if n1 is None or n2 is None:
                    continue
                impedances.append({"n1": n1, "n2": n2, "value": Complex(0.01, 0)})
        elif comp_type == "push_button":
            if props.get("closed", False):
                if n1 is None or n2 is None:
                    continue
                impedances.append({"n1": n1, "n2": n2, "value": Complex(0.01, 0)})
        elif comp_type == "inductor":
            if n1 is None or n2 is None:
                continue
            inductance = max(props.get("value", 0.0), 1e-12)
            impedances.append({"n1": n1, "n2": n2, "value": Complex(0, omega * inductance)})
        elif comp_type == "capacitor":
            if n1 is None or n2 is None:
                continue
            capacitance = max(props.get("value", 0.0), 1e-12)
            impedances.append({"n1": n1, "n2": n2, "value": Complex(0, -1 / (omega * capacitance))})
        elif comp_type == "motor":
            if n1 is None or n2 is None:
                continue
            impedances.append({"n1": n1, "n2": n2, "value": Complex(props.get("value", 10), 0)})
        elif comp_type == "motor_3ph":
            n_l1 = terminal_nodes.get(f"{comp['id']}:0")
            n_l2 = terminal_nodes.get(f"{comp['id']}:1")
            n_l3 = terminal_nodes.get(f"{comp['id']}:2")
            if n_l1 is None or n_l2 is None or n_l3 is None:
                continue
            z = Complex(props.get("value", 12), 0)
            if props.get("connection", "Y") == "Y":
                internal = terminal_nodes.get(f"{comp['id']}:N")
                if internal is None:
                    internal = node_count
                    terminal_nodes[f"{comp['id']}:N"] = internal
                    node_count += 1
                impedances.append({"n1": n_l1, "n2": internal, "value": z})
                impedances.append({"n1": n_l2, "n2": internal, "value": z})
                impedances.append({"n1": n_l3, "n2": internal, "value": z})
            else:
                impedances.append({"n1": n_l1, "n2": n_l2, "value": z})
                impedances.append({"n1": n_l2, "n2": n_l3, "value": z})
                impedances.append({"n1": n_l3, "n2": n_l1, "value": z})
        elif comp_type == "lamp":
            if n1 is None or n2 is None:
                continue
            impedances.append({"n1": n1, "n2": n2, "value": Complex(props.get("value", 80), 0)})
        elif comp_type == "contactor":
            coil_n1 = terminal_nodes.get(f"{comp['id']}:0")
            coil_n2 = terminal_nodes.get(f"{comp['id']}:1")
            if coil_n1 is not None and coil_n2 is not None:
                impedances.append(
                    {"n1": coil_n1, "n2": coil_n2, "value": Complex(props.get("coilResistance", 120), 0)}
                )
            poles = props.get("poles") or ["NO"]
            energized = contactor_states.get(comp["id"], False)
            if props.get("contactType", "standard") == "changeover":
                for idx in range(len(poles)):
                    n_common = terminal_nodes.get(f"{comp['id']}:{2 + idx * 3}")
                    n_no = terminal_nodes.get(f"{comp['id']}:{3 + idx * 3}")
                    n_nc = terminal_nodes.get(f"{comp['id']}:{4 + idx * 3}")
                    target = n_no if energized else n_nc
                    if n_common is None or target is None:
                        continue
                    impedances.append({"n1": n_common, "n2": target, "value": Complex(0.01, 0)})
            else:
                for idx, pole in enumerate(poles):
                    closed = pole == "NO" if energized else pole == "NC"
                    if not closed:
                        continue
                    n1_pole = terminal_nodes.get(f"{comp['id']}:{2 + idx * 2}")
                    n2_pole = terminal_nodes.get(f"{comp['id']}:{3 + idx * 2}")
                    if n1_pole is None or n2_pole is None:
                        continue
                    impedances.append({"n1": n1_pole, "n2": n2_pole, "value": Complex(0.01, 0)})
        elif comp_type == "timer":
            coil_n1 = terminal_nodes.get(f"{comp['id']}:0")
            coil_n2 = terminal_nodes.get(f"{comp['id']}:1")
            if coil_n1 is not None and coil_n2 is not None:
                impedances.append(
                    {"n1": coil_n1, "n2": coil_n2, "value": Complex(props.get("coilResistance", 120), 0)}
                )
            state = timer_states.get(comp["id"], {})
            output_closed = state.get("outputClosed", False)
            n_common = terminal_nodes.get(f"{comp['id']}:2")
            n_no = terminal_nodes.get(f"{comp['id']}:3")
            n_nc = terminal_nodes.get(f"{comp['id']}:4")
            target = n_no if output_closed else n_nc
            if n_common is not None and target is not None:
                impedances.append({"n1": n_common, "n2": target, "value": Complex(0.01, 0)})
        elif comp_type == "time_timer":
            state = timer_states.get(comp["id"], {})
            output_closed = state.get("outputClosed", False)
            n_common = terminal_nodes.get(f"{comp['id']}:0")
            n_no = terminal_nodes.get(f"{comp['id']}:1")
            n_nc = terminal_nodes.get(f"{comp['id']}:2")
            target = n_no if output_closed else n_nc
            if n_common is not None and target is not None:
                impedances.append({"n1": n_common, "n2": target, "value": Complex(0.01, 0)})
        elif comp_type == "switch_spdt":
            if n1 is None:
                continue
            n_up = terminal_nodes.get(f"{comp['id']}:1")
            n_down = terminal_nodes.get(f"{comp['id']}:2")
            position = props.get("position", "up")
            if position == "up" and n_up is not None:
                impedances.append({"n1": n1, "n2": n_up, "value": Complex(0.01, 0)})
            elif position != "up" and n_down is not None:
                impedances.append({"n1": n1, "n2": n_down, "value": Complex(0.01, 0)})
        elif comp_type == "voltage_source":
            supply = props.get("supplyType", "DC")
            if supply == "DC":
                continue
            if supply == "AC1":
                if n1 is None or n2 is None:
                    continue
                value = Complex(props.get("value", 0), 0)
                sources.append({"n1": n1, "n2": n2, "value": value, "id": comp["id"]})
            elif supply == "AC3":
                connection = props.get("connection", "Y")
                v_ll = props.get("value", 400)
                if connection == "Delta":
                    n_l1 = terminal_nodes.get(f"{comp['id']}:0")
                    n_l2 = terminal_nodes.get(f"{comp['id']}:1")
                    n_l3 = terminal_nodes.get(f"{comp['id']}:2")
                    if n_l1 is not None and n_l2 is not None:
                        sources.append(
                            {"n1": n_l1, "n2": n_l2, "value": complex_from_polar(v_ll, 0), "id": f"{comp['id']}_L1L2"}
                        )
                    if n_l2 is not None and n_l3 is not None:
                        sources.append(
                            {"n1": n_l2, "n2": n_l3, "value": complex_from_polar(v_ll, -120), "id": f"{comp['id']}_L2L3"}
                        )
                    if n_l3 is not None and n_l1 is not None:
                        sources.append(
                            {"n1": n_l3, "n2": n_l1, "value": complex_from_polar(v_ll, 120), "id": f"{comp['id']}_L3L1"}
                        )
                else:
                    v_phase = v_ll / math.sqrt(3)
                    n_l1 = terminal_nodes.get(f"{comp['id']}:0")
                    n_l2 = terminal_nodes.get(f"{comp['id']}:1")
                    n_l3 = terminal_nodes.get(f"{comp['id']}:2")
                    n_n = terminal_nodes.get(f"{comp['id']}:3")
                    if n_l1 is not None and n_n is not None:
                        sources.append(
                            {"n1": n_n, "n2": n_l1, "value": complex_from_polar(v_phase, 0), "id": f"{comp['id']}_L1"}
                        )
                    if n_l2 is not None and n_n is not None:
                        sources.append(
                            {"n1": n_n, "n2": n_l2, "value": complex_from_polar(v_phase, -120), "id": f"{comp['id']}_L2"}
                        )
                    if n_l3 is not None and n_n is not None:
                        sources.append(
                            {"n1": n_n, "n2": n_l3, "value": complex_from_polar(v_phase, 120), "id": f"{comp['id']}_L3"}
                        )

    return {
        "terminal_nodes": terminal_nodes,
        "node_count": node_count,
        "impedances": impedances,
        "sources": sources,
        "virtual_ground": terminal_data.get("virtual_ground", False),
    }


def _find_floating_nodes(node_count, elements):
    if node_count <= 1:
        return set(), set(), set()
    adjacency = [set() for _ in range(node_count)]
    active = set()
    for elem in elements:
        n1 = elem.get("n1")
        n2 = elem.get("n2")
        if n1 is None or n2 is None:
            continue
        active.add(n1)
        active.add(n2)
        adjacency[n1].add(n2)
        adjacency[n2].add(n1)
    if not active:
        return set(), set(), set()
    reachable = set()
    stack = [0] if 0 in active else []
    while stack:
        node = stack.pop()
        if node in reachable:
            continue
        reachable.add(node)
        stack.extend(adjacency[node])
    floating = active - reachable
    return floating, reachable, active


def _filter_elements(elements, floating):
    if not floating:
        return elements
    filtered = []
    for elem in elements:
        n1 = elem.get("n1")
        n2 = elem.get("n2")
        if n1 in floating or n2 in floating:
            continue
        filtered.append(elem)
    return filtered


def _component_errors_for_floating(components, terminal_nodes, floating, active, source_reachable, label):
    errors = {}
    if not floating:
        return errors
    for comp in components:
        comp_id = comp.get("id")
        count = get_terminal_count(comp)
        for idx in range(count):
            key = f"{comp_id}:{idx}"
            node = terminal_nodes.get(key)
            if node is None:
                continue
            if node in active and node in floating and node in source_reachable:
                errors[comp_id] = f"Ej jordad delkrets ({label})"
                break
    return errors


def _reachable_from_sources(node_count, elements, sources):
    if not sources:
        return set()
    adjacency = [set() for _ in range(node_count)]
    for elem in elements:
        n1 = elem.get("n1")
        n2 = elem.get("n2")
        if n1 is None or n2 is None:
            continue
        adjacency[n1].add(n2)
        adjacency[n2].add(n1)
    source_nodes = set()
    for src in sources:
        n1 = src.get("n1")
        n2 = src.get("n2")
        if n1 is not None:
            source_nodes.add(n1)
        if n2 is not None:
            source_nodes.add(n2)
    reachable = set()
    stack = list(source_nodes)
    while stack:
        node = stack.pop()
        if node in reachable:
            continue
        reachable.add(node)
        stack.extend(adjacency[node])
    return reachable


def gaussian_solve(matrix, vector):
    n = len(matrix)
    augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]

    for i in range(n):
        max_row = max(range(i, n), key=lambda r: abs(augmented[r][i]))
        if abs(augmented[max_row][i]) < 1e-12:
            return None
        augmented[i], augmented[max_row] = augmented[max_row], augmented[i]

        pivot = augmented[i][i]
        for j in range(i, n + 1):
            augmented[i][j] /= pivot

        for k in range(n):
            if k == i:
                continue
            factor = augmented[k][i]
            for j in range(i, n + 1):
                augmented[k][j] -= factor * augmented[i][j]

    return [row[n] for row in augmented]


def solve_mna(node_count, resistors, sources):
    n = node_count - 1
    m = len(sources)
    size = n + m
    if size == 0:
        return {"error": "Inga noder att simulera."}

    matrix = [[0.0 for _ in range(size)] for _ in range(size)]
    vector = [0.0 for _ in range(size)]

    for res in resistors:
        if res["n1"] is None or res["n2"] is None:
            continue
        g = 1 / max(res["value"], 1e-9)
        n1 = -1 if res["n1"] == 0 else res["n1"] - 1
        n2 = -1 if res["n2"] == 0 else res["n2"] - 1
        if n1 >= 0:
            matrix[n1][n1] += g
        if n2 >= 0:
            matrix[n2][n2] += g
        if n1 >= 0 and n2 >= 0:
            matrix[n1][n2] -= g
            matrix[n2][n1] -= g

    for idx, src in enumerate(sources):
        n1 = -1 if src["n1"] == 0 else src["n1"] - 1
        n2 = -1 if src["n2"] == 0 else src["n2"] - 1
        row = n + idx
        if n1 >= 0:
            matrix[n1][row] += 1
            matrix[row][n1] += 1
        if n2 >= 0:
            matrix[n2][row] -= 1
            matrix[row][n2] -= 1
        vector[row] = src["value"]

    solution = gaussian_solve(matrix, vector)
    if solution is None:
        return {"error": "Kunde inte lösa nätet (singulärt)."}

    node_voltages = [0.0] + solution[:n]
    source_currents = {src["id"]: solution[n + idx] for idx, src in enumerate(sources)}
    return {"node_voltages": node_voltages, "source_currents": source_currents}


def gaussian_solve_complex(matrix, vector):
    n = len(matrix)
    augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]

    for i in range(n):
        max_row = max(range(i, n), key=lambda r: abs(augmented[r][i]))
        if abs(augmented[max_row][i]) < 1e-12:
            return None
        augmented[i], augmented[max_row] = augmented[max_row], augmented[i]

        pivot = augmented[i][i]
        for j in range(i, n + 1):
            augmented[i][j] = augmented[i][j] / pivot

        for k in range(n):
            if k == i:
                continue
            factor = augmented[k][i]
            for j in range(i, n + 1):
                augmented[k][j] = augmented[k][j] - factor * augmented[i][j]

    return [row[n] for row in augmented]


def solve_mna_ac(node_count, impedances, sources):
    n = node_count - 1
    m = len(sources)
    size = n + m
    if size == 0:
        return {"error": "Inga noder att simulera."}

    matrix = [[Complex(0, 0) for _ in range(size)] for _ in range(size)]
    vector = [Complex(0, 0) for _ in range(size)]

    for imp in impedances:
        if imp["n1"] is None or imp["n2"] is None:
            continue
        g = Complex(1, 0) / imp["value"]
        n1 = -1 if imp["n1"] == 0 else imp["n1"] - 1
        n2 = -1 if imp["n2"] == 0 else imp["n2"] - 1
        if n1 >= 0:
            matrix[n1][n1] = matrix[n1][n1] + g
        if n2 >= 0:
            matrix[n2][n2] = matrix[n2][n2] + g
        if n1 >= 0 and n2 >= 0:
            matrix[n1][n2] = matrix[n1][n2] - g
            matrix[n2][n1] = matrix[n2][n1] - g

    for idx, src in enumerate(sources):
        n1 = -1 if src["n1"] == 0 else src["n1"] - 1
        n2 = -1 if src["n2"] == 0 else src["n2"] - 1
        row = n + idx
        if n1 >= 0:
            matrix[n1][row] = matrix[n1][row] + Complex(1, 0)
            matrix[row][n1] = matrix[row][n1] + Complex(1, 0)
        if n2 >= 0:
            matrix[n2][row] = matrix[n2][row] - Complex(1, 0)
            matrix[row][n2] = matrix[row][n2] - Complex(1, 0)
        vector[row] = src["value"]

    solution = gaussian_solve_complex(matrix, vector)
    if solution is None:
        return {"error": "Kunde inte lösa nätet (singulärt)."}

    node_voltages = [Complex(0, 0)] + solution[:n]
    source_currents = {src["id"]: solution[n + idx] for idx, src in enumerate(sources)}
    return {"node_voltages": node_voltages, "source_currents": source_currents}


def _voltage_magnitude(comp, terminal_nodes, dc_voltages, ac_voltages):
    n1 = terminal_nodes.get(f"{comp['id']}:0")
    n2 = terminal_nodes.get(f"{comp['id']}:1")
    if n1 is None or n2 is None:
        return None
    dv_dc = None
    dv_ac = None
    if dc_voltages is not None:
        dv_dc = abs(dc_voltages[n1] - dc_voltages[n2])
    if ac_voltages is not None:
        dv_ac = abs(ac_voltages[n1] - ac_voltages[n2])
    if dv_dc is None:
        return dv_ac
    if dv_ac is None:
        return dv_dc
    return max(dv_dc, dv_ac)


def compute_contactor_states(components, terminal_nodes, dc_voltages, ac_voltages):
    states = {}
    for comp in components:
        if comp.get("type") != "contactor":
            continue
        dv = _voltage_magnitude(comp, terminal_nodes, dc_voltages, ac_voltages)
        if dv is None:
            states[comp["id"]] = False
            continue
        pull_in = comp.get("props", {}).get("pullInVoltage", 0)
        states[comp["id"]] = dv + EPSILON_V >= pull_in
    return states


def _parse_hhmm(value, fallback_minutes):
    if not isinstance(value, str) or ":" not in value:
        return fallback_minutes
    parts = value.split(":")
    if len(parts) != 2:
        return fallback_minutes
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        return fallback_minutes
    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        return fallback_minutes
    return hours * 60 + minutes


def compute_time_timer_states(components):
    now = time.localtime()
    current_minutes = now.tm_hour * 60 + now.tm_min
    states = {}
    for comp in components:
        if comp.get("type") != "time_timer":
            continue
        props = comp.get("props", {})
        start_minutes = _parse_hhmm(props.get("startTime"), 8 * 60)
        end_minutes = _parse_hhmm(props.get("endTime"), 17 * 60)
        if start_minutes == end_minutes:
            active = False
        elif end_minutes > start_minutes:
            active = start_minutes <= current_minutes < end_minutes
        else:
            active = current_minutes >= start_minutes or current_minutes < end_minutes
        states[comp["id"]] = {"outputClosed": active}
    return states


def compute_timer_states(components, terminal_nodes, dc_voltages, ac_voltages, sim_time_ms):
    states = {}
    now = int(sim_time_ms) if sim_time_ms is not None else int(time.time() * 1000)
    for comp in components:
        if comp.get("type") != "timer":
            continue
        props = comp.get("props", {})
        delay_ms = max(0, int(props.get("delayMs", 1000)))
        loop_mode = bool(props.get("loop", False))
        initial_closed = bool(props.get("initialClosed", False))
        pull_in = props.get("pullInVoltage", 0)
        dv = _voltage_magnitude(comp, terminal_nodes, dc_voltages, ac_voltages)
        energized = dv is not None and dv + EPSILON_V >= pull_in
        prev = props.get("timerState", {}) or {}
        running = bool(prev.get("running", False))
        start_at = prev.get("startAt")
        output_closed = bool(prev.get("outputClosed", False))
        remaining_ms = delay_ms

        if energized:
            if not running or start_at is None:
                running = True
                start_at = now
            elapsed = max(0, now - start_at)
            if elapsed >= delay_ms:
                if loop_mode:
                    output_closed = not output_closed
                    running = True
                    start_at = now
                    remaining_ms = delay_ms
                else:
                    output_closed = True
                    running = False
                    remaining_ms = 0
            else:
                remaining_ms = delay_ms - elapsed
        else:
            running = False
            start_at = None
            output_closed = initial_closed
            remaining_ms = delay_ms

        states[comp["id"]] = {
            "running": running,
            "startAt": start_at,
            "outputClosed": output_closed,
            "remainingMs": remaining_ms,
        }
    return states


def compute_lamp_lit(components, terminal_nodes, dc_voltages, ac_voltages):
    lamp_lit = {}
    for comp in components:
        if comp.get("type") != "lamp":
            continue
        dv = _voltage_magnitude(comp, terminal_nodes, dc_voltages, ac_voltages)
        if dv is None:
            lamp_lit[comp["id"]] = False
            continue
        threshold = comp.get("props", {}).get("threshold", 0)
        lamp_lit[comp["id"]] = dv + EPSILON_V >= threshold
    return lamp_lit


def compute_motor_running(components, terminal_nodes, dc_voltages, ac_voltages):
    running = {}
    for comp in components:
        if comp.get("type") != "motor":
            continue
        dv = _voltage_magnitude(comp, terminal_nodes, dc_voltages, ac_voltages)
        if dv is None:
            running[comp["id"]] = False
            continue
        threshold = comp.get("props", {}).get("startVoltage", 0)
        running[comp["id"]] = dv + EPSILON_V >= threshold
    return running


def compute_faults(components, terminal_nodes, dc_voltages, ac_voltages):
    faults = {}
    for comp in components:
        comp_type = comp.get("type")
        if comp_type not in {"lamp", "contactor"}:
            continue
        dv = _voltage_magnitude(comp, terminal_nodes, dc_voltages, ac_voltages)
        if dv is None or dv < FAULT_MIN_V:
            continue
        props = comp.get("props", {})
        if comp_type == "lamp":
            rated = props.get("ratedVoltage", props.get("threshold", 0))
            if rated:
                low = rated * (1 - FAULT_TOLERANCE)
                high = rated * (1 + FAULT_TOLERANCE)
                if dv < low or dv > high:
                    faults[comp["id"]] = f"Lampa fel spänning ({dv:.2f} V / {rated} V)"
        if comp_type == "contactor":
            rated = props.get("coilRatedVoltage", props.get("pullInVoltage", 0))
            if rated:
                low = rated * (1 - FAULT_TOLERANCE)
                high = rated * (1 + FAULT_TOLERANCE)
                if dv < low or dv > high:
                    faults[comp["id"]] = f"Kontaktor fel spänning ({dv:.2f} V / {rated} V)"
    return faults


def _phase_angle(phasor):
    return math.degrees(math.atan2(phasor.im, phasor.re))


def _normalize_angle(angle):
    while angle <= -180:
        angle += 360
    while angle > 180:
        angle -= 360
    return angle


def compute_motor3ph_direction(components, terminal_nodes, ac_voltages):
    directions = {}
    if ac_voltages is None:
        return directions
    for comp in components:
        if comp.get("type") != "motor_3ph":
            continue
        n1 = terminal_nodes.get(f"{comp['id']}:0")
        n2 = terminal_nodes.get(f"{comp['id']}:1")
        n3 = terminal_nodes.get(f"{comp['id']}:2")
        if n1 is None or n2 is None or n3 is None:
            directions[comp["id"]] = "stopped"
            continue
        v1 = ac_voltages[n1]
        v2 = ac_voltages[n2]
        v3 = ac_voltages[n3]
        v12 = abs(v1 - v2)
        v23 = abs(v2 - v3)
        v31 = abs(v3 - v1)
        v_ll = (v12 + v23 + v31) / 3.0
        threshold = comp.get("props", {}).get("startVoltage", 0)
        if v_ll + EPSILON_V < threshold:
            directions[comp["id"]] = "stopped"
            continue
        a1 = _phase_angle(v1)
        a2 = _phase_angle(v2)
        a3 = _phase_angle(v3)
        d12 = _normalize_angle(a2 - a1)
        d13 = _normalize_angle(a3 - a1)
        if d12 < 0 and d13 > 0:
            directions[comp["id"]] = "cw"
        elif d12 > 0 and d13 < 0:
            directions[comp["id"]] = "ccw"
        else:
            directions[comp["id"]] = "cw"
    return directions


def get_ac_frequency(components):
    frequencies = set()
    for comp in components:
        if comp.get("type") != "voltage_source":
            continue
        props = comp.get("props", {})
        supply = props.get("supplyType", "DC")
        if supply in {"AC1", "AC3"}:
            frequencies.add(int(props.get("frequency", 50)))
    if not frequencies:
        return None
    if len(frequencies) > 1:
        return {"error": "Flera AC-frekvenser stöds inte ännu."}
    return frequencies.pop()


def solve_network(payload):
    components = payload.get("components", [])
    wires = payload.get("wires", [])
    sim_time = payload.get("simTime")
    contactor_states = {comp["id"]: False for comp in components if comp.get("type") == "contactor"}
    timer_states = {}
    for comp in components:
        if comp.get("type") == "timer":
            timer_states[comp["id"]] = comp.get("props", {}).get("timerState", {}) or {}
    timer_states.update(compute_time_timer_states(components))
    dc_solution = None
    dc_model = None
    ac_solution = None
    ac_model = None
    freq = get_ac_frequency(components)
    if isinstance(freq, dict):
        return freq

    solve_errors = {}
    debug_info = {"dc": {}, "ac": {}}

    for _ in range(3):
        dc_model = build_model_dc(components, wires, contactor_states, timer_states)
        if "error" in dc_model:
            return dc_model
        dc_elements = dc_model["resistors"] + dc_model["sources"]
        dc_floating, dc_reachable, dc_active = _find_floating_nodes(dc_model["node_count"], dc_elements)
        dc_inactive = set(range(1, dc_model["node_count"])) - dc_active
        dc_floating_all = dc_floating | dc_inactive
        dc_source_reachable = _reachable_from_sources(
            dc_model["node_count"], dc_elements, dc_model["sources"]
        )
        debug_info["dc"] = {
            "nodes": dc_model["node_count"],
            "sources": len(dc_model["sources"]),
            "elements": len(dc_elements),
            "floating": len(dc_floating),
            "inactive": len(dc_inactive),
            "active": len(dc_active),
            "virtualGround": dc_model.get("virtual_ground", False),
        }
        solve_errors.update(
            _component_errors_for_floating(
                components,
                dc_model["terminal_nodes"],
                dc_floating,
                dc_active,
                dc_source_reachable,
                "DC",
            )
        )
        dc_resistors = _filter_elements(dc_model["resistors"], dc_floating_all)
        dc_sources = _filter_elements(dc_model["sources"], dc_floating_all)
        for node in dc_floating_all:
            if node == 0:
                continue
            dc_resistors.append({"n1": node, "n2": 0, "value": SHUNT_RESISTANCE})
        if dc_sources:
            dc_solution = solve_mna(dc_model["node_count"], dc_resistors, dc_sources)
            if "error" in dc_solution:
                for node in dc_active:
                    if node == 0:
                        continue
                    dc_resistors.append({"n1": node, "n2": 0, "value": SHUNT_RESISTANCE})
                dc_solution = solve_mna(dc_model["node_count"], dc_resistors, dc_sources)
                if "error" in dc_solution:
                    solve_errors["__network_dc"] = "Kunde inte lösa DC-nätet."
                    dc_solution = {"node_voltages": [0.0] * dc_model["node_count"], "source_currents": {}}
        else:
            dc_solution = {"node_voltages": [0.0] * dc_model["node_count"], "source_currents": {}}

        if freq is not None:
            ac_model = build_model_ac(components, wires, contactor_states, timer_states, freq)
            if "error" in ac_model:
                return ac_model
            ac_elements = ac_model["impedances"] + ac_model["sources"]
            ac_floating, ac_reachable, ac_active = _find_floating_nodes(ac_model["node_count"], ac_elements)
            ac_inactive = set(range(1, ac_model["node_count"])) - ac_active
            ac_floating_all = ac_floating | ac_inactive
            ac_source_reachable = _reachable_from_sources(
                ac_model["node_count"], ac_elements, ac_model["sources"]
            )
            debug_info["ac"] = {
                "nodes": ac_model["node_count"],
                "sources": len(ac_model["sources"]),
                "elements": len(ac_elements),
                "floating": len(ac_floating),
                "inactive": len(ac_inactive),
                "active": len(ac_active),
                "virtualGround": ac_model.get("virtual_ground", False),
            }
            solve_errors.update(
                _component_errors_for_floating(
                    components,
                    ac_model["terminal_nodes"],
                    ac_floating,
                    ac_active,
                    ac_source_reachable,
                    "AC",
                )
            )
            ac_impedances = _filter_elements(ac_model["impedances"], ac_floating_all)
            ac_sources = _filter_elements(ac_model["sources"], ac_floating_all)
            for node in ac_floating_all:
                if node == 0:
                    continue
                ac_impedances.append({"n1": node, "n2": 0, "value": Complex(SHUNT_RESISTANCE, 0)})
            if ac_sources:
                ac_solution = solve_mna_ac(ac_model["node_count"], ac_impedances, ac_sources)
                if "error" in ac_solution:
                    for node in ac_active:
                        if node == 0:
                            continue
                        ac_impedances.append({"n1": node, "n2": 0, "value": Complex(SHUNT_RESISTANCE, 0)})
                    ac_solution = solve_mna_ac(ac_model["node_count"], ac_impedances, ac_sources)
                    if "error" in ac_solution:
                        solve_errors["__network_ac"] = "Kunde inte lösa AC-nätet."
                        ac_solution = {"node_voltages": [Complex(0, 0)] * ac_model["node_count"], "source_currents": {}}
            else:
                ac_solution = {"node_voltages": [Complex(0, 0)] * ac_model["node_count"], "source_currents": {}}
        else:
            ac_solution = None

        terminal_nodes = dc_model["terminal_nodes"]
        updated = compute_contactor_states(
            components,
            terminal_nodes,
            dc_solution["node_voltages"] if dc_solution else None,
            ac_solution["node_voltages"] if ac_solution else None,
        )
        updated_timers = compute_timer_states(
            components,
            terminal_nodes,
            dc_solution["node_voltages"] if dc_solution else None,
            ac_solution["node_voltages"] if ac_solution else None,
            sim_time,
        )
        updated_timers.update(compute_time_timer_states(components))
        if updated == contactor_states and updated_timers == timer_states:
            break
        contactor_states = updated
        timer_states = updated_timers

    return {
        "components": components,
        "terminal_nodes": dc_model["terminal_nodes"],
        "contactor_states": contactor_states,
        "timer_states": timer_states,
        "dc_solution": dc_solution,
        "ac_solution": ac_solution,
        "solve_errors": solve_errors,
        "debug_info": debug_info,
    }


def simulate_circuit(payload):
    result = solve_network(payload)
    if "error" in result:
        return result

    terminal_nodes = result["terminal_nodes"]
    dc_solution = result["dc_solution"]
    ac_solution = result["ac_solution"]
    components = result["components"]

    lamp_lit = compute_lamp_lit(
        components,
        terminal_nodes,
        dc_solution["node_voltages"] if dc_solution else None,
        ac_solution["node_voltages"] if ac_solution else None,
    )
    motor_running = compute_motor_running(
        components,
        terminal_nodes,
        dc_solution["node_voltages"] if dc_solution else None,
        ac_solution["node_voltages"] if ac_solution else None,
    )
    faults = compute_faults(
        components,
        terminal_nodes,
        dc_solution["node_voltages"] if dc_solution else None,
        ac_solution["node_voltages"] if ac_solution else None,
    )
    motor3ph_direction = compute_motor3ph_direction(
        components,
        terminal_nodes,
        ac_solution["node_voltages"] if ac_solution else None,
    )
    return {
        "solution": {
            "nodeVoltages": dc_solution["node_voltages"] if dc_solution else [],
            "terminalNodes": terminal_nodes,
            "acNodeVoltages": (
                [{"re": v.re, "im": v.im} for v in ac_solution["node_voltages"]]
                if ac_solution
                else []
            ),
        },
        "contactorStates": result["contactor_states"],
        "lampLit": lamp_lit,
        "motorRunning": motor_running,
        "motor3phDirection": motor3ph_direction,
        "faults": faults,
        "solveErrors": result["solve_errors"],
        "timerStates": result.get("timer_states", {}),
        "debugInfo": result.get("debug_info", {}),
    }


@app.post("/api/simulate")
def api_simulate():
    payload = request.get_json(silent=True) or {}
    result = simulate_circuit(payload)
    if "error" in result:
        return jsonify({"error": result["error"]}), 400
    return jsonify(result)


@app.post("/api/measure")
def api_measure():
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode")
    result = solve_network(payload)
    if "error" in result:
        return jsonify({"error": result["error"]}), 400

    components = result["components"]
    terminal_nodes = result["terminal_nodes"]
    dc_voltages = result["dc_solution"]["node_voltages"] if result["dc_solution"] else None
    ac_voltages = result["ac_solution"]["node_voltages"] if result["ac_solution"] else None

    if mode == "voltage":
        a_ref = payload.get("aRef")
        b_ref = payload.get("bRef")
        if not a_ref or not b_ref:
            return jsonify({"error": "Saknar mätpunkter."}), 400
        va = dc_voltages[terminal_nodes[f"{a_ref['compId']}:{a_ref['index']}"]]
        vb = dc_voltages[terminal_nodes[f"{b_ref['compId']}:{b_ref['index']}"]]
        return jsonify({"value": va - vb})

    if mode == "ac_voltage":
        a_ref = payload.get("aRef")
        b_ref = payload.get("bRef")
        if not a_ref or not b_ref:
            return jsonify({"error": "Saknar mätpunkter."}), 400
        if ac_voltages is None:
            return jsonify({"error": "Ingen AC-lösning tillgänglig."}), 400
        va = ac_voltages[terminal_nodes[f"{a_ref['compId']}:{a_ref['index']}"]]
        vb = ac_voltages[terminal_nodes[f"{b_ref['compId']}:{b_ref['index']}"]]
        return jsonify({"value": abs(va - vb)})

    if mode == "ac_phase":
        a_ref = payload.get("aRef")
        b_ref = payload.get("bRef")
        if not a_ref or not b_ref:
            return jsonify({"error": "Saknar mätpunkter."}), 400
        if ac_voltages is None:
            return jsonify({"error": "Ingen AC-lösning tillgänglig."}), 400
        va = ac_voltages[terminal_nodes[f"{a_ref['compId']}:{a_ref['index']}"]]
        vb = ac_voltages[terminal_nodes[f"{b_ref['compId']}:{b_ref['index']}"]]
        v = va - vb
        angle = math.degrees(math.atan2(v.im, v.re))
        return jsonify({"value": angle})

    if mode == "current":
        component_id = payload.get("componentId")
        comp = next((c for c in components if c.get("id") == component_id), None)
        if not comp:
            return jsonify({"error": "Komponent saknas."}), 400
        n1 = terminal_nodes.get(f"{comp['id']}:0")
        n2 = terminal_nodes.get(f"{comp['id']}:1")
        v1 = dc_voltages[n1]
        v2 = dc_voltages[n2]
        comp_type = comp.get("type")
        props = comp.get("props", {})
        if comp_type == "voltage_source":
            return jsonify({"value": None})
        if comp_type in {"resistor", "motor"}:
            value = props.get("value", 1)
            return jsonify({"value": (v1 - v2) / value})
        if comp_type == "lamp":
            value = props.get("value", 80)
            return jsonify({"value": (v1 - v2) / value})
        if comp_type == "switch":
            if not props.get("closed", False):
                return jsonify({"value": 0.0})
            return jsonify({"value": (v1 - v2) / 0.01})
        if comp_type == "inductor":
            return jsonify({"value": (v1 - v2) / 0.01})
        if comp_type == "contactor":
            value = props.get("coilResistance", 120)
            return jsonify({"value": (v1 - v2) / value})
        return jsonify({"value": None})

    if mode == "ac_current":
        component_id = payload.get("componentId")
        comp = next((c for c in components if c.get("id") == component_id), None)
        if not comp:
            return jsonify({"error": "Komponent saknas."}), 400
        if ac_voltages is None:
            return jsonify({"error": "Ingen AC-lösning tillgänglig."}), 400
        n1 = terminal_nodes.get(f"{comp['id']}:0")
        n2 = terminal_nodes.get(f"{comp['id']}:1")
        n3 = terminal_nodes.get(f"{comp['id']}:2")
        if n1 is None or n2 is None:
            return jsonify({"value": None})
        v1 = ac_voltages[n1]
        v2 = ac_voltages[n2]
        v = v1 - v2
        comp_type = comp.get("type")
        props = comp.get("props", {})
        freq = get_ac_frequency(components)
        if isinstance(freq, dict):
            return jsonify({"error": freq["error"]}), 400
        omega = 2 * math.pi * (freq or 50)
        if comp_type in {"resistor", "motor", "lamp"}:
            z = Complex(props.get("value", 1), 0)
        elif comp_type == "motor_3ph":
            z = Complex(props.get("value", 12), 0)
            if n3 is None:
                return jsonify({"value": None})
            v12 = abs(ac_voltages[n1] - ac_voltages[n2])
            v23 = abs(ac_voltages[n2] - ac_voltages[n3])
            v31 = abs(ac_voltages[n3] - ac_voltages[n1])
            v_ll = (v12 + v23 + v31) / 3.0
            if props.get("connection", "Y") == "Y":
                v_phase = v_ll / math.sqrt(3)
                current = Complex(v_phase, 0) / z
                return jsonify({"value": abs(current)})
            current = Complex(v_ll, 0) / z
            return jsonify({"value": abs(current) * math.sqrt(3)})
        elif comp_type == "contactor":
            z = Complex(props.get("coilResistance", 120), 0)
        elif comp_type == "timer":
            z = Complex(props.get("coilResistance", 120), 0)
        elif comp_type == "time_timer":
            return jsonify({"value": None})
        elif comp_type == "inductor":
            z = Complex(0, omega * max(props.get("value", 0.0), 1e-12))
        elif comp_type == "capacitor":
            z = Complex(0, -1 / (omega * max(props.get("value", 0.0), 1e-12)))
        elif comp_type == "switch":
            if not props.get("closed", False):
                return jsonify({"value": 0.0})
            z = Complex(0.01, 0)
        elif comp_type == "push_button":
            if not props.get("closed", False):
                return jsonify({"value": 0.0})
            z = Complex(0.01, 0)
        elif comp_type == "switch_spdt":
            z = Complex(0.01, 0)
        else:
            return jsonify({"value": None})
        current = v / z
        return jsonify({"value": abs(current)})

    if mode in {"ac_power_p", "ac_power_q", "ac_power_s", "ac_pf"}:
        component_id = payload.get("componentId")
        comp = next((c for c in components if c.get("id") == component_id), None)
        if not comp:
            return jsonify({"error": "Komponent saknas."}), 400
        if ac_voltages is None:
            return jsonify({"error": "Ingen AC-lösning tillgänglig."}), 400
        n1 = terminal_nodes.get(f"{comp['id']}:0")
        n2 = terminal_nodes.get(f"{comp['id']}:1")
        n3 = terminal_nodes.get(f"{comp['id']}:2")
        if n1 is None or n2 is None:
            return jsonify({"value": None})
        v = ac_voltages[n1] - ac_voltages[n2]
        props = comp.get("props", {})
        freq = get_ac_frequency(components)
        if isinstance(freq, dict):
            return jsonify({"error": freq["error"]}), 400
        omega = 2 * math.pi * (freq or 50)
        comp_type = comp.get("type")
        if comp_type in {"resistor", "motor", "lamp"}:
            z = Complex(props.get("value", 1), 0)
        elif comp_type == "motor_3ph":
            z = Complex(props.get("value", 12), 0)
            if n3 is None:
                return jsonify({"value": None})
            v12 = abs(ac_voltages[n1] - ac_voltages[n2])
            v23 = abs(ac_voltages[n2] - ac_voltages[n3])
            v31 = abs(ac_voltages[n3] - ac_voltages[n1])
            v_ll = (v12 + v23 + v31) / 3.0
            if props.get("connection", "Y") == "Y":
                v_phase = v_ll / math.sqrt(3)
                i_phase = Complex(v_phase, 0) / z
                s_phase = Complex(v_phase, 0) * i_phase.conjugate()
                s = Complex(s_phase.re * 3, s_phase.im * 3)
            else:
                i_phase = Complex(v_ll, 0) / z
                s_phase = Complex(v_ll, 0) * i_phase.conjugate()
                s = Complex(s_phase.re * 3, s_phase.im * 3)
            if mode == "ac_power_p":
                return jsonify({"value": s.re})
            if mode == "ac_power_q":
                return jsonify({"value": s.im})
            if mode == "ac_power_s":
                return jsonify({"value": abs(s)})
            s_abs = abs(s)
            if s_abs == 0:
                return jsonify({"value": None})
            return jsonify({"value": s.re / s_abs})
        elif comp_type == "contactor":
            z = Complex(props.get("coilResistance", 120), 0)
        elif comp_type == "timer":
            z = Complex(props.get("coilResistance", 120), 0)
        elif comp_type == "time_timer":
            return jsonify({"value": None})
        elif comp_type == "inductor":
            z = Complex(0, omega * max(props.get("value", 0.0), 1e-12))
        elif comp_type == "capacitor":
            z = Complex(0, -1 / (omega * max(props.get("value", 0.0), 1e-12)))
        elif comp_type == "switch":
            if not props.get("closed", False):
                return jsonify({"value": 0.0})
            z = Complex(0.01, 0)
        elif comp_type == "push_button":
            if not props.get("closed", False):
                return jsonify({"value": 0.0})
            z = Complex(0.01, 0)
        else:
            return jsonify({"value": None})
        current = v / z
        s = v * current.conjugate()
        if mode == "ac_power_p":
            return jsonify({"value": s.re})
        if mode == "ac_power_q":
            return jsonify({"value": s.im})
        if mode == "ac_power_s":
            return jsonify({"value": abs(s)})
        s_abs = abs(s)
        if s_abs == 0:
            return jsonify({"value": None})
        return jsonify({"value": s.re / s_abs})

    if mode == "resistance":
        a_ref = payload.get("aRef")
        b_ref = payload.get("bRef")
        if not a_ref or not b_ref:
            return jsonify({"error": "Saknar mätpunkter."}), 400
        model = build_model_dc(
            components,
            payload.get("wires", []),
            result["contactor_states"],
            result.get("timer_states", {}),
        )
        if "error" in model:
            return jsonify({"error": model["error"]}), 400
        a_node = terminal_nodes.get(f"{a_ref['compId']}:{a_ref['index']}")
        b_node = terminal_nodes.get(f"{b_ref['compId']}:{b_ref['index']}")
        sources = [dict(src, value=0) for src in model["sources"]]
        sources.append({"n1": a_node, "n2": b_node, "value": 1, "id": "test"})
        solution = solve_mna(model["node_count"], model["resistors"], sources)
        if "error" in solution:
            return jsonify({"error": solution["error"]}), 400
        current = solution["source_currents"].get("test")
        if current is None or abs(current) < 1e-9:
            return jsonify({"value": None})
        return jsonify({"value": 1 / current})

    return jsonify({"error": "Okänt mätläge."}), 400


@app.get("/api/saves")
def api_saves_list():
    return jsonify({"saves": _list_saves()})


@app.post("/api/saves")
def api_saves_save():
    payload = request.get_json(silent=True) or {}
    name = _safe_name(payload.get("name", ""))
    snapshot = payload.get("snapshot")
    if not name:
        return jsonify({"error": "Namn saknas."}), 400
    if snapshot is None:
        return jsonify({"error": "Snapshot saknas."}), 400

    save_id = payload.get("id")
    existing = None
    if save_id:
        path = SAVES_DIR / f"{save_id}.json"
        existing = _load_save(path) if path.exists() else None
    else:
        for path in SAVES_DIR.glob("*.json"):
            data = _load_save(path)
            if data and data.get("name") == name:
                existing = data
                save_id = data.get("id", path.stem)
                break

    if not save_id:
        save_id = str(uuid.uuid4())

    timestamp = int(time.time() * 1000)
    record = {
        "id": save_id,
        "name": name,
        "snapshot": snapshot,
        "updatedAt": timestamp,
    }
    if existing and "createdAt" in existing:
        record["createdAt"] = existing["createdAt"]
    else:
        record["createdAt"] = record["updatedAt"]

    path = SAVES_DIR / f"{save_id}.json"
    try:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=True, indent=2)
    except OSError:
        return jsonify({"error": "Kunde inte spara filen."}), 500

    return jsonify({"save": {"id": save_id, "name": name, "updatedAt": record["updatedAt"]}})


@app.get("/api/saves/<save_id>")
def api_saves_load(save_id):
    path = SAVES_DIR / f"{save_id}.json"
    data = _load_save(path)
    if not data:
        return jsonify({"error": "Sparning hittades inte."}), 404
    return jsonify({"snapshot": data.get("snapshot", {})})


@app.delete("/api/saves/<save_id>")
def api_saves_delete(save_id):
    path = SAVES_DIR / f"{save_id}.json"
    if not path.exists():
        return jsonify({"error": "Sparning hittades inte."}), 404
    try:
        path.unlink()
    except OSError:
        return jsonify({"error": "Kunde inte ta bort sparning."}), 500
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True,port=8080)
