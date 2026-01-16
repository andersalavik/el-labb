import math

from flask import Blueprint, jsonify, render_template, request

from api.storage import delete_save, list_saves, load_snapshot, safe_name, save_snapshot
from sim.core import Complex, build_model_dc, get_ac_frequency, simulate_circuit, solve_mna, solve_network

blueprint = Blueprint("routes", __name__)


@blueprint.get("/")
def index():
    return render_template("index.html")


@blueprint.post("/api/simulate")
def api_simulate():
    payload = request.get_json(silent=True) or {}
    result = simulate_circuit(payload)
    if "error" in result:
        return jsonify({"error": result["error"]}), 400
    return jsonify(result)


@blueprint.post("/api/measure")
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
            result.get("plc_states", {}),
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


@blueprint.get("/api/saves")
def api_saves_list():
    return jsonify({"saves": list_saves()})


@blueprint.post("/api/saves")
def api_saves_save():
    payload = request.get_json(silent=True) or {}
    name = safe_name(payload.get("name", ""))
    snapshot = payload.get("snapshot")
    if not name:
        return jsonify({"error": "Namn saknas."}), 400
    if snapshot is None:
        return jsonify({"error": "Snapshot saknas."}), 400

    try:
        record = save_snapshot(name, snapshot, payload.get("id"))
    except OSError:
        return jsonify({"error": "Kunde inte spara filen."}), 500

    return jsonify({"save": {"id": record["id"], "name": name, "updatedAt": record["updatedAt"]}})


@blueprint.get("/api/saves/<save_id>")
def api_saves_load(save_id):
    snapshot = load_snapshot(save_id)
    if snapshot is None:
        return jsonify({"error": "Sparning hittades inte."}), 404
    return jsonify({"snapshot": snapshot})


@blueprint.delete("/api/saves/<save_id>")
def api_saves_delete(save_id):
    result = delete_save(save_id)
    if result is None:
        return jsonify({"error": "Kunde inte ta bort sparning."}), 500
    if result is False:
        return jsonify({"error": "Sparning hittades inte."}), 404
    return jsonify({"ok": True})


def register_routes(app):
    app.register_blueprint(blueprint)
