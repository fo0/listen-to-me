# Assistant (optional LLM cleanup)

Off by default. When enabled, the raw transcript is sent to an
OpenAI-compatible `/chat/completions` endpoint and the _answer_ is inserted
instead. The default configuration targets a local [Ollama](https://ollama.com):

```jsonc
"assistant": {
  "enabled": true,
  "base_url": "http://localhost:11434/v1",
  "api_key": "",
  "model": "llama3.2",
  "system_prompt": "…",   // freely editable in the settings window
  "system_audio": {       // the second profile — see below
    "enabled": false,
    "model": "",          // empty = the shared model above
    "system_prompt": "…"
  }
}
```

The default system prompt fixes punctuation, removes filler words and applies
dictated formatting ("new paragraph", "bullet list") without translating or
rewriting content. Adapt it however you like — e.g. "always answer in formal
German" or "translate everything to English".

**Two profiles, one connection.** A dictation and a recorded meeting want
opposite things from the assistant, so the page has one card per recording
source — **Microphone dictation** and **System audio** — each with its own
switch and its own prompt. What they share is the connection: one endpoint, one
API key, one temperature, one timeout. The system-audio card additionally takes
a **model override** (leave it empty to use the shared model — one endpoint
usually serves one). Its default prompt only tidies the transcript up; it is a
starting point meant to be replaced by whatever you actually want out of a
recorded meeting — minutes, a summary, a translation. The two switches are
independent: turning the assistant on for dictations does not turn it on for
system audio, and a profile whose prompt is empty stays off.

**Test connection** on the Assistant page sends one short sample sentence to the
endpoint with the values currently entered (no _Save_ needed) and shows what
comes back. The dropdown beside the button picks **which profile** it goes
through — the connection is shared between the two, the model override and the
system prompt are not, so a green test of _Microphone dictation_ says nothing
about the model a meeting would actually be sent to. Use it before you rely on
the assistant: it runs after a dictation, so a wrong URL, an unknown model name
or a stopped Ollama would otherwise only show up once you have already spoken —
for system audio, after a recording that may have run for an hour. The status
line names the profile it tested. The reply is shown, not just an "OK" — an
endpoint can answer perfectly while the model or the prompt returns something
you would not want inserted. A running test can be called off with **Cancel** —
the wait is bounded by the request timeout below, which goes up to ten minutes,
and a test against an endpoint that is simply not there should not hold the page
for that long. The request itself cannot be recalled once sent; it is left to run
out on its own and its answer is discarded.

**Request timeout** decides how long a finished dictation is held back waiting
for the answer before the raw transcript is inserted instead. Raise it if your
local model is slow to respond, lower it so an unreachable endpoint fails fast
rather than delaying every recording by two minutes.
