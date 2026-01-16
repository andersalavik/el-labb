import math
import time

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
    if comp_type == "plc":
        props = component.get("props", {})
        inputs = max(1, min(64, int(props.get("inputs", 4))))
        outputs = max(1, min(64, int(props.get("outputs", 4))))
        return 2 + inputs + outputs
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


def build_model_dc(components, wires, contactor_states, timer_states, plc_states):
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
        elif comp_type == "plc":
            outputs_state = plc_states.get(comp["id"], [])
            props = comp.get("props", {})
            inputs = max(1, min(64, int(props.get("inputs", 4))))
            outputs = max(1, min(64, int(props.get("outputs", 4))))
            node_m = terminal_nodes.get(f"{comp['id']}:0")
            node_l = terminal_nodes.get(f"{comp['id']}:1")
            if node_l is None:
                continue
            for idx in range(outputs):
                if idx >= len(outputs_state) or not outputs_state[idx]:
                    continue
                n_out = terminal_nodes.get(f"{comp['id']}:{2 + inputs + idx}")
                if n_out is None:
                    continue
                resistors.append({"n1": node_l, "n2": n_out, "value": 0.01})
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


def build_model_ac(components, wires, contactor_states, timer_states, plc_states, frequency_hz):
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
        elif comp_type == "plc":
            outputs_state = plc_states.get(comp["id"], [])
            props = comp.get("props", {})
            inputs = max(1, min(64, int(props.get("inputs", 4))))
            outputs = max(1, min(64, int(props.get("outputs", 4))))
            node_l = terminal_nodes.get(f"{comp['id']}:1")
            if node_l is None:
                continue
            for idx in range(outputs):
                if idx >= len(outputs_state) or not outputs_state[idx]:
                    continue
                n_out = terminal_nodes.get(f"{comp['id']}:{2 + inputs + idx}")
                if n_out is None:
                    continue
                impedances.append({"n1": node_l, "n2": n_out, "value": Complex(0.01, 0)})
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


def _parse_plc_operand(token, inputs, outputs, timers, memories, counters):
    token = token.strip().upper()
    if token.startswith("I"):
        try:
            idx = int(token[1:]) - 1
        except ValueError:
            return None
        if 0 <= idx < len(inputs):
            return bool(inputs[idx])
        return False
    if token.startswith("Q"):
        try:
            idx = int(token[1:]) - 1
        except ValueError:
            return None
        if 0 <= idx < len(outputs):
            return bool(outputs[idx])
        return False
    if token.startswith("M"):
        try:
            idx = int(token[1:]) - 1
        except ValueError:
            return None
        return bool(memories.get(idx, False))
    if token.startswith("C"):
        try:
            idx = int(token[1:]) - 1
        except ValueError:
            return None
        return bool(counters.get(idx, False))
    if token.startswith("T"):
        try:
            idx = int(token[1:]) - 1
        except ValueError:
            return None
        return bool(timers.get(idx, False))
    return None


