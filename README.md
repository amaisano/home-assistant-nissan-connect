# MyNISSAN for Home Assistant

[![CI](https://github.com/bvdcode/home-assistant-nissan-connect/actions/workflows/ci.yml/badge.svg)](https://github.com/bvdcode/home-assistant-nissan-connect/actions/workflows/ci.yml)
[![HACS](https://github.com/bvdcode/home-assistant-nissan-connect/actions/workflows/hacs.yml/badge.svg)](https://github.com/bvdcode/home-assistant-nissan-connect/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/bvdcode/home-assistant-nissan-connect/actions/workflows/hassfest.yml/badge.svg)](https://github.com/bvdcode/home-assistant-nissan-connect/actions/workflows/hassfest.yml)
[![Support on Ko-fi](https://img.shields.io/badge/Support_on_Ko--fi-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/bvdcode)

[![Open your Home Assistant instance and open this repository in the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bvdcode&repository=home-assistant-nissan-connect&category=integration)
[![Open your Home Assistant instance and start setting up the MyNISSAN integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=mynissan)

MyNISSAN connects supported Nissan vehicles to Home Assistant through the
MyNISSAN cloud service.

> [!IMPORTANT]
> **This is a fork** of [bvdcode/home-assistant-nissan-connect](https://github.com/bvdcode/home-assistant-nissan-connect)
> v0.3.5. It adds one thing, the `mynissan.refresh` service; see the [CHANGELOG](CHANGELOG.md). To install it, add
> `https://github.com/amaisano/home-assistant-nissan-connect` to HACS as a custom repository (type Integration).
>
> The integration only reads Nissan's cached data on its 15-minute poll. `mynissan.refresh` asks the car itself for
> every vehicle, then refreshes the entities:
>
> ```yaml
> action: mynissan.refresh
> data:
>   kinds: [battery, climate, status, location]  # default: [status]
> ```
>
> `status` and `location` wait for the car's answer (up to 210 s).

The integration provides:

- configuration through the Home Assistant user interface;
- account authentication and automatic token refresh;
- discovery of every vehicle attached to the account;
- one Home Assistant device per vehicle;
- battery level, charging, plugged-in state, range, and climate sensors;
- last reported vehicle location on the Home Assistant map;
- remote climate start, stop, and target-temperature control.

Additional vehicle data and remote commands will be added in subsequent releases.

## Requirements

- Home Assistant 2026.7.4 or newer;
- a MyNISSAN account from the United States or Canada, or a MiNissan account
  from Mexico, with at least one connected vehicle.

## Installation

The integration is available through HACS as a custom repository while its
default-catalog submission is under review.

1. Open HACS.
2. Select **Integrations**.
3. Open the menu and select **Custom repositories**.
4. Add `https://github.com/bvdcode/home-assistant-nissan-connect` as an
   **Integration** repository.
5. Install **MyNISSAN** and restart Home Assistant.

## Configuration

1. Open **Settings → Devices & services**.
2. Select **Add integration**.
3. Search for **MyNISSAN**.
4. Select the account country and enter the email address and password used by
   the MyNISSAN or MiNissan app.

The password is used only while authenticating and is not stored. Home Assistant
stores the issued OAuth tokens and device identifier in the config entry so the
integration can reconnect and refresh its session.

## Development

The integration uses [`pynissan`](https://pypi.org/project/pynissan/) for all
communication with MyNISSAN services.

```bash
python -m pip install -r requirements_test.txt
ruff check .
ruff format --check .
mypy custom_components/mynissan tests
pytest
```

## Project status

This is a community-maintained project and is not affiliated with, endorsed by,
or associated with Nissan Motor Co., Ltd. Nissan and MyNISSAN are trademarks of
their respective owners.
