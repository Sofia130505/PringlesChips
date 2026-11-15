"""Minimal helmcode client: one function, chat(), for both API styles.

Laptop only. Never import this from copilot/: the board must stay offline.

Settings come from environment variables (or orchestration/.env, which is git-ignored):
  HELMCODE_API_KEY   the key (never commit it)
  HELMCODE_BASE_URL  https://api.helmcode.com/v1
  HELMCODE_FORMAT    "openai" (POST {base}/chat/completions) or "anthropic" (POST {base}/messages)
  HELMCODE_MODEL     deepseek-v4-flash (DeepSeek V4.1 Flash, reads text and images)
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# The reasoning text of the last reply on this thread (DeepSeek returns it as
# reasoning_content), so run_agent.py can log it next to the answer.
_last = threading.local()


def last_reasoning():
    return getattr(_last, "reasoning", None)


def last_usage():
    """Token counts of the last reply on this thread, as the API reported them."""
    return getattr(_last, "usage", None)


def _load_dotenv():
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


_load_dotenv()


def settings():
    missing = [k for k in ("HELMCODE_API_KEY", "HELMCODE_BASE_URL", "HELMCODE_MODEL") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"Set {', '.join(missing)} (environment or orchestration/.env)")
    return {
        "key": os.environ["HELMCODE_API_KEY"],
        "base": os.environ["HELMCODE_BASE_URL"].rstrip("/"),
        "format": os.environ.get("HELMCODE_FORMAT", "openai").lower(),
        "model": os.environ["HELMCODE_MODEL"],
    }


def _post(url, headers, payload, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _post_stream(url, headers, payload, timeout):
    """OpenAI-style streaming (server-sent events). Long jobs need it: helmcode's gateway answers
    HTTP 408 when a non-streamed reply takes too long, but a stream keeps the connection alive.
    Returns a dict shaped like a non-streamed response, so chat() handles both the same way."""
    payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"content-type": "application/json", "accept": "text/event-stream", **headers})
    content, reasoning, usage = [], [], None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            usage = chunk.get("usage") or usage
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                content.append(delta.get("content") or "")
                reasoning.append(delta.get("reasoning_content") or delta.get("reasoning") or "")
    return {"choices": [{"message": {"content": "".join(content), "reasoning_content": "".join(reasoning)}}],
            "usage": usage}


def chat(system, user, model=None, max_tokens=8192, temperature=0.2, timeout=300, retries=4, image_b64=None,
         stream=False):
    """Send one system + user turn, return the reply text. image_b64: optional PNG as base64.
    stream=True (OpenAI format only) for long replies; timeout then applies between chunks."""
    s = settings()
    _last.reasoning = _last.usage = None  # never log a previous call's data after a failure
    model = model or s["model"]
    if image_b64 and s["format"] == "anthropic":
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                   {"type": "text", "text": user}]
    elif image_b64:
        content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64}},
                   {"type": "text", "text": user}]
    else:
        content = user
    if s["format"] == "anthropic":
        url = s["base"] + "/messages"
        headers = {"x-api-key": s["key"], "authorization": f"Bearer {s['key']}",
                   "anthropic-version": "2023-06-01"}
        payload = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                   "system": system, "messages": [{"role": "user", "content": content}]}
    else:
        url = s["base"] + "/chat/completions"
        headers = {"authorization": f"Bearer {s['key']}"}
        payload = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": content}]}

    for attempt in range(retries + 1):
        try:
            if stream and s["format"] != "anthropic":
                data = _post_stream(url, headers, payload, timeout)
            else:
                data = _post(url, headers, payload, timeout)
            _last.reasoning = None
            _last.usage = data.get("usage")
            if s["format"] == "anthropic":
                _last.reasoning = "".join(b.get("thinking", "") for b in data["content"]
                                            if b.get("type") == "thinking") or None
                return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            _last.reasoning = message.get("reasoning_content") or message.get("reasoning") or None
            if not content.strip() and message.get("reasoning_content"):
                # Reasoning models spend tokens thinking first; an empty answer means the budget ran out.
                raise RuntimeError("empty content: raise max_tokens")
            return content
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504, 529) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"helmcode HTTP {e.code}: {body}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise


if __name__ == "__main__":  # smoke test: python orchestration/helm.py
    print(chat("Reply with exactly one word.", "Say OK."))