def compute_plc_states(components, terminal_nodes, dc_voltages, ac_voltages, sim_time_ms):
    states = {}
    meta = {}
    now = int(sim_time_ms) if sim_time_ms is not None else int(time.time() * 1000)
    for comp in components:
        if comp.get("type") != "plc":
            continue
        props = comp.get("props", {})
        inputs_count = max(1, min(64, int(props.get("inputs", 4))))
        outputs_count = max(1, min(64, int(props.get("outputs", 4))))
        threshold = float(props.get("inputThreshold", 9))
        inputs = [False] * inputs_count
        outputs = [False] * outputs_count
        plc_state = props.get("plcState", {}) or {}
        timers_state = plc_state.get("timers", {})
        memories_state = plc_state.get("mem", {})
        counters_state = plc_state.get("counters", {})
        trig_state = plc_state.get("trig", {})
        timers_output = {}
        counters_output = {}
        next_tick_ms = None
        if isinstance(memories_state, dict):
            normalized_mem = {}
            for key, value in memories_state.items():
                if isinstance(key, int):
                    normalized_mem[key] = value
                    continue
                if isinstance(key, str) and key.isdigit():
                    normalized_mem[int(key)] = value
            memories_state = normalized_mem
        else:
            memories_state = {}
        for key, data in counters_state.items():
            if not key.startswith("C"):
                continue
            try:
                idx = int(key[1:]) - 1
            except ValueError:
                continue
            counters_output[idx] = bool(data.get("q", False))
        node_m = terminal_nodes.get(f"{comp['id']}:0")
        for idx in range(inputs_count):
            node_i = terminal_nodes.get(f"{comp['id']}:{2 + idx}")
            if node_m is None or node_i is None:
                continue
            dv = 0.0
            if dc_voltages is not None and node_m < len(dc_voltages) and node_i < len(dc_voltages):
                dv = max(dv, abs(dc_voltages[node_i] - dc_voltages[node_m]))
            if ac_voltages is not None and node_m < len(ac_voltages) and node_i < len(ac_voltages):
                dv = max(dv, abs(ac_voltages[node_i] - ac_voltages[node_m]))
            inputs[idx] = dv + EPSILON_V >= threshold

        program = props.get("program", "")
        language = props.get("language", "LAD")
        if language != "LAD":
            states[comp["id"]] = outputs
            meta[comp["id"]] = {
                "timers": timers_state,
                "mem": memories_state,
                "counters": counters_state,
                "trig": trig_state,
                "trace": ["PLC-sprak ej stodt (endast LAD)."],
            }
            continue
        acc = None
        trace = []
        if program.strip():
            inputs_snapshot = ", ".join(
                f"I{idx + 1}={'1' if value else '0'}" for idx, value in enumerate(inputs)
            )
            trace.append(f"Inputs: {inputs_snapshot}")
        else:
            trace.append("Inget PLC-program angivet.")
        for raw in program.splitlines():
            line = raw.strip()
            if not line:
                acc = None
                continue
            if ";" in line:
                line = line.split(";", 1)[0].strip()
                if not line:
                    continue
            if line.startswith("//") or line.startswith("#"):
                continue
            parts = line.replace("=", " = ").split()
            if not parts:
                continue
            op = parts[0].upper()
            if op == "L" and len(parts) >= 2:
                operand = _parse_plc_operand(
                    parts[1], inputs, outputs, timers_output, memories_state, counters_output
                )
                if operand is None:
                    continue
                acc = operand
                trace.append(f"{line} -> ACC={'1' if acc else '0'}")
                continue
            if op == "MOVE" and len(parts) >= 3:
                operand = _parse_plc_operand(
                    parts[1], inputs, outputs, timers_output, memories_state, counters_output
                )
                if operand is None:
                    continue
                acc = operand
                target = parts[2].upper()
                if target.startswith("Q"):
                    try:
                        idx = int(target[1:]) - 1
                    except ValueError:
                        continue
                    if 0 <= idx < outputs_count:
                        outputs[idx] = bool(acc)
                if target.startswith("M"):
                    try:
                        idx = int(target[1:]) - 1
                    except ValueError:
                        continue
                    if idx >= 0:
                        memories_state[idx] = bool(acc)
                trace.append(f"{line} -> ACC={'1' if acc else '0'}")
                acc = None
                continue
            if op in {"A", "AN", "O", "ON", "U", "UN"} and len(parts) >= 2:
                operand = _parse_plc_operand(
                    parts[1], inputs, outputs, timers_output, memories_state, counters_output
                )
                if operand is None:
                    continue
                if op in {"AN", "UN"}:
                    operand = not operand
                if op == "ON":
                    operand = not operand
                if acc is None:
                    acc = operand
                else:
                    acc = acc and operand if op in {"A", "AN", "U", "UN"} else acc or operand
                trace.append(f"{line} -> ACC={'1' if acc else '0'}")
                continue
            if op in {"TON", "TOF", "TP"} and len(parts) >= 3:
                timer_id = parts[1].upper()
                if not timer_id.startswith("T"):
                    continue
                try:
                    t_index = int(timer_id[1:]) - 1
                except ValueError:
                    continue
                try:
                    delay_s = float(parts[2])
                except ValueError:
                    delay_s = 0.0
                delay_ms = max(0, int(delay_s * 1000))
                t_state = timers_state.get(timer_id, {})
                prev_in = bool(t_state.get("in", False))
                output = bool(t_state.get("q", False))
                start_at = t_state.get("startAt")
                acc_value = bool(acc) if acc is not None else False

                if op == "TON":
                    if acc_value:
                        if not prev_in:
                            start_at = now
                        elapsed = max(0, now - (start_at or now))
                        output = elapsed >= delay_ms
                        if not output and start_at is not None and delay_ms > 0:
                            remaining = max(0, delay_ms - elapsed)
                            if remaining > 0:
                                next_tick_ms = remaining if next_tick_ms is None else min(next_tick_ms, remaining)
                    else:
                        output = False
                        start_at = None
                elif op == "TOF":
                    if acc_value:
                        output = True
                        start_at = None
                    else:
                        if prev_in:
                            start_at = now
                        elapsed = max(0, now - (start_at or now))
                        output = elapsed < delay_ms
                        if output and start_at is not None and delay_ms > 0:
                            remaining = max(0, delay_ms - elapsed)
                            if remaining > 0:
                                next_tick_ms = remaining if next_tick_ms is None else min(next_tick_ms, remaining)
                elif op == "TP":
                    if acc_value and not prev_in:
                        start_at = now
                        output = True
                    if start_at is not None:
                        elapsed = max(0, now - start_at)
                        output = elapsed < delay_ms
                        if not output:
                            start_at = None
                    if not acc_value and start_at is None:
                        output = False
                    if output and start_at is not None and delay_ms > 0:
                        remaining = max(0, delay_ms - (now - start_at))
                        if remaining > 0:
                            next_tick_ms = remaining if next_tick_ms is None else min(next_tick_ms, remaining)

                timers_state[timer_id] = {"in": acc_value, "q": output, "startAt": start_at}
                timers_output[t_index] = output
                acc = output
                trace.append(f"{line} -> ACC={'1' if acc else '0'}")
                continue
            if op in {"CTU", "CTD"} and len(parts) >= 2:
                counter_id = parts[1].upper()
                if not counter_id.startswith("C"):
                    continue
                try:
                    c_index = int(counter_id[1:]) - 1
                except ValueError:
                    continue
                pv = None
                for token in parts[2:]:
                    if token.upper().startswith("PV="):
                        try:
                            pv = int(float(token.split("=", 1)[1]))
                        except ValueError:
                            pv = None
                    else:
                        try:
                            pv = int(float(token))
                        except ValueError:
                            continue
                c_state = counters_state.get(counter_id, {})
                if pv is None:
                    pv = int(c_state.get("pv", 1))
                if op == "CTD" and not c_state:
                    c_state = {"cv": pv, "pv": pv, "cu": False, "q": False}
                cv = int(c_state.get("cv", 0))
                prev_cu = bool(c_state.get("cu", False))
                acc_value = bool(acc) if acc is not None else False
                if acc_value and not prev_cu:
                    if op == "CTU":
                        cv += 1
                    else:
                        cv = max(0, cv - 1)
                if op == "CTU":
                    q = cv >= pv
                else:
                    q = cv <= 0
                counters_state[counter_id] = {"cv": cv, "pv": pv, "cu": acc_value, "q": q}
                counters_output[c_index] = q
                acc = q
                trace.append(f"{line} -> ACC={'1' if acc else '0'}")
                continue
            if op in {"R_TRIG", "F_TRIG"} and len(parts) >= 2:
                target = parts[1].upper()
                acc_value = bool(acc) if acc is not None else False
                prev = bool(trig_state.get(target, False))
                if op == "R_TRIG":
                    pulse = acc_value and not prev
                else:
                    pulse = (not acc_value) and prev
                trig_state[target] = acc_value
                if target.startswith("M"):
                    try:
                        idx = int(target[1:]) - 1
                    except ValueError:
                        continue
                    if idx >= 0:
                        memories_state[idx] = pulse
                if target.startswith("Q"):
                    try:
                        idx = int(target[1:]) - 1
                    except ValueError:
                        continue
                    if 0 <= idx < outputs_count:
                        outputs[idx] = pulse
                acc = pulse
                trace.append(f"{line} -> ACC={'1' if acc else '0'}")
                continue
            if op == "=" and len(parts) >= 2:
                target = parts[1].upper()
            elif op.startswith("="):
                target = op[1:].upper()
            else:
                if op in {"S", "R"} and len(parts) >= 2:
                    target = parts[1].upper()
                elif op == "T" and len(parts) >= 2:
                    target = parts[1].upper()
                    if target.startswith("Q"):
                        try:
                            idx = int(target[1:]) - 1
                        except ValueError:
                            continue
                        if 0 <= idx < outputs_count:
                            outputs[idx] = bool(acc)
                    if target.startswith("M"):
                        try:
                            idx = int(target[1:]) - 1
                        except ValueError:
                            continue
                        if idx >= 0:
                            memories_state[idx] = bool(acc)
                    trace.append(f"{line} -> ACC={'1' if acc else '0'}")
                    continue
                else:
                    continue
            if target.startswith("Q"):
                try:
                    idx = int(target[1:]) - 1
                except ValueError:
                    continue
                if 0 <= idx < outputs_count:
                    acc_value = bool(acc) if acc is not None else False
                    if op == "R":
                        if acc_value:
                            outputs[idx] = False
                    elif op == "S":
                        if acc_value:
                            outputs[idx] = True
                    else:
                        outputs[idx] = bool(acc)
            if target.startswith("M"):
                try:
                    idx = int(target[1:]) - 1
                except ValueError:
                    continue
                if idx >= 0:
                    acc_value = bool(acc) if acc is not None else False
                    if op == "R":
                        if acc_value:
                            memories_state[idx] = False
                    elif op == "S":
                        if acc_value:
                            memories_state[idx] = True
                    else:
                        memories_state[idx] = bool(acc)
            if target.startswith("C") and op in {"R", "S"}:
                try:
                    idx = int(target[1:]) - 1
                except ValueError:
                    continue
                if idx >= 0:
                    acc_value = bool(acc) if acc is not None else False
                    if not acc_value:
                        acc = None
                        continue
                    key = f"C{idx + 1}"
                    c_state = counters_state.get(key, {})
                    pv = int(c_state.get("pv", 1))
                    if op == "R":
                        counters_state[key] = {"cv": 0, "pv": pv, "cu": False, "q": False}
                        counters_output[idx] = False
                    else:
                        counters_state[key] = {"cv": pv, "pv": pv, "cu": False, "q": True}
                        counters_output[idx] = True
            trace.append(f"{line} -> ACC={'1' if acc else '0'}")
        outputs_snapshot = ", ".join(
            f"Q{idx + 1}={'1' if value else '0'}" for idx, value in enumerate(outputs)
        )
        trace.append(f"Outputs: {outputs_snapshot}")
        if len(trace) > 200:
            trace = trace[:200] + [f"... {len(trace) - 200} rader till ..."]
        states[comp["id"]] = outputs
        meta[comp["id"]] = {
            "timers": timers_state,
            "mem": memories_state,
            "counters": counters_state,
            "trig": trig_state,
            "trace": trace,
        }
        if next_tick_ms is not None:
            meta[comp["id"]]["nextTickMs"] = int(next_tick_ms)
    return states, meta


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
    plc_states = {}
    plc_meta = {}
    for comp in components:
        if comp.get("type") == "plc":
            outputs = max(1, min(64, int(comp.get("props", {}).get("outputs", 4))))
            plc_states[comp["id"]] = [False] * outputs
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
        dc_model = build_model_dc(components, wires, contactor_states, timer_states, plc_states)
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
            ac_model = build_model_ac(components, wires, contactor_states, timer_states, plc_states, freq)
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
        updated_plc, updated_plc_meta = compute_plc_states(
            components,
            terminal_nodes,
            dc_solution["node_voltages"] if dc_solution else None,
            ac_solution["node_voltages"] if ac_solution else None,
            sim_time,
        )
        plc_meta = updated_plc_meta
        if (
            updated == contactor_states
            and updated_timers == timer_states
            and updated_plc == plc_states
        ):
            break
        contactor_states = updated
        timer_states = updated_timers
        plc_states = updated_plc

    return {
        "components": components,
        "terminal_nodes": dc_model["terminal_nodes"],
        "contactor_states": contactor_states,
        "timer_states": timer_states,
        "plc_states": plc_states,
        "plc_meta": plc_meta,
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
        "plcStates": result.get("plc_states", {}),
        "plcMeta": result.get("plc_meta", {}),
        "debugInfo": result.get("debug_info", {}),
    }
