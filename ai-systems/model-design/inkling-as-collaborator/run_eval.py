#!/usr/bin/env python3
"""Local web interface for running the behavior-eval prompts against a model under test.

Start it with:
    python3 run_eval.py
and use the page it opens (http://127.0.0.1:8765).

- Each prompt is sent alone, as the first message of a fresh conversation. Only the
  `prompt` text is sent; `category`, `primary_trait` and `probe` never leave this machine.
- Responses are written to the output JSON after every prompt, so a stopped or crashed
  run picks up where it left off ("Run unanswered prompts").
- The API key stays in memory only. Paste it into the page, or start the server with
  EVAL_API_KEY set (TINKER_API_KEY also works for Thinking Machines' Tinker API, which
  serves Inkling). It is never written to the output file.
- When the API returns the model's reasoning separately, it is saved in
  response_meta.reasoning; model_response holds only the final answer.

Standard library only; works with the macOS system Python (3.9+).
"""

import argparse
import copy
import http.client
import json
import os
import queue
import random
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_DIR = Path(__file__).resolve().parent
UI_FILE = PROJECT_DIR / "eval_ui.html"
DEFAULT_INPUT = "behavior_eval_prompts.json"
DEFAULT_OUTPUT = "behavior_eval_outputs.json"

REQUEST_TIMEOUT = 600  # seconds per API call; reasoning models can take minutes
MAX_ATTEMPTS = 6  # first try plus retries for rate limits and server errors
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
FATAL_STATUS = {401, 402, 403, 404}  # bad key, billing, permissions, wrong model or URL
EARLY_FAILURE_LIMIT = 3  # stop a run if this many prompts fail before any succeeds
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_DEFAULT_MAX_TOKENS = 16000  # the Messages API requires max_tokens
TINKER_HOST = "tinker.thinkingmachines.dev"  # Thinking Machines' API, which serves Inkling
# Python's default User-Agent is blocked by Cloudflare on some APIs (Tinker answers 403 "error code: 1010").
USER_AGENT = "behavior-eval-runner/1.0"
CONVERSATION_MODE = (
    "Each prompt was sent alone as the first user message of a new conversation. "
    "Only the `prompt` text was sent; category, primary_trait and probe were not."
)
REASONING_NOTE = (
    "model_response holds only the model's final answer. When the API returned the model's reasoning, "
    "it is saved in response_meta.reasoning instead. The flag reasoning_split means the reasoning came "
    "back inline (ending in </think>) and was moved out of the answer."
)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UserError(ValueError):
    """A problem the person can fix from the page; shown to them as-is."""


class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status

    @property
    def fatal(self):
        return self.status in FATAL_STATUS


class StopRequested(Exception):
    pass


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def parse_config(raw):
    """Validate the settings sent from the page and fill in defaults."""
    if not isinstance(raw, dict):
        raise UserError("Missing connection settings.")
    provider = raw.get("provider")
    if provider not in ("openai", "anthropic"):
        raise UserError("Unknown API format: %r" % provider)
    base_url = (raw.get("base_url") or "").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise UserError("The base URL must start with https:// (or http:// for a local server).")
    model = (raw.get("model") or "").strip()
    if not model:
        raise UserError("Enter the model name.")
    try:
        temperature = raw.get("temperature")
        temperature = None if temperature in (None, "") else float(temperature)
        max_tokens = raw.get("max_tokens")
        max_tokens = None if max_tokens in (None, "") else int(max_tokens)
        parallel = max(1, min(8, int(raw.get("parallel") or 1)))
    except (TypeError, ValueError):
        raise UserError("Temperature, max output tokens and parallel requests must be numbers.")
    if provider == "anthropic" and max_tokens is None:
        max_tokens = ANTHROPIC_DEFAULT_MAX_TOKENS
    extra = raw.get("extra_params") or {}
    if not isinstance(extra, dict):
        raise UserError("Extra request parameters must be a JSON object.")
    system_prompt = raw.get("system_prompt") or ""
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": (raw.get("api_key") or "").strip() or env_api_key(base_url),
        "system_prompt": system_prompt if system_prompt.strip() else "",
        "temperature": temperature,
        "max_tokens": max_tokens,
        "extra_params": extra,
        "parallel": parallel,
    }


def env_api_key(base_url):
    """Key from the environment: EVAL_API_KEY, or TINKER_API_KEY but only for Tinker's own URLs."""
    if os.environ.get("EVAL_API_KEY"):
        return os.environ["EVAL_API_KEY"]
    if urlparse(base_url).hostname == TINKER_HOST:
        return os.environ.get("TINKER_API_KEY", "")
    return ""


