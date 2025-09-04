# Warp Account Manager

![Warp Account Manager](img/en.png)

This extension allows you to easily switch between your accounts.
- No ban issues
- Custom chrome extension

## NOTE

This project is designed to facilitate the use of Warp.dev. No responsibility is accepted.

## Usage Video:
https://youtu.be/5_itpYHZGJc

## Linux Support

This fork adds safer Linux support:

- Windows-specific registry and certificate installation are gated. On Linux, mitmproxy certificate trust is manual.
- Use `start.sh` to install dependencies and run the app.
- After first run, trust `~/.mitmproxy/mitmproxy-ca-cert.pem` in your browser/system trust store to allow HTTPS interception.
- Set your browser/system proxy to `127.0.0.1:8080` when activating an account.

Steps (Linux):

1. `bash start.sh`
2. Manually trust `~/.mitmproxy/mitmproxy-ca-cert.pem` in your browser.
3. Set proxy to `127.0.0.1:8080` while using Warp (the app shows a reminder).
4. Use the GUI to add accounts (Chrome extension or manual JSON) and activate.
