"""Local, single-user writing workspace. Run: python -m ui.server."""

import argparse
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from debate_engine.agents import RoundDirector
from debate_engine.agents.evaluation import EvaluationAgent, fingerprint, select_architecture
from debate_engine.agents.strategy_provider import inference_ready, provider_settings
from debate_engine.config import get_settings
from debate_engine.schemas.case import CaseResult, SpeechBudget
from debate_engine.schemas.rounds import RoundInput
from ui.workflow import load_checkpoint, unresolved_findings

WEB = Path(__file__).parent / "web"


class Workspace:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.lock = threading.RLock()
        self.outputs = {}
        self.round = None
        self.job = None
        self.notice = "Start a round or open a saved run."
        self.started = None
        self.timings = {}
        self.run_dir = None

    def checkpoints(self):
        root = self.settings.project_root / "data/parsed"
        return sorted(str(p.parent.relative_to(root)) for p in root.rglob("strategy.json"))

    def snapshot(self):
        with self.lock:
            result = {k: v.model_dump(mode="json") for k, v in self.outputs.items()}
            evaluation = self.outputs.get("evaluation")
            risks = {}
            if evaluation:
                for i in (1, 2, 3):
                    risks[str(i)] = [
                        {"finding": f.model_dump(), "response": r.model_dump() if r else None}
                        for f, r in unresolved_findings(evaluation, i)
                    ]
            return {
                "outputs": result,
                "round": self.round.model_dump() if self.round else None,
                "job": self.job,
                "notice": self.notice,
                "started": self.started,
                "timings": self.timings,
                "risks": risks,
                "profile": self.round.prep_rules.profile if self.round else None,
                "provider": self.settings.strategy.provider.value,
                "model": provider_settings(self.settings).model or "Provider default",
                "inference_ready": inference_ready(self.settings),
                "research_configured": bool(self.settings.research.api_key),
                "checkpoints": self.checkpoints(),
            }

    def save(self, name, value):
        if self.run_dir is None:
            root = self.settings.project_root / "data/parsed"
            self.run_dir = root / (
                "workspace-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
            )
            self.run_dir.mkdir(parents=True)
        path = self.run_dir / f"{name}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(value.model_dump_json(indent=2))
        temp.replace(path)

    def action(self, action, body):
        with self.lock:
            if self.job and self.job["status"] == "running":
                raise ValueError("A stage is running. Wait for it before changing the round.")
            if action == "round":
                current = RoundInput.model_validate(body)
                if self.round != current:
                    self.outputs = {}
                    self.started = None
                    self.timings = {}
                    self.run_dir = None
                    self.notice = "Round saved. Dependent outputs cleared."
                else:
                    self.notice = "Unchanged round reused."
                self.round = current
                self.job = None
            elif action == "timer":
                if not self.round or self.round.side not in {"aff", "gov", "neg", "opp"}:
                    raise ValueError("Confirm a concrete side first.")
                if self.started is None:
                    self.started = time.time()
                self.notice = "Prep timer started; it does not cancel engine requests."
            elif action == "load":
                name = body.get("name")
                if name not in self.checkpoints():
                    raise ValueError("Choose an available checkpoint.")
                root = (self.settings.project_root / "data/parsed").resolve()
                path = (root / name).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("Invalid checkpoint path.")
                restored = load_checkpoint(path)
                outputs = {
                    "packet": restored["round_output"],
                    "strategy": restored["strategy_output"],
                }
                evaluation = restored.get("evaluation_output")
                if evaluation:
                    outputs["evaluation"] = evaluation
                    for casepath in sorted(
                        path.glob("case*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True
                    ):
                        try:
                            case = CaseResult.model_validate_json(casepath.read_text())
                        except ValueError:
                            continue
                        if (
                            case.status == "completed"
                            and case.packet_fingerprint == fingerprint(outputs["packet"])
                            and case.strategy_fingerprint == fingerprint(outputs["strategy"])
                            and case.evaluation_fingerprint == fingerprint(evaluation)
                        ):
                            outputs["case"] = case
                            break
                self.outputs = outputs
                self.round = outputs["packet"].plan.round_input
                self.run_dir = None  # Never overwrite an imported historical run.
                self.started = None
                self.timings = {}
                self.job = None
                self.notice = "Saved run loaded locally. No model or research request made."
            elif action == "select":
                evaluation = self.outputs.get("evaluation")
                if not evaluation:
                    raise ValueError("Evaluate strategies first.")
                choice = body.get("id")
                if type(choice) is not int or choice not in (1, 2, 3):
                    raise ValueError("Choose option 1, 2 or 3.")
                if evaluation.selected_architecture_id != choice:
                    self.outputs.pop("case", None)
                    self.outputs["evaluation"] = select_architecture(evaluation, choice)
                    self.persist()
                self.notice = f"Option {choice} selected. Any dependent case was cleared."
            elif action in {"prepare", "strategize", "evaluate", "resume", "write"}:
                self.start_job(action, body)
            else:
                raise ValueError("Unknown action.")

    def persist(self):
        # Save a new complete checkpoint; keep prior selections and stages intact.
        self.run_dir = None
        for key, value in self.outputs.items():
            self.save(key, value)

    def start_job(self, action, body):
        if not self.round:
            raise ValueError("Save round settings first.")
        requirements = {
            "prepare": [],
            "strategize": ["packet"],
            "evaluate": ["packet", "strategy"],
            "resume": ["packet", "strategy", "evaluation"],
            "write": ["packet", "strategy", "evaluation"],
        }
        if any(k not in self.outputs for k in requirements[action]):
            raise ValueError("Complete the preceding stage first.")
        if action != "prepare" and not self.round.prep_rules.inference_permitted:
            raise ValueError("Enable cloud inference in round settings first.")
        if action == "write" and not self.outputs["evaluation"].selected_architecture_id:
            raise ValueError("Select an evaluated strategy before writing.")
        if action == "prepare" and "packet" in self.outputs:
            self.notice = "Reused the unchanged packet. Edit round settings to prepare again."
            return
        budget = SpeechBudget.model_validate(body.get("budget", {}))
        preferences = body.get("preferences", "")
        if not isinstance(preferences, str) or len(preferences) > 3000:
            raise ValueError("Strategy preferences must be at most 3,000 characters.")
        previous = dict(self.outputs)
        current = self.round
        target = {
            "prepare": "packet",
            "strategize": "strategy",
            "evaluate": "evaluation",
            "resume": "evaluation",
            "write": "case",
        }[action]
        order = ["packet", "strategy", "evaluation", "case"]
        for key in order[order.index(target) :]:
            self.outputs.pop(key, None)
        self.job = {"stage": action, "status": "running", "started": time.time()}
        self.notice = "Working. You can move between pages while this stage runs."

        def work():
            start = time.perf_counter()
            try:
                director = RoundDirector(self.settings)
                if action == "prepare":
                    result = director.prepare(current)
                elif action == "strategize":
                    result = director.strategize(previous["packet"], preferences=preferences)
                elif action == "evaluate":
                    result = director.evaluate(previous["packet"], previous["strategy"])
                elif action == "resume":
                    result = EvaluationAgent(self.settings).evaluate(
                        previous["packet"], previous["strategy"], checkpoint=previous["evaluation"]
                    )
                else:
                    result = director.write_case(
                        previous["packet"],
                        previous["strategy"],
                        previous["evaluation"],
                        budget=budget,
                    )
                with self.lock:
                    self.outputs[target] = result
                    self.timings[action] = round(time.perf_counter() - start, 2)
                    if action == "prepare":
                        self.timings.update(director.preparation_timings)
                    self.persist()
                    status = getattr(result, "status", "completed")
                    self.job = {"stage": action, "status": status}
                    self.notice = (
                        f"{action.title()}: {status}. Review the result before continuing."
                    )
            except Exception:
                with self.lock:
                    # Retain the last accepted checkpoint after transport/save exceptions.
                    self.outputs = previous
                    self.job = {"stage": action, "status": "failed"}
                    self.notice = (
                        "Stage failed. Previous work retained; check configuration/indexes."
                    )
                    self.timings[action] = round(time.perf_counter() - start, 2)

        threading.Thread(target=work, daemon=True).start()


def make_server(port=8768, workspace=None):
    workspace = workspace or Workspace()
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, value, code=200, mime="application/json"):
            data = json.dumps(value).encode() if mime == "application/json" else value
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; "
                "script-src 'self'; frame-ancestors 'none'; connect-src 'self'",
            )
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get("Host") in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }

        def do_GET(self):
            if not self.valid_host():
                return self.send({"error": "Local access only."}, 403)
            path = urlsplit(self.path).path
            if path == "/api/state":
                return self.send({**workspace.snapshot(), "token": token})
            if path in {"/api/download/json", "/api/download/markdown"}:
                with workspace.lock:
                    case = workspace.outputs.get("case")
                    if not case or case.status != "completed":
                        return self.send({"error": "No completed case."}, 404)
                    if path.endswith("json"):
                        return self.send(case.model_dump(mode="json"))
                    return self.send(case.markdown.encode(), mime="text/plain; charset=utf-8")
            files = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if path not in files:
                return self.send({"error": "Not found."}, 404)
            name, mime = files[path]
            return self.send((WEB / name).read_bytes(), mime=mime)

        def do_POST(self):
            origin = self.headers.get("Origin")
            if (
                not self.valid_host()
                or self.headers.get("X-Workspace-Token") != token
                or (origin and origin != f"http://{self.headers.get('Host')}")
            ):
                return self.send({"error": "Local workspace authorization required."}, 403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 100_000:
                    raise ValueError("Request size invalid.")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Expected an object.")
                workspace.action(urlsplit(self.path).path.removeprefix("/api/"), body)
                return self.send(workspace.snapshot())
            except (ValueError, KeyError):
                return self.send(
                    {
                        "error": "Invalid request or unavailable stage. Check your inputs "
                        "and finish any running stage first."
                    },
                    400,
                )
            except Exception:
                return self.send({"error": "Unable to load or save this workspace."}, 500)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    server = make_server(args.port)
    print(f"Writing workspace: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