def recorded_settings(cfg):
    """The part of the config that shapes the outputs, as written to the output file.

    Never includes the API key. None means the provider's default was used.
    """
    return {
        "api_format": "anthropic-messages" if cfg["provider"] == "anthropic" else "openai-chat-completions",
        "base_url": cfg["base_url"],
        "model_requested": cfg["model"],
        "system_prompt": cfg["system_prompt"] or None,
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
        "extra_params": cfg["extra_params"],
    }


# ---------------------------------------------------------------------------
# Calling the model
# ---------------------------------------------------------------------------

def error_message(http_error):
    try:
        body = http_error.read().decode("utf-8", "replace")
    except Exception:
        return http_error.reason or "no details"
    try:
        parsed = json.loads(body)
        err = parsed.get("error") or parsed.get("detail")  # Tinker reports errors as {"detail": ...}
        if isinstance(err, dict) and err.get("message"):
            return err["message"]
        if isinstance(err, str):
            return err
        if err:
            return json.dumps(err)[:400]
    except (ValueError, AttributeError):
        pass
    return body.strip()[:400] or str(http_error.reason)


def backoff_delay(attempt, retry_after):
    try:
        return min(float(retry_after), 120.0)
    except (TypeError, ValueError):
        return min(60.0, 2.0 ** attempt) + random.uniform(0, 1)


def post_json(url, headers, body, stop_event=None):
    """POST a JSON body and return (parsed reply, attempts), retrying transient failures."""
    data = json.dumps(body).encode("utf-8")
    headers = dict(headers)
    headers["Content-Type"] = "application/json"
    headers["User-Agent"] = USER_AGENT
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        retry_after = None
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                raw = response.read().decode("utf-8", "replace")
            try:
                return json.loads(raw), attempt
            except ValueError:
                raise ApiError("The API replied with something other than JSON: %s" % raw.strip()[:200])
        except urllib.error.HTTPError as e:
            if e.code not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
                raise ApiError("HTTP %d: %s" % (e.code, error_message(e)), e.code)
            retry_after = e.headers.get("retry-after")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                http.client.HTTPException) as e:
            if attempt == MAX_ATTEMPTS:
                raise ApiError("Network error: %s" % getattr(e, "reason", e))
        delay = backoff_delay(attempt, retry_after)
        if stop_event is None:
            time.sleep(delay)
        elif stop_event.wait(delay):
            raise StopRequested()
    raise ApiError("Gave up after %d attempts." % MAX_ATTEMPTS)


