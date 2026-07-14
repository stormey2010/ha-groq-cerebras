# Groq and Cerebras - Home Assistant Custom Integration

[![Release](https://img.shields.io/github/v/release/stormey2010/ha-groq-cerebras?display_name=tag&sort=semver)](https://github.com/stormey2010/ha-groq-cerebras/releases)
[![Stars](https://img.shields.io/github/stars/stormey2010/ha-groq-cerebras)](https://github.com/stormey2010/ha-groq-cerebras/stargazers)
[![License](https://img.shields.io/github/license/stormey2010/ha-groq-cerebras)](LICENSE)

[![Tests](https://img.shields.io/github/actions/workflow/status/stormey2010/ha-groq-cerebras/ci.yml?branch=main&label=tests)](https://github.com/stormey2010/ha-groq-cerebras/actions/workflows/ci.yml)
[![Codecov](https://codecov.io/gh/stormey2010/ha-groq-cerebras/branch/main/graph/badge.svg)](https://codecov.io/gh/stormey2010/ha-groq-cerebras)
[![Hassfest](https://img.shields.io/github/actions/workflow/status/stormey2010/ha-groq-cerebras/hassfest.yml?branch=main&label=hassfest)](https://github.com/stormey2010/ha-groq-cerebras/actions/workflows/hassfest.yml)
[![Quality Scale](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstormey2010%2Fha-groq-cerebras%2Fmain%2Fcustom_components%2Fgroq%2Fmanifest.json&query=%24.quality_scale&label=quality%20scale&cacheSeconds=3600)](https://developers.home-assistant.io/docs/integration_quality_scale_index)

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Open Issues](https://img.shields.io/github/issues/stormey2010/ha-groq-cerebras)](https://github.com/stormey2010/ha-groq-cerebras/issues)
![Development Status](https://img.shields.io/badge/development-active-success?style=flat-square)

This Home Assistant custom integration connects Groq and Cerebras cloud accounts to Assist, AI Tasks, and response actions. Groq accounts also support speech-to-text, text-to-speech, and image analysis.

> [!IMPORTANT]
> This is an unofficial community project. It is not affiliated with, endorsed by, or supported by Groq or Cerebras.
>
> Feature availability, model availability, rate limits, token limits, and billing behavior are controlled by the selected provider and can vary by account, project, and model.

## Supported Functionality

This integration supports Groq and Cerebras cloud accounts. It does not discover or control physical devices.

Cerebras accounts are intentionally limited to Text Generation. They provide Assist conversation agents, AI Task entities, and the `groq.generate_text`/`groq.generate_structured` actions through the Cerebras OpenAI-compatible API. New Cerebras Text Generation services default to:

- endpoint: `https://api.cerebras.ai/v1/chat/completions`
- model: `gpt-oss-120b`
- streaming: enabled
- max tokens: `32768`
- temperature: `1`
- top P: `1`
- reasoning effort: `low`

Supported Home Assistant platforms:

- `conversation`: Assist conversation agents backed by configured Groq text generation services.
- `ai_task`: data generation tasks for services and automations that need structured output.
- `stt`: speech-to-text entities for Home Assistant voice pipelines.
- `tts`: text-to-speech entities for `tts.speak`.

Provided response actions:

- `groq.generate_text`: generate a text response.
- `groq.generate_structured`: generate JSON or schema-shaped output.
- `groq.analyze_image`: ask a question about a camera image, media image, local image, or image URL.
- `groq.extract_text_from_image`: OCR-style text extraction from an image.
- `groq.transcribe_audio`: transcribe a local or media-source audio file.
- `groq.clear_cache`: clear the local response cache for a provider account.
- `groq.list_models`: list models visible to a provider account.

Each configured provider service creates its own Home Assistant device and the relevant entity for that platform. Text generation services can create Assist and AI Task entities. Speech-to-text and text-to-speech services create STT and TTS entities.

## Installation

### HACS

This fork is installed as a HACS custom repository. Use the button below, or add `https://github.com/stormey2010/ha-groq-cerebras` as an **Integration** under HACS -> three-dot menu -> **Custom repositories**.

[![Open your Home Assistant instance and open Groq and Cerebras in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stormey2010&repository=ha-groq-cerebras&category=integration)

1. Open **Groq and Cerebras** in HACS.
2. Select **Download** and choose the latest release.
3. Restart Home Assistant.
4. Go to **Settings -> Devices & services -> Add integration -> Groq and Cerebras**.

### Manual

1. Copy `custom_components/groq` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings -> Devices & services -> Add integration -> Groq and Cerebras**.

## Requirements

- Home Assistant `2026.6.0` or newer. Local development is tested against the minimum supported version.
- A Groq API key from [Groq Console](https://console.groq.com/) or a Cerebras API key from [Cerebras Cloud](https://cloud.cerebras.ai/).
- Network access from Home Assistant to `https://api.groq.com` or `https://api.cerebras.ai`, depending on the selected provider.
- Optional: `ffmpeg` on the Home Assistant host if you enable TTS audio normalization, Long TTS, or processed playback conversion.

This integration does not use Home Assistant application credentials or OAuth. Provider API keys act as account or project credentials. Use separate keys when you want separate projects, billing pools, environments, or rate-limit isolation.

## Configuration

Initial account setup asks for:

- Provider: Groq or Cerebras.
- Name: friendly name for this provider account in Home Assistant.
- API key: secret key used for provider API requests. The key is stored by Home Assistant and redacted from diagnostics.

After adding an account, open the integration page and add one or more services. Cerebras exposes Text Generation only; Groq exposes all of the following:

- Text Generation: name, model, system prompt, temperature, free-tier protection, and optional advanced request options.
- Speech-to-Text: name, model, language hint, and free-tier protection.
- Text-to-Speech: name, model, voice, output format, optional sample rate, optional speed, optional vocal directions, optional audio normalization, optional Long TTS, and free-tier protection.
- Image Recognition: name, model, system prompt, and free-tier protection.

Advanced Text Generation options include max completion tokens, top P, stop sequences, seed, service tier, streaming, reasoning options, local response caching, simple tools, Compound built-in tool allow-lists, structured output schema, strict schema mode, and additional provider request body options.

### Simple tools

Assist can use a deliberately small tool set copied from the companion Codex clone. Every group is opt-in. Weather, Home Assistant entity/device access, and live flight lookup need no extra credentials; credentialed groups are exposed to the model only when their required key or token is present. Memory, shell/code execution, delegation, deep scraping, advanced Home Assistant configuration, booking, playlist editing, calendar writes, and advanced route generation are not included.

In a Text Generation service, enable **Advanced options** and set **Simple tool configuration** to an object like this:

```yaml
enabled:
  - weather
  - web_search
  - home_assistant
  - flight_tracker
  - apple_calendar
  - google_workspace
  - spotify
  - openroute
exa_api_key: YOUR_EXA_KEY
apple_calendar_email: you@icloud.com
apple_calendar_app_password: YOUR_APP_SPECIFIC_PASSWORD
apple_calendar_url: https://caldav.icloud.com/
google_access_token: YOUR_GOOGLE_OAUTH_ACCESS_TOKEN
spotify_access_token: YOUR_SPOTIFY_OAUTH_ACCESS_TOKEN
openroute_api_key: YOUR_OPENROUTESERVICE_KEY
```

Available tools are:

- Weather: current/forecast weather by city or coordinates.
- Web: Exa web search.
- Home Assistant: overview, entity search, state reads, and allowlisted device-control services.
- Flights: nearby aircraft and bounding-box state queries through OpenSky.
- Apple Calendar: list calendars and read events through CalDAV.
- Google Workspace: read Calendar, Contacts, and Gmail; list, create, and complete Tasks.
- Spotify: search/read library and playback state, control playback, queue tracks, and change volume.
- OpenRouteService: forward and reverse geocoding.

Google and Spotify access tokens are used directly and are never refreshed by this integration. Replace them in the service configuration when they expire. The entire Simple tool configuration object is redacted from Home Assistant diagnostics.

Compound built-in tools are opt-in. For `groq/compound` and `groq/compound-mini`, the integration sends an explicit empty built-in tool allow-list unless you enable tools such as web search, visit website, browser automation, code execution, or Wolfram Alpha in the service's advanced options. Enabling these tools allows Groq to run server-side tools and inspect external content for the request.

You can add more than one Groq account. The integration prevents adding the same API key twice.

## Known Limitations

- This is a cloud integration and will not work without internet access to Groq.
- Groq can change model availability, limits, and request option support outside this integration.
- Some advanced options work only on models that support them. The setup flow validates known model capabilities where possible.
- Credentialed simple tools require the listed third-party key or access token, and the provider can apply its own scopes, subscription requirements, and rate limits. Spotify playback controls generally require Premium.
- TTS input is limited by Groq Orpheus model limits. Enable the Long TTS option to split longer announcements and stitch them with `ffmpeg`; this uses more CPU and more Groq request quota. Without Long TTS, overly long requests are blocked locally.
- Groq speech can generate WAV, MP3, FLAC, OGG, or MULAW audio. The integration sends the selected format directly to Groq for single-part announcements without audio processing. When audio normalization or Long TTS is enabled, the integration asks Groq for WAV chunks and uses `ffmpeg` to normalize, stitch, or convert the final playback output.
- TTS sample rate and speed are optional. Leave sample rate unset to use Groq's model default or the integration's playback profile; use speed `1.0` for normal playback.
- Long TTS, audio normalization, and playback conversion need `ffmpeg` and use extra CPU.
- This integration does not discover devices. It supports Groq cloud accounts and user-created Groq service entries.

## Troubleshooting

- Invalid API key: create or copy a fresh key from Groq Console, then reauthenticate the Groq integration entry.
- Cannot connect: check Home Assistant network/DNS access to `api.groq.com` and the [Groq status page](https://groqstatus.com/).
- Model missing: use `groq.list_models` to see models visible to the selected account, or choose a known compatible model.
- Service actions: provide `service_id` for Text Generation, Image Recognition, and Speech-to-Text actions so automations keep using the intended configured Groq service. Provide `config_entry_id` for account-level actions such as clearing the cache or listing models.
- Rate-limit errors: wait for Groq's reset window, lower automation frequency, choose a smaller model, or use separate Groq projects/keys where appropriate.
- TTS audio processing fails: install `ffmpeg` on the Home Assistant host, choose direct single-part playback without audio normalization, or disable Long TTS.
- Local image or audio file fails: make sure the path is allowed by Home Assistant `allowlist_external_dirs`, or use a media-source file.
- Diagnostics: download diagnostics from the integration page. API keys and prompt fields are redacted.

## Removal

1. Go to Settings -> Devices & services -> Groq.
2. Delete any Groq service entries you no longer want.
3. Delete the Groq account entry.
4. Restart Home Assistant if you plan to remove the custom integration files.
5. If installed through HACS, remove Groq from HACS. For a manual install, delete `custom_components/groq`.

Removing the integration stops future Groq API calls from Home Assistant. It does not delete Groq projects, keys, billing data, or logs in Groq Console.

## Useful Links

- [Project repository](https://github.com/stormey2010/ha-groq-cerebras)
- [Groq Console](https://console.groq.com/)
- [Groq status page](https://groqstatus.com/)
- [Groq API reference](https://console.groq.com/docs/api-reference)
- [Architecture notes](docs/architecture.md)
