#!/usr/bin/env python3

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


CONFIG_DIR = Path(os.environ.get("PDP_CONFIG_DIR", "/mnt/shared/island_mode"))

IDENTITY_CACHE_PATH = CONFIG_DIR / "identity_cache.json"
SERVICE_REGISTRY_PATH = CONFIG_DIR / "service_registry.json"
POLICY_MODEL_PATH = CONFIG_DIR / "policy_model.json"

HOST = os.environ.get("PDP_HOST", "127.0.0.1")
PORT = int(os.environ.get("PDP_PORT", "8088"))


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

def load_model() -> tuple[dict, dict, dict]:
    identities = load_json(IDENTITY_CACHE_PATH)
    services = load_json(SERVICE_REGISTRY_PATH)
    policies = load_json(POLICY_MODEL_PATH)
    return identities, services, policies

def identity_denial_reason(actor_data: dict) -> str | None:
    status = actor_data.get("status")
    quarantined = actor_data.get("quarantined", False)
    risk = int(actor_data.get("risk", 100))

    if status != "valid":
        return "local identity status is not valid"

    if quarantined:
        return "local identity is quarantined"

    if risk > 50:
        return "local identity risk is too high"

    return None


def actor_is_locally_authenticated(actor_data: dict) -> bool:
    return identity_denial_reason(actor_data) is None

def matching_actors(identities: dict, role: str) -> dict:
    if role == "*":
        return identities

    return {
        name: data
        for name, data in identities.items()
        if data.get("role") == role
    }


def matching_services(services: dict, service_class: str) -> dict:
    if service_class == "*":
        return services

    return {
        name: data
        for name, data in services.items()
        if data.get("class") == service_class
    }


def priority_for_rule(action: str, role: str, service_class: str) -> int:
    if action == "allow":
        return 500

    if role != "*" and service_class != "*":
        return 490

    return 480

def compile_policy(mode: str) -> list[dict[str, Any]]:
    identities, services, policies = load_model()

    mode = mode.upper()
    mode_policy = policies.get(mode, [])

    compiled = []

    for rule in mode_policy:
        role = rule["role"]
        service_class = rule["service_class"]
        action = rule["action"]
        reason = rule.get("reason", "no reason provided")

        actors = matching_actors(identities, role)
        target_services = matching_services(services, service_class)
        priority = priority_for_rule(action, role, service_class)

        for service_name, service_data in target_services.items():
            dst_ip = service_data["ip"]

            if role == "*" and action == "deny":
                compiled.append({
                    "mode": mode,
                    "actor": "*",
                    "role": "*",
                    "src_ip": None,
                    "src_mac": None,
                    "service": service_name,
                    "service_class": service_class,
                    "dst_ip": dst_ip,
                    "action": "deny",
                    "priority": priority,
                    "reason": reason
                })
                continue

            for actor_name, actor_data in actors.items():
                src_ip = actor_data["ip"]
                src_mac = actor_data.get("mac")

                deny_reason = identity_denial_reason(actor_data)

                if action == "allow" and deny_reason is not None:
                    compiled.append({
                        "mode": mode,
                        "actor": actor_name,
                        "role": actor_data.get("role"),
                        "src_ip": src_ip,
                        "src_mac": src_mac,
                        "service": service_name,
                        "service_class": service_class,
                        "dst_ip": dst_ip,
                        "action": "deny",
                        "priority": 490,
                        "reason": deny_reason
                    })
                    continue

                compiled.append({
                    "mode": mode,
                    "actor": actor_name,
                    "role": actor_data.get("role"),
                    "src_ip": src_ip,
                    "src_mac": src_mac,
                    "service": service_name,
                    "service_class": service_class,
                    "dst_ip": dst_ip,
                    "action": action,
                    "priority": priority,
                    "reason": reason
                })

    return compiled

def authorize(actor: str, service: str, mode: str) -> dict:
    compiled = compile_policy(mode)

    matching_rules = [
        rule for rule in compiled
        if rule["actor"] in [actor, "*"] and rule["service"] == service
    ]

    if matching_rules:
        best_rule = max(matching_rules, key=lambda rule: rule.get("priority", 0))

        return {
            "actor": actor,
            "service": service,
            "mode": mode.upper(),
            "decision": best_rule["action"],
            "reason": best_rule["reason"]
        }

    return {
        "actor": actor,
        "service": service,
        "mode": mode.upper(),
        "decision": "deny",
        "reason": "no matching policy rule"
    }

def update_identity(actor: str, updates: dict) -> dict:
    identities = load_json(IDENTITY_CACHE_PATH)

    if actor not in identities:
        return {
            "ok": False,
            "error": f"unknown actor: {actor}"
        }

    allowed_fields = {"status", "risk", "quarantined", "role", "zone", "mac"}

    for key, value in updates.items():
        if key in allowed_fields:
            identities[actor][key] = value

    save_json(IDENTITY_CACHE_PATH, identities)

    return {
        "ok": True,
        "actor": actor,
        "identity": identities[actor]
    }


class PDPHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict | list) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}

        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "local-pdp"})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            request = self._read_json()

            if self.path == "/compile":
                mode = request.get("mode", "ISLANDED")
                rules = compile_policy(mode)
                self._send_json(200, {
                    "mode": mode.upper(),
                    "rules": rules
                })
                return

            if self.path == "/authorize":
                actor = request["actor"]
                service = request["service"]
                mode = request.get("mode", "ISLANDED")
                decision = authorize(actor, service, mode)
                self._send_json(200, decision)
                return
            if self.path == "/identity/update":
                actor = request["actor"]
                updates = request.get("updates", {})
                result = update_identity(actor, updates)

                status = 200 if result.get("ok") else 404
                self._send_json(status, result)
                return

            if self.path == "/identity/revoke":
                actor = request["actor"]
                result = update_identity(actor, {
                    "status": "revoked",
                    "risk": 90,
                    "quarantined": True
                })

                status = 200 if result.get("ok") else 404
                self._send_json(status, result)
                return

            if self.path == "/identity/validate":
                actor = request["actor"]
                result = update_identity(actor, {
                    "status": "valid",
                    "risk": 10,
                    "quarantined": False
                })

                status = 200 if result.get("ok") else 404
                self._send_json(status, result)
                return

            if self.path == "/identity/quarantine":
                actor = request["actor"]
                result = update_identity(actor, {
                    "quarantined": True,
                    "risk": 90
                })

                status = 200 if result.get("ok") else 404
                self._send_json(status, result)
                return

            if self.path == "/identity/unquarantine":
                actor = request["actor"]
                result = update_identity(actor, {
                    "quarantined": False,
                    "risk": 10
                })

                status = 200 if result.get("ok") else 404
                self._send_json(status, result)
                return
            self._send_json(404, {"error": "not found"})

        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    server = HTTPServer((HOST, PORT), PDPHandler)
    print(f"[pdp] local PDP service listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