def parse_anthropic(data):
    if data.get("type") == "error":
        raise ApiError("API error: %s" % (data.get("error") or {}).get("message", data))
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    reasoning = "\n\n".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking").strip()
    usage = data.get("usage") or {}
    result = {
        "text": text,
        "reasoning": reasoning,
        "model": data.get("model"),
        "finish_reason": data.get("stop_reason"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "api_refusal": data.get("stop_reason") == "refusal",
    }
    if data.get("stop_details"):
        result["stop_details"] = data["stop_details"]
    return result


def parse_openai(data):
    if data.get("error") and not data.get("choices"):
        err = data["error"]
        raise ApiError("API error: %s" % (err.get("message") if isinstance(err, dict) else err))
    choices = data.get("choices") or []
    if not choices:
        raise ApiError("The reply had no choices: %s" % json.dumps(data)[:300])
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # some APIs return a list of content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    refusal = message.get("refusal")
    text = content or refusal or ""
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    if not isinstance(reasoning, str):
        reasoning = json.dumps(reasoning)
    reasoning_in_content = False
    if not reasoning and "</think>" in text:
        # Some servers leave the reasoning inline, ending with </think>; keep it out of the graded answer.
        reasoning, text = text.rsplit("</think>", 1)
        reasoning = reasoning.replace("<think>", "", 1).strip()
        text = text.strip()
        reasoning_in_content = True
    usage = data.get("usage") or {}
    return {
        "text": text,
        "reasoning": reasoning.strip(),
        "reasoning_in_content": reasoning_in_content,
        "model": data.get("model"),
        "finish_reason": choice.get("finish_reason"),
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "api_refusal": bool(refusal) or choice.get("finish_reason") == "content_filter",
    }


def call_model(cfg, messages, stop_event=None):
    """Send one conversation to the model and return its reply text plus metadata."""
    headers = {}
    if cfg["provider"] == "anthropic":
        url = cfg["base_url"] + "/messages"
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if cfg["api_key"]:
            headers["x-api-key"] = cfg["api_key"]
        body = {"model": cfg["model"], "max_tokens": cfg["max_tokens"], "messages": messages}
        if cfg["system_prompt"]:
            body["system"] = cfg["system_prompt"]
    else:
        url = cfg["base_url"] + "/chat/completions"
        if cfg["api_key"]:
            headers["Authorization"] = "Bearer " + cfg["api_key"]
        system = [{"role": "system", "content": cfg["system_prompt"]}] if cfg["system_prompt"] else []
        body = {"model": cfg["model"], "messages": system + messages}
        if cfg["max_tokens"] is not None:
            # OpenAI's own API wants max_completion_tokens; most compatible APIs still use max_tokens.
            key = "max_completion_tokens" if "api.openai.com" in cfg["base_url"] else "max_tokens"
            body[key] = cfg["max_tokens"]
    if cfg["temperature"] is not None:
        body["temperature"] = cfg["temperature"]
    body.update(cfg["extra_params"])

    started = time.monotonic()
    data, attempts = post_json(url, headers, body, stop_event)
    result = parse_anthropic(data) if cfg["provider"] == "anthropic" else parse_openai(data)
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    result["attempts"] = attempts
    return result


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def resolve_json_path(name):
    """Resolve a file name typed on the page to a .json file inside the project folder."""
    name = (name or "").strip()
    if not name:
        raise UserError("Enter a file name.")
    path = (PROJECT_DIR / name).resolve()
    if PROJECT_DIR not in path.parents:
        raise UserError("Files must be inside %s." % PROJECT_DIR)
    if path.suffix.lower() != ".json":
        raise UserError("File names must end in .json.")
    return path


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError as e:
        raise UserError("%s is not valid JSON (%s)." % (path.name, e))


def split_dataset(source, name):
    """Return (header fields, prompt list) from a dataset file."""
    if isinstance(source, list):
        header, prompts = {}, source
    elif isinstance(source, dict) and isinstance(source.get("prompts"), list):
        header = {k: v for k, v in source.items() if k not in ("prompts", "run_metadata")}
        prompts = source["prompts"]
    else:
        raise UserError('%s should be a JSON object with a "prompts" list.' % name)
    seen = set()
    for p in prompts:
        if not (isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("prompt"), str)):
            raise UserError('Every item in %s needs a text "id" and "prompt".' % name)
        if p["id"] in seen:
            raise UserError("%s has a duplicate id: %s" % (name, p["id"]))
        seen.add(p["id"])
    return header, prompts


def write_json_atomic(path, doc):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Eval session: loaded files plus the current run
# ---------------------------------------------------------------------------

class EvalSession:
    def __init__(self):
        self.lock = threading.RLock()
        self.input_path = None
        self.output_path = None
        self.doc = None  # the output document, kept in sync with the file on disk
        self.by_id = {}
        self.active = {}  # prompt id -> "queued" | "running" during a run
        self.run = None
        self.stop_event = threading.Event()
        self.log = []

    def is_running(self):
        return bool(self.run) and self.run["state"] in ("running", "stopping")

    def log_line(self, message):
        line = "%s  %s" % (datetime.now().strftime("%H:%M:%S"), message)
        self.log.append(line)
        del self.log[:-200]
        print(line, flush=True)

    # ----- loading -----

    def load(self, input_name, output_name):
        with self.lock:
            if self.is_running():
                raise UserError("Stop the current run before loading files.")
            input_path = resolve_json_path(input_name)
            output_path = resolve_json_path(output_name)
            if input_path == output_path:
                raise UserError("The output file must be different from the prompts file.")
            if not input_path.exists():
                raise UserError("Can't find %s in %s." % (input_path.name, PROJECT_DIR))
            header, prompts = split_dataset(read_json(input_path), input_path.name)
            if not prompts:
                raise UserError("%s has no prompts." % input_path.name)

            previous, run_metadata = {}, None
            if output_path.exists():
                existing = read_json(output_path)
                _, old_prompts = split_dataset(existing, output_path.name)
                previous = {p["id"]: p for p in old_prompts}
                if isinstance(existing, dict):
                    run_metadata = existing.get("run_metadata")

            items = []
            for p in prompts:
                item = copy.deepcopy(p)
                item.setdefault("model_response", "")
                old = previous.get(item["id"])
                # Keep earlier responses only if the prompt text is unchanged.
                if old and old.get("prompt") == item["prompt"]:
                    item["model_response"] = old.get("model_response") or ""
                    if old.get("response_meta"):
                        item["response_meta"] = old["response_meta"]
                items.append(item)

            doc = dict(header)
            if run_metadata:
                doc["run_metadata"] = run_metadata
            doc["prompts"] = items
            self.input_path, self.output_path, self.doc = input_path, output_path, doc
            self.by_id = {p["id"]: p for p in items}
            self.active, self.run = {}, None
            answered = sum(1 for p in items if p.get("model_response"))
            self.log_line("Loaded %d prompts from %s (%d already answered in %s)."
                          % (len(items), input_path.name, answered, output_path.name))
            return self.status(full=True)

    # ----- status -----

    def item_state(self, item):
        meta = item.get("response_meta") or {}
        state = self.active.get(item["id"])
        if not state:
            state = "done" if item.get("model_response") else ("error" if meta.get("error") else "pending")
        return {"id": item["id"], "state": state, "flags": meta.get("flags", [])}

    def status(self, full=False):
        with self.lock:
            if self.doc is None:
                return {"loaded": False, "run": None, "log": self.log[-40:]}
            prompts = self.doc["prompts"]
            states = [self.item_state(p) for p in prompts]
            meta = self.doc.get("run_metadata") or {}
            result = {
                "loaded": True,
                "input": self.input_path.name,
                "output": str(self.output_path.relative_to(PROJECT_DIR)),
                "output_path": str(self.output_path),
                "output_exists": self.output_path.exists(),
                "states": states,
                "settings": meta.get("settings"),
                "run": dict(self.run) if self.run else None,
                "log": self.log[-40:],
            }
            if full:
                result["catalog"] = [
                    {"id": p["id"], "category": p.get("category", ""),
                     "primary_trait": p.get("primary_trait", ""), "prompt": p["prompt"]}
                    for p in prompts
                ]
            return result

    def item(self, prompt_id):
        with self.lock:
            if prompt_id not in self.by_id:
                raise UserError("No prompt with id %s." % prompt_id)
            result = copy.deepcopy(self.by_id[prompt_id])
            result["state"] = self.item_state(self.by_id[prompt_id])
            return result

    # ----- running -----

    def start(self, raw_config, mode, ids=None):
        cfg = parse_config(raw_config)
        with self.lock:
            if self.doc is None:
                raise UserError("Load the prompts file first.")
            if self.is_running():
                raise UserError("A run is already in progress.")
            prompts = self.doc["prompts"]
            settings = recorded_settings(cfg)
            meta = self.doc.get("run_metadata")
            answered = [p for p in prompts if p.get("model_response")]

            if mode == "all":
                for p in prompts:
                    p["model_response"] = ""
                    p.pop("response_meta", None)
                meta = None
            elif answered and meta and meta.get("settings") != settings:
                # Never mix two models or two configurations in one output file.
                old = meta.get("settings") or {}
                raise UserError(
                    "%s already has %d responses made with different settings (model: %s). "
                    "To keep them, type a new output file name and click Load. "
                    "To replace them, use Re-run all."
                    % (self.output_path.name, len(answered), old.get("model_requested", "unknown")))

            if mode == "ids":
                targets = [i for i in (ids or []) if i in self.by_id]
                if not targets:
                    raise UserError("No matching prompt ids to run.")
            else:
                targets = [p["id"] for p in prompts if not p.get("model_response")]
                if not targets:
                    raise UserError("Every prompt already has a response. Use Re-run all to start over.")

            if meta is None:
                meta = {"source_file": self.input_path.name, "started_at": now_iso()}
            meta.update({
                "runner": "run_eval.py",
                "conversation_mode": CONVERSATION_MODE,
                "reasoning_handling": REASONING_NOTE,
                "settings": settings,
            })
            meta.setdefault("models_reported", [])
            self.doc = self._with_metadata(meta)

            self.stop_event = threading.Event()
            work = queue.Queue()
            for prompt_id in targets:
                work.put(prompt_id)
                self.active[prompt_id] = "queued"
            self.run = {"state": "running", "total": len(targets), "finished": 0,
                        "succeeded": 0, "failed": 0, "started_at": now_iso(), "message": ""}
            self._save()
            self.log_line("Started %d prompt(s) on %s with %d parallel request(s)."
                          % (len(targets), cfg["model"], cfg["parallel"]))

            workers = [threading.Thread(target=self._worker, args=(cfg, work), daemon=True)
                       for _ in range(min(cfg["parallel"], len(targets)))]
            for w in workers:
                w.start()
            threading.Thread(target=self._finish_when_done, args=(workers,), daemon=True).start()
            return self.status()

    def stop(self):
        with self.lock:
            if not self.is_running():
                return self.status()
            self.stop_event.set()
            self.run["state"] = "stopping"
            self.run["message"] = "Stopping. Requests already sent will finish and be saved."
            self.log_line("Stop requested.")
            return self.status()

    def _with_metadata(self, meta):
        """Rebuild the document so run_metadata sits just before the prompt list."""
        doc = {k: v for k, v in self.doc.items() if k not in ("run_metadata", "prompts")}
        doc["run_metadata"] = meta
        doc["prompts"] = self.doc["prompts"]
        return doc

    def _worker(self, cfg, work):
        while not self.stop_event.is_set():
            try:
                prompt_id = work.get_nowait()
            except queue.Empty:
                return
            with self.lock:
                self.active[prompt_id] = "running"
                prompt = self.by_id[prompt_id]["prompt"]
            try:
                result = call_model(cfg, [{"role": "user", "content": prompt}], self.stop_event)
            except StopRequested:
                return
            except ApiError as e:
                self._record_error(prompt_id, e)
                continue
            except Exception as e:  # a bug here should not kill the whole run
                self._record_error(prompt_id, ApiError("Unexpected error: %r" % e))
                continue
            self._record_result(prompt_id, result)

    def _record_result(self, prompt_id, result):
        flags = []
        if result["finish_reason"] in ("length", "max_tokens"):
            flags.append("truncated")
        if result.get("api_refusal"):
            flags.append("api_refusal")
        if result.get("reasoning_in_content"):
            flags.append("reasoning_split")
        text = result["text"]
        if not text.strip():
            flags.append("empty")
            text = "[No text returned by the API. finish_reason: %s]" % result["finish_reason"]
        meta = {
            "model": result["model"],
            "finish_reason": result["finish_reason"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "elapsed_seconds": result["elapsed_seconds"],
            "attempts": result["attempts"],
            "timestamp": now_iso(),
        }
        if result.get("stop_details"):
            meta["stop_details"] = result["stop_details"]
        if flags:
            meta["flags"] = flags
        if result.get("reasoning"):
            meta["reasoning"] = result["reasoning"]
        with self.lock:
            item = self.by_id[prompt_id]
            item["model_response"] = text
            item["response_meta"] = meta
            reported = self.doc["run_metadata"]["models_reported"]
            if result["model"] and result["model"] not in reported:
                reported.append(result["model"])
            self.active.pop(prompt_id, None)
            self.run["finished"] += 1
            self.run["succeeded"] += 1
            self.log_line("%s answered (%s output tokens, %.1fs)%s" % (
                prompt_id, result["output_tokens"], result["elapsed_seconds"],
                " [%s]" % ", ".join(flags) if flags else ""))
            self._save()

    def _record_error(self, prompt_id, error):
        with self.lock:
            item = self.by_id[prompt_id]
            self.active.pop(prompt_id, None)
            self.run["finished"] += 1
            self.run["failed"] += 1
            self.log_line("%s failed: %s" % (prompt_id, error))
            if error.fatal:
                # A bad key, model name or URL fails every prompt the same way.
                self._abort("Stopped: %s" % error)
            else:
                if not item.get("model_response"):  # keep an earlier good response on a failed re-run
                    item["response_meta"] = {"error": str(error), "timestamp": now_iso()}
                if self.run["succeeded"] == 0 and self.run["failed"] >= EARLY_FAILURE_LIMIT:
                    self._abort("Stopped because the first %d prompts all failed. Last error: %s"
                                % (self.run["failed"], error))
            self._save()

    def _abort(self, message):
        self.run["message"] = message
        self.run["aborted"] = True
        self.stop_event.set()
        self.log_line(message)

    def _finish_when_done(self, workers):
        for w in workers:
            w.join()
        with self.lock:
            self.active.clear()
            run = self.run
            if run.get("aborted"):
                run["state"] = "aborted"
            elif self.stop_event.is_set():
                run["state"] = "stopped"
                run["message"] = "Stopped. Run unanswered prompts to continue."
            else:
                run["state"] = "done"
            run["ended_at"] = now_iso()
            self._save()
            self.log_line("Run %s: %d answered, %d failed. Saved to %s."
                          % (run["state"], run["succeeded"], run["failed"], self.output_path.name))

    def _save(self):
        prompts = self.doc["prompts"]
        meta = self.doc.get("run_metadata")
        if meta is not None:
            meta["last_updated_at"] = now_iso()
            meta["totals"] = {
                "prompts": len(prompts),
                "answered": sum(1 for p in prompts if p.get("model_response")),
                "errors": sum(1 for p in prompts if (p.get("response_meta") or {}).get("error")),
                "flagged": sum(1 for p in prompts if (p.get("response_meta") or {}).get("flags")),
            }
        write_json_atomic(self.output_path, self.doc)


def chat(raw_config, messages):
    cfg = parse_config(raw_config)
    if not isinstance(messages, list) or not messages:
        raise UserError("Nothing to send.")
    cleaned = []
    for m in messages:
        if not (isinstance(m, dict) and m.get("role") in ("user", "assistant")
                and isinstance(m.get("content"), str)):
            raise UserError("Malformed chat message.")
        cleaned.append({"role": m["role"], "content": m["content"]})
    return call_model(cfg, cleaned)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

SESSION = EvalSession()


class Handler(BaseHTTPRequestHandler):
    server_version = "EvalRunner"

    def log_message(self, fmt, *args):
        pass  # keep the terminal for run progress

    def _is_local(self):
        # Refuse requests from other websites open in the browser (DNS rebinding / CSRF).
        allowed = self.server.allowed_hosts
        origin = self.headers.get("Origin")
        return (self.headers.get("Host") in allowed
                and (origin is None or origin in {"http://" + h for h in allowed}))

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._is_local():
            return self._send(403, {"error": "Forbidden"})
        url = urlparse(self.path)
        try:
            if url.path == "/":
                return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
            if url.path == "/api/info":
                return self._send(200, {
                    "env_key": bool(os.environ.get("EVAL_API_KEY")),
                    "tinker_env_key": bool(os.environ.get("TINKER_API_KEY")),
                    "project_dir": str(PROJECT_DIR),
                    "default_input": DEFAULT_INPUT,
                    "default_output": DEFAULT_OUTPUT,
                })
            if url.path == "/api/status":
                full = parse_qs(url.query).get("full") == ["1"]
                return self._send(200, SESSION.status(full=full))
            if url.path == "/api/item":
                return self._send(200, SESSION.item(parse_qs(url.query).get("id", [""])[0]))
            return self._send(404, {"error": "Not found"})
        except UserError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            return self._send(500, {"error": "Internal error: %r" % e})

    def do_POST(self):
        if not self._is_local() or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._send(403, {"error": "Forbidden"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            path = urlparse(self.path).path
            if path == "/api/load":
                return self._send(200, SESSION.load(payload.get("input"), payload.get("output")))
            if path == "/api/run":
                return self._send(200, SESSION.start(payload.get("config"), payload.get("mode"), payload.get("ids")))
            if path == "/api/stop":
                return self._send(200, SESSION.stop())
            if path == "/api/chat":
                return self._send(200, chat(payload.get("config"), payload.get("messages")))
            return self._send(404, {"error": "Not found"})
        except UserError as e:
            return self._send(400, {"error": str(e)})
        except ApiError as e:
            return self._send(502, {"error": str(e)})
        except ValueError:
            return self._send(400, {"error": "Request body was not valid JSON."})
        except Exception as e:
            return self._send(500, {"error": "Internal error: %r" % e})


def main():
    parser = argparse.ArgumentParser(description="Run behavior-eval prompts against a model under test.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="don't open the page automatically")
    args = parser.parse_args()

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        sys.exit("Could not start on port %d (%s). Try: python3 run_eval.py --port %d"
                 % (args.port, e, args.port + 1))
    server.allowed_hosts = {"127.0.0.1:%d" % args.port, "localhost:%d" % args.port}
    url = "http://127.0.0.1:%d" % args.port
    print("Eval runner is open at %s  (press Ctrl+C to quit)" % url, flush=True)
    if os.environ.get("EVAL_API_KEY"):
        print("Using the API key from EVAL_API_KEY unless you enter one on the page.", flush=True)
    elif os.environ.get("TINKER_API_KEY"):
        print("Using TINKER_API_KEY for Tinker URLs unless you enter a key on the page.", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShut down. Every response received so far is saved in the output file.")


if __name__ == "__main__":
    main()
